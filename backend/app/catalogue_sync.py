"""Safe local orchestration, snapshots, diffs, and review queues for catalogues."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.catalogue_adapters import CatalogueFetchResult, fetch_catalogue
from app.catalogue_classifier import DatasetAssessment, MaintenancePolicy, classify_dataset, load_policy
from app.catalogue_models import CATALOGUE_PORTALS, CatalogueDataset, CataloguePortalConfig, DatasetResource
from app.catalogue_store import persist_catalogue_assessment, persist_catalogue_result
from app.db import get_connection, run_migrations

ADAPTER_VERSION = "1"
SNAPSHOT_SCHEMA_VERSION = 1
SyncStatus = Literal["complete", "partial", "failed"]


@dataclass(frozen=True)
class PortalSyncOutcome:
    portal_id: str
    status: SyncStatus
    observed_at: datetime
    dataset_count: int = 0
    resource_count: int = 0
    complete: bool = False
    warnings: tuple[str, ...] = ()
    snapshot_path: Path | None = None
    content_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SyncRunSummary:
    status: SyncStatus
    portals: Mapping[str, PortalSyncOutcome]
    review_queue_path: Path

    @property
    def exit_code(self) -> int:
        return {"complete": 0, "partial": 2, "failed": 1}[self.status]

    @property
    def snapshot_paths(self) -> tuple[Path, ...]:
        return tuple(
            outcome.snapshot_path
            for outcome in self.portals.values()
            if outcome.snapshot_path is not None
        )


@dataclass(frozen=True)
class SnapshotChange:
    kind: str
    source_dataset_id: str
    before: Any = None
    after: Any = None


@dataclass(frozen=True)
class SnapshotDiff:
    before: Path
    after: Path
    changes: tuple[SnapshotChange, ...]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


_SENSITIVE_KEY = re.compile(
    r"^(?:authorization|auth|cookie|credential|password|secret|token|"
    r"api[_-]?key|access[_-]?token|client[_-]?secret|signature|sig|"
    r"security[_-]?token|x[_-]amz[_-](?:credential|signature|security[_-]?token)|"
    r"x[_-]goog[_-](?:credential|signature)|awsaccesskeyid|googleaccessid|"
    r"key[_-]?pair[_-]?id)$",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b([a-z0-9_-]+)(\s*[=:]\s*)[^\s,;&]+"
)
_AUTHORIZATION_SECRET = re.compile(
    r"(?i)\b(authorization)\s*[=:]\s*[^,;\r\n]+"
)
_COOKIE_SECRET = re.compile(r"(?i)\b(cookie)\s*[=:]\s*[^,\r\n]+")
_AUTH_SCHEME_SECRET = re.compile(
    r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=-]+)"
)
_QUERY_VALUE_DECODE_ROUNDS = 3
_NESTED_URL_REDACTION_ROUNDS = 3
_VALID_PERCENT_ESCAPE = re.compile(r"[0-9a-fA-F]{2}")


def _is_sensitive_name(value: str) -> bool:
    """Return whether the complete value is an exact sensitive field name."""
    return _SENSITIVE_KEY.fullmatch(value) is not None


def _is_sensitive_pair(value: str) -> bool:
    """Return whether decoded data starts with an exact sensitive pair."""
    key, separator, _ = value.partition("=")
    return bool(separator and _is_sensitive_name(key.strip()))


def _decoded_key_is_sensitive(value: str) -> bool:
    """Reject canonical names hidden by whitespace or encoded delimiters."""
    return any(
        _is_sensitive_name(part.partition("=")[0].strip())
        for part in re.split(r"[&;]", value)
    )


def _has_malformed_percent_escape(value: str) -> bool:
    """Return whether any percent sign is not followed by two hex digits."""
    offset = 0
    while True:
        offset = value.find("%", offset)
        if offset < 0:
            return False
        if not _VALID_PERCENT_ESCAPE.fullmatch(value[offset + 1 : offset + 3]):
            return True
        offset += 3


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _is_private_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def _safe_url(
    value: str, *, nested_url_rounds: int = _NESTED_URL_REDACTION_ROUNDS
) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED_URL]"
    if parsed.username or parsed.password or _is_private_host(parsed.hostname):
        return "[REDACTED_URL]"
    # Preserve benign query parameters; remove only sensitive ones.
    safe_query = _filter_sensitive_query(
        parsed.query, nested_url_rounds=nested_url_rounds
    )
    safe_fragment = _filter_sensitive_fragment(
        parsed.fragment, nested_url_rounds=nested_url_rounds
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, safe_query, safe_fragment)
    )


def _filter_sensitive_query(
    query: str, *, nested_url_rounds: int = _NESTED_URL_REDACTION_ROUNDS
) -> str:
    """Remove sensitive query parameters while preserving benign ones."""
    if not query:
        return ""
    from urllib.parse import urlencode

    pairs: list[tuple[str, str]] = []

    # Only literal source delimiters define query structure. Encoded
    # delimiters are decoded later and remain inside their original value.
    for segment in re.split(r"[&;]", query):
        if not segment:
            continue
        raw_key, separator, raw_value = segment.partition("=")
        key, complete = _bounded_url_decode(raw_key, form_encoded=True)
        if not complete or _decoded_key_is_sensitive(key):
            continue
        value = (
            _redact_query_value(raw_value, nested_url_rounds=nested_url_rounds)
            if separator
            else ""
        )
        pairs.append((key, value))

    return urlencode(pairs)


def _bounded_url_decode(value: str, *, form_encoded: bool) -> tuple[str, bool]:
    """Decode at most the fixed budget and report residual valid encoding."""
    from urllib.parse import unquote, unquote_plus

    decoded = value
    for round_index in range(_QUERY_VALUE_DECODE_ROUNDS):
        if _has_malformed_percent_escape(decoded) or _has_control_character(decoded):
            return decoded, False
        decoder = unquote_plus if form_encoded and round_index == 0 else unquote
        further_decoded = decoder(decoded)
        if _has_control_character(further_decoded):
            return further_decoded, False
        if further_decoded == decoded:
            return decoded, True
        decoded = further_decoded
    return decoded, (
        not _has_malformed_percent_escape(decoded)
        and not _has_control_character(decoded)
        and unquote(decoded) == decoded
    )


def _remove_sensitive_value_pairs(value: str) -> str:
    """Remove credential pairs from decoded value data without promoting it."""
    parts = re.split(r"([;&])", value)
    retained: list[str] = []
    for index in range(0, len(parts), 2):
        part = parts[index]
        if _is_sensitive_pair(part):
            continue
        if retained and index:
            retained.append(parts[index - 1])
        retained.append(part)
    return "".join(retained)


def _redact_query_value(
    value: str, *, nested_url_rounds: int, form_encoded: bool = True
) -> str:
    """Decode and redact one retained URL value without reparsing its contents."""
    decoded, complete = _bounded_url_decode(value, form_encoded=form_encoded)
    if not complete:
        return "[REDACTED]"
    safe_value = _redact_non_url_text(_remove_sensitive_value_pairs(decoded))
    return _redact_nested_urls(
        safe_value, nested_url_rounds=nested_url_rounds
    )


def _redact_nested_urls(value: str, *, nested_url_rounds: int) -> str:
    """Redact embedded URLs with a single budget shared across all components."""
    if nested_url_rounds <= 0:
        return "[REDACTED_URL]" if _URL.search(value) else value
    return _URL.sub(
        lambda match: _safe_url(
            match.group(0), nested_url_rounds=nested_url_rounds - 1
        ),
        value,
    )


def _redact_fragment_value(value: str, *, nested_url_rounds: int) -> str:
    """Redact fragment data while preserving its benign source representation."""
    from urllib.parse import quote

    decoded, complete = _bounded_url_decode(value, form_encoded=False)
    if not complete:
        return quote("[REDACTED]", safe="")
    safe_value = _remove_sensitive_value_pairs(decoded)
    redacted_value = _redact_non_url_text(safe_value)
    plus_as_space = _redact_non_url_text(safe_value.replace("+", " "))
    if plus_as_space != safe_value.replace("+", " "):
        redacted_value = plus_as_space
    redacted_value = _redact_nested_urls(
        redacted_value, nested_url_rounds=nested_url_rounds
    )
    if redacted_value == decoded:
        return value
    return quote(redacted_value, safe="/-._~")


def _filter_plain_fragment(fragment: str, *, nested_url_rounds: int) -> str:
    """Filter pair-like fragment chunks without reparsing encoded delimiters."""
    from urllib.parse import quote

    parts = re.split(r"([&;])", fragment)
    retained: list[str] = []
    for index in range(0, len(parts), 2):
        segment = parts[index]
        if not segment:
            continue
        raw_key, separator, raw_value = segment.partition("=")
        key, complete = _bounded_url_decode(raw_key, form_encoded=False)
        if not complete or _decoded_key_is_sensitive(key):
            continue
        if separator:
            value = _redact_fragment_value(
                raw_value, nested_url_rounds=nested_url_rounds
            )
            safe_segment = (
                f"{quote(key, safe='/-._~')}={value}"
            )
        else:
            safe_segment = _redact_fragment_value(
                segment, nested_url_rounds=nested_url_rounds
            )
        if retained and index:
            retained.append(parts[index - 1])
        retained.append(safe_segment)
    return "".join(retained)


def _filter_sensitive_fragment(
    fragment: str, *, nested_url_rounds: int = _NESTED_URL_REDACTION_ROUNDS
) -> str:
    """Preserve public fragments while removing credential-bearing pairs."""
    if not fragment:
        return ""
    prefix, separator, query = fragment.partition("?")
    if separator:
        safe_query = _filter_sensitive_query(
            query, nested_url_rounds=nested_url_rounds
        )
        safe_prefix = _redact_fragment_value(
            prefix, nested_url_rounds=nested_url_rounds
        )
        return f"{safe_prefix}?{safe_query}" if safe_query else safe_prefix

    return _filter_plain_fragment(
        fragment, nested_url_rounds=nested_url_rounds
    )


def _redact_non_url_text(value: str) -> str:
    text = _AUTHORIZATION_SECRET.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", value
    )
    text = _COOKIE_SECRET.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    text = _KEY_VALUE_SECRET.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}[REDACTED]"
            if _is_sensitive_name(match.group(1))
            else match.group(0)
        ),
        text,
    )
    return _AUTH_SCHEME_SECRET.sub(_redact_auth_scheme, text)


_BENIGN_PROSE_WORDS = frozenset({"metadata", "information"})


def _redact_auth_scheme(match: re.Match[str]) -> str:
    """Redact opaque auth values without destroying ordinary scheme-like prose."""
    scheme = match.group(1)
    credential = match.group(2)
    if scheme.casefold() not in ("bearer", "basic"):
        return "[REDACTED]"
    # Long opaque tokens are always credential-shaped.
    if len(credential) >= 16:
        return "[REDACTED]"
    # Short Basic values that decode from base64 to include ':' are
    # credential pairs (e.g. "YTpi" → "a:b").  Check before the prose
    # guard because short base64 can be purely alphabetic.
    if scheme.casefold() == "basic" and _is_short_base64_credential(credential):
        return "[REDACTED]"
    # Specific benign prose: "Basic metadata ..." or "Bearer information ..."
    # where the word after the scheme is a known common English noun.
    if credential.casefold() in _BENIGN_PROSE_WORDS:
        return match.group(0)
    # Purely alphabetic values of typical English-word length are credential-shaped.
    if credential.isalpha() and len(credential) >= 4:
        return "[REDACTED]"
    # Anything with non-letter characters (digits, punctuation) in a
    # short token is credential-shaped rather than prose.
    if not credential.isalpha():
        return "[REDACTED]"
    return match.group(0)


def _is_short_base64_credential(value: str) -> bool:
    """Return True when *value* looks like a short base64-encoded credential."""
    if len(value) < 4 or not value.isascii():
        return False
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(padded, validate=True)
    except Exception:
        return False
    return b":" in decoded


def _safe_text(value: str) -> str:
    urls_redacted = _URL.sub(lambda match: _safe_url(match.group(0)), value)
    return _redact_non_url_text(urls_redacted)


def safe_error(error: Exception) -> str:
    """Describe a failure without reflecting its potentially sensitive body."""
    return f"{type(error).__name__}: operation failed"


def redact(value: Any) -> Any:
    """Recursively remove authentication material and private endpoint details."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_name(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _snapshot_core(result: CatalogueFetchResult) -> dict[str, Any]:
    return redact(
        {
            "datasets": [dataset.model_dump(mode="json") for dataset in result.datasets],
            "resources": [resource.model_dump(mode="json") for resource in result.resources],
            "raw_pages": list(result.raw_pages),
        }
    )


def _without_model_observation_clock(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strip generated model clocks without changing embedded source provenance."""
    cleaned = {key: item for key, item in value.items() if key != "observed_at"}
    for nested_field in ("resources", "classification_evidence"):
        nested = cleaned.get(nested_field)
        if isinstance(nested, list):
            cleaned[nested_field] = [
                _without_model_observation_clock(item) if isinstance(item, Mapping) else item
                for item in nested
            ]
    return cleaned


def _snapshot_identity(core: Mapping[str, Any]) -> dict[str, Any]:
    """Return hash input with only FlexCompass-generated clocks removed."""
    identity = dict(core)
    for model_collection in ("datasets", "resources"):
        values = identity.get(model_collection)
        if isinstance(values, list):
            identity[model_collection] = [
                _without_model_observation_clock(item) if isinstance(item, Mapping) else item
                for item in values
            ]
    normalised = _normalise_semantically_unordered(identity)
    if not isinstance(normalised, dict):
        raise ValueError("snapshot identity must be a JSON object")
    return normalised


_UNORDERED_SOURCE_LIST_KEYS = frozenset(
    {
        "attachments",
        "alternative_exports",
        "classification_evidence",
        "datasets",
        "groups",
        "resources",
        "results",
        "tags",
        "themes",
    }
)
_UNORDERED_IDENTITY_FIELDS = {
    "attachments": ("id", "url", "name", "title"),
    "alternative_exports": ("id", "url", "name", "title"),
    "classification_evidence": ("id",),
    "datasets": ("source_dataset_id", "id"),
    "groups": ("id", "name", "title"),
    "resources": ("id", "source_resource_id", "url", "name", "title"),
    "results": ("name", "id", "dataset_id", "dataset_uid"),
}


def _unordered_source_item_key(
    field_name: str | None,
    value: Any,
) -> tuple[str, bytes]:
    if isinstance(value, Mapping):
        for identity_field in _UNORDERED_IDENTITY_FIELDS.get(field_name or "", ()):
            identity = value.get(identity_field)
            if isinstance(identity, str) and identity:
                return identity, _canonical_json(value)
    return "", _canonical_json(value)


def _normalise_semantically_unordered(
    value: Any,
    field_name: str | None = None,
) -> Any:
    """Normalise known set-like source arrays without mutating raw provenance."""
    if isinstance(value, Mapping):
        return {
            key: _normalise_semantically_unordered(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [
            _normalise_semantically_unordered(item)
            for item in value
        ]
        if field_name in _UNORDERED_SOURCE_LIST_KEYS:
            return sorted(
                items,
                key=lambda item: _unordered_source_item_key(field_name, item),
            )
        return items
    return value


def _redacted_result(result: CatalogueFetchResult, core: Mapping[str, Any]) -> CatalogueFetchResult:
    """Rebuild persistence contracts from the same redacted snapshot content."""
    return CatalogueFetchResult(
        portal_id=result.portal_id,
        observed_at=result.observed_at,
        datasets=[CatalogueDataset.model_validate(item) for item in core["datasets"]],
        resources=[DatasetResource.model_validate(item) for item in core["resources"]],
        expected_count=result.expected_count,
        complete=result.complete,
        warnings=tuple(redact(result.warnings)),
        raw_pages=tuple(core["raw_pages"]),
    )


def _timestamp_directory(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(payload) + b"\n"
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"immutable snapshot already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _classify(
    result: CatalogueFetchResult,
    policy: MaintenancePolicy,
    now: datetime,
) -> list[tuple[Any, DatasetAssessment]]:
    assessments: list[tuple[Any, DatasetAssessment]] = []
    for dataset in result.datasets:
        resources = [
            resource
            for resource in result.resources
            if resource.source_dataset_id == dataset.source_dataset_id
        ]
        assessment = classify_dataset(
            dataset,
            resources,
            dataset.classification_evidence,
            policy,
            now,
        )
        assessments.append((dataset, assessment))
    return assessments


def _persist_assessments(
    conn: sqlite3.Connection,
    observation_id: str,
    assessments: Sequence[tuple[Any, DatasetAssessment]],
    now: datetime,
) -> None:
    for dataset, assessment in assessments:
        dimensions = (
            ("lifecycle", assessment.lifecycle, assessment.lifecycle_confidence, assessment.lifecycle_evidence),
            (
                "publication_pattern",
                assessment.publication_pattern,
                assessment.pattern_confidence,
                assessment.pattern_evidence,
            ),
            ("access", assessment.access_status, assessment.access_confidence, assessment.access_evidence),
            (
                "maintenance",
                assessment.maintenance_state,
                assessment.maintenance_confidence,
                assessment.maintenance_evidence,
            ),
        )
        for name, value, confidence, evidence in dimensions:
            unknown = getattr(value, "value", value) == "unknown"
            persist_catalogue_assessment(
                conn,
                assessment_id=f"{dataset.portal_id}:{dataset.source_dataset_id}:{name}",
                portal_id=dataset.portal_id,
                source_dataset_id=dataset.source_dataset_id,
                observation_id=observation_id,
                assessment_type=name,
                assessment_value=getattr(value, "value", value),
                confidence=confidence.value,
                rationale=[item.evidence for item in evidence]
                or (["Missing published evidence; no value was inferred."] if unknown else []),
                missing_evidence=[f"published evidence for {name}"] if unknown and not evidence else [],
                assessed_at=now,
            )


def _review_items(assessments: Sequence[tuple[Any, DatasetAssessment]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for dataset, assessment in assessments:
        dimensions = (
            ("lifecycle", assessment.lifecycle, assessment.lifecycle_evidence),
            ("publication_pattern", assessment.publication_pattern, assessment.pattern_evidence),
            ("access", assessment.access_status, assessment.access_evidence),
            ("maintenance", assessment.maintenance_state, assessment.maintenance_evidence),
        )
        for dimension, value, evidence in dimensions:
            if getattr(value, "value", value) != "unknown":
                continue
            reason = "conflict" if evidence else "missing_evidence"
            stable = f"{dataset.portal_id}\n{dataset.source_dataset_id}\n{dimension}\n{reason}"
            items.append(
                {
                    "id": hashlib.sha256(stable.encode()).hexdigest(),
                    "portal_id": dataset.portal_id,
                    "source_dataset_id": dataset.source_dataset_id,
                    "dimension": dimension,
                    "reason": reason,
                    "evidence_ids": sorted(item.id for item in evidence),
                }
            )
    return items


def _sync_one(
    portal_id: str,
    portal: CataloguePortalConfig,
    client_factory: Callable[[CataloguePortalConfig], httpx.Client],
    db_path: Path,
    output_dir: Path,
    now: datetime,
    fetcher: Callable[[CataloguePortalConfig, Any, datetime], CatalogueFetchResult],
    policy: MaintenancePolicy,
) -> tuple[PortalSyncOutcome, list[dict[str, Any]]]:
    client = client_factory(portal)
    try:
        result = fetcher(portal, client, now)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    if result.portal_id != portal_id:
        raise ValueError("adapter result portal does not match requested portal")
    core = _snapshot_core(result)
    content_hash = hashlib.sha256(_canonical_json(_snapshot_identity(core))).hexdigest()
    redacted_result = _redacted_result(result, core)
    assessments = _classify(redacted_result, policy, now)
    snapshot_path = output_dir / _timestamp_directory(now) / f"{portal_id}.json"
    status: SyncStatus = "complete" if result.complete else "partial"
    manifest = {
        "adapter_version": ADAPTER_VERSION,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "observed_at": now.astimezone(timezone.utc).isoformat(),
        "portal_id": portal_id,
        "portal_status": status,
        "dataset_count": len(result.datasets),
        "resource_count": len(result.resources),
        "expected_count": result.expected_count,
        "complete": result.complete,
        "warnings": redact(list(result.warnings)),
        "snapshot_path": snapshot_path.as_posix(),
        "content_hash": content_hash,
    }
    _validated_snapshot({"manifest": manifest, **core})
    snapshot_existed = snapshot_path.exists()
    try:
        with get_connection(db_path) as conn:
            conn.execute("BEGIN")
            persisted = persist_catalogue_result(
                conn,
                redacted_result,
                snapshot_path.as_posix(),
                content_hash,
                status=status,
            )
            _persist_assessments(conn, persisted.observation_id, assessments, now)
            _write_json_atomic(snapshot_path, {"manifest": manifest, **core})
    except Exception:
        if not snapshot_existed:
            snapshot_path.unlink(missing_ok=True)
        raise
    return (
        PortalSyncOutcome(
            portal_id=portal_id,
            status=status,
            observed_at=now,
            dataset_count=len(result.datasets),
            resource_count=len(result.resources),
            complete=result.complete,
            warnings=tuple(redact(result.warnings)),
            snapshot_path=snapshot_path,
            content_hash=content_hash,
        ),
        _review_items(assessments),
    )


def sync_catalogues(
    portal_ids: Sequence[str],
    client_factory: Callable[[CataloguePortalConfig], httpx.Client],
    db_path: Path,
    output_dir: Path,
    now: datetime,
    *,
    fetcher: Callable[[CataloguePortalConfig, Any, datetime], CatalogueFetchResult] = fetch_catalogue,
    review_queue_path: Path | None = None,
    policy_path: Path | None = None,
) -> SyncRunSummary:
    """Synchronise approved public catalogues independently using read-only adapters."""
    unknown = sorted(set(portal_ids) - set(CATALOGUE_PORTALS))
    if unknown:
        raise ValueError(f"unsupported catalogue portal: {', '.join(unknown)}")
    if not portal_ids:
        raise ValueError("at least one catalogue portal is required")
    root = Path(__file__).resolve().parents[2]
    policy = load_policy(policy_path or root / "data" / "catalogue" / "maintenance-policy.json")
    run_migrations(db_path)
    outcomes: dict[str, PortalSyncOutcome] = {}
    review_items: list[dict[str, Any]] = []
    for portal_id in portal_ids:
        try:
            outcome, items = _sync_one(
                portal_id,
                CATALOGUE_PORTALS[portal_id],
                client_factory,
                db_path,
                output_dir,
                now,
                fetcher,
                policy,
            )
            outcomes[portal_id] = outcome
            review_items.extend(items)
        except Exception as error:  # failures are isolated at the portal boundary
            outcomes[portal_id] = PortalSyncOutcome(
                portal_id=portal_id,
                status="failed",
                observed_at=now,
                error=safe_error(error),
            )
    statuses = {outcome.status for outcome in outcomes.values()}
    if statuses == {"complete"}:
        run_status: SyncStatus = "complete"
    elif statuses == {"failed"}:
        run_status = "failed"
    else:
        run_status = "partial"
    queue_path = review_queue_path or root / "data" / "cache" / "catalogue" / "review-queue.json"
    # Replace items only for portals with a fresh complete or partial classification
    # pass. Preserve existing items for failed and unrequested portals.
    refreshed_portals = {
        portal_id for portal_id, outcome in outcomes.items() if outcome.status != "failed"
    }
    retained: list[dict[str, Any]] = []
    if queue_path.exists():
        try:
            previous_queue = json.loads(queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_queue = []
        if isinstance(previous_queue, list):
            retained = [
                item
                for item in previous_queue
                if isinstance(item, dict)
                and item.get("portal_id") not in refreshed_portals
            ]
    merged: dict[str, dict[str, Any]] = {}
    for item in [*retained, *review_items]:
        normalised = _normalise_review_item(item)
        if normalised is not None:
            merged[normalised["id"]] = normalised
    _write_replaceable_json(queue_path, sorted(merged.values(), key=lambda item: item["id"]))
    return SyncRunSummary(run_status, outcomes, queue_path)


def _write_replaceable_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(_canonical_json(redact(payload)) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalise_review_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    stable_fields = ("portal_id", "source_dataset_id", "dimension", "reason")
    if not all(isinstance(value.get(field), str) and value[field] for field in stable_fields):
        return None
    evidence_ids = value.get("evidence_ids", [])
    if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
        return None
    item = dict(value)
    item["evidence_ids"] = sorted(set(evidence_ids))
    if not isinstance(item.get("id"), str) or not item["id"]:
        stable = "\n".join(str(item[field]) for field in stable_fields)
        item["id"] = hashlib.sha256(stable.encode()).hexdigest()
    return item


def _snapshot_portal(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("snapshot must be a JSON object")
    manifest = payload.get("manifest")
    portal_id = manifest.get("portal_id") if isinstance(manifest, Mapping) else None
    if not isinstance(portal_id, str) or not portal_id:
        raise ValueError("snapshot manifest must contain portal_id")
    return portal_id


@dataclass(frozen=True)
class _ValidatedSnapshot:
    portal_id: str
    complete: bool
    datasets: Mapping[str, Mapping[str, Any]]


def _validated_snapshot(payload: Any) -> _ValidatedSnapshot:
    """Validate manifest, provenance graph, and content identity for a snapshot."""
    portal_id = _snapshot_portal(payload)
    manifest = payload["manifest"]
    if manifest.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema version")
    status = manifest.get("portal_status")
    complete = manifest.get("complete")
    if status not in {"complete", "partial"} or not isinstance(complete, bool):
        raise ValueError("snapshot manifest has invalid completeness semantics")
    if complete != (status == "complete"):
        raise ValueError("snapshot manifest has inconsistent completeness semantics")

    collections: dict[str, list[Any]] = {}
    for field in ("datasets", "resources", "raw_pages"):
        value = payload.get(field)
        if not isinstance(value, list):
            raise ValueError(f"snapshot {field} must be a list")
        collections[field] = value
    datasets = collections["datasets"]
    resources = collections["resources"]
    if manifest.get("dataset_count") != len(datasets):
        raise ValueError("snapshot manifest dataset count is inconsistent")
    if manifest.get("resource_count") != len(resources):
        raise ValueError("snapshot manifest resource count is inconsistent")

    dataset_map: dict[str, Mapping[str, Any]] = {}
    nested_resources: list[Any] = []
    for dataset in datasets:
        if not isinstance(dataset, Mapping):
            raise ValueError("snapshot dataset must be a JSON object")
        source_id = dataset.get("source_dataset_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("snapshot dataset must contain source_dataset_id")
        if dataset.get("portal_id") != portal_id:
            raise ValueError("snapshot dataset portal association is invalid")
        if source_id in dataset_map:
            raise ValueError("snapshot dataset identifiers must be unique")
        dataset_map[source_id] = dataset
        dataset_resources = dataset.get("resources")
        if not isinstance(dataset_resources, list):
            raise ValueError("snapshot nested resources must be a list")
        nested_resources.extend(dataset_resources)

    for resource in resources:
        if not isinstance(resource, Mapping):
            raise ValueError("snapshot resource must be a JSON object")
        if resource.get("portal_id") != portal_id:
            raise ValueError("snapshot resource portal association is invalid")
        if resource.get("source_dataset_id") not in dataset_map:
            raise ValueError("snapshot resource dataset association is invalid")
    if _comparable_resources(nested_resources) != _comparable_resources(resources):
        raise ValueError("snapshot nested and top-level resources are inconsistent")

    expected_count = manifest.get("expected_count")
    if complete and (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 0
        or len(dataset_map) != expected_count
    ):
        raise ValueError(
            "complete snapshot must match its expected unique usable dataset count"
        )

    core = {field: collections[field] for field in collections}
    expected_hash = hashlib.sha256(
        _canonical_json(_snapshot_identity(core))
    ).hexdigest()
    if manifest.get("content_hash") != expected_hash:
        raise ValueError("snapshot content hash does not match its source state")
    return _ValidatedSnapshot(portal_id, complete, dataset_map)


def _comparable_resources(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    resources = [
        _without_model_observation_clock(item) if isinstance(item, Mapping) else item
        for item in value
    ]
    return _normalise_semantically_unordered(resources, "resources")


_SOURCE_METADATA_FIELDS = (
    "title",
    "description",
    "publisher",
    "licence",
    "licence_identifier",
    "licence_title",
    "licence_url",
    "attribution",
    "themes",
    "catalogue_page_url",
    "metadata_api_url",
    "declared_update_frequency",
    "declared_update_frequency_text",
    "portal_url",
    "api_url",
    "source_created_at",
    "source_updated_at",
    "lifecycle_status",
    "publication_pattern",
    "tags",
)


def _source_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: _normalise_semantically_unordered(value.get(field), field)
        for field in _SOURCE_METADATA_FIELDS
    }


def _source_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = value.get("classification_evidence", [])
    if isinstance(evidence, list):
        evidence = [
            _without_model_observation_clock(item)
            if isinstance(item, Mapping)
            else item
            for item in evidence
        ]
    return {
        "classification_evidence": _normalise_semantically_unordered(
            evidence,
            "classification_evidence",
        ),
        "raw_record": _normalise_semantically_unordered(
            value.get("raw_record", {}),
            "raw_record",
        ),
    }


def diff_snapshots(before: str | Path, after: str | Path) -> SnapshotDiff:
    """Return deterministic, evidence-only changes between two local snapshots."""
    before_path, after_path = Path(before), Path(after)
    before_data = json.loads(before_path.read_text(encoding="utf-8"))
    after_data = json.loads(after_path.read_text(encoding="utf-8"))
    before_snapshot = _validated_snapshot(before_data)
    after_snapshot = _validated_snapshot(after_data)
    if before_snapshot.portal_id != after_snapshot.portal_id:
        raise ValueError("cannot diff snapshots from different portals")
    old, new = before_snapshot.datasets, after_snapshot.datasets
    changes: list[SnapshotChange] = []
    if before_snapshot.complete:
        for source_id in sorted(new.keys() - old.keys()):
            changes.append(
                SnapshotChange("dataset_added", source_id, after=new[source_id])
            )
    if before_snapshot.complete and after_snapshot.complete:
        for source_id in sorted(old.keys() - new.keys()):
            changes.append(
                SnapshotChange("dataset_removed", source_id, before=old[source_id])
            )
    for source_id in sorted(old.keys() & new.keys()):
        previous, current = old[source_id], new[source_id]
        before_metadata = _source_metadata(previous)
        after_metadata = _source_metadata(current)
        if before_metadata != after_metadata:
            changes.append(SnapshotChange("metadata_changed", source_id, before_metadata, after_metadata))
        before_evidence = _source_evidence(previous)
        after_evidence = _source_evidence(current)
        if before_evidence != after_evidence:
            changes.append(
                SnapshotChange(
                    "source_evidence_changed",
                    source_id,
                    before_evidence,
                    after_evidence,
                )
            )
        previous_resources = previous.get("resources", [])
        current_resources = current.get("resources", [])
        if _comparable_resources(previous_resources) != _comparable_resources(current_resources):
            changes.append(
                SnapshotChange(
                    "resources_replaced",
                    source_id,
                    previous_resources,
                    current_resources,
                )
            )
        if previous.get("access_status") != current.get("access_status"):
            changes.append(
                SnapshotChange(
                    "access_changed",
                    source_id,
                    previous.get("access_status"),
                    current.get("access_status"),
                )
            )
    return SnapshotDiff(before_path, after_path, tuple(changes))


def summary_as_json(summary: SyncRunSummary) -> dict[str, Any]:
    """Return a public-safe JSON representation for CLI output."""
    return redact(
        {
            "status": summary.status,
            "exit_code": summary.exit_code,
            "review_queue_path": summary.review_queue_path.as_posix(),
            "portals": {
                portal_id: {
                    **asdict(outcome),
                    "observed_at": outcome.observed_at.isoformat(),
                    "snapshot_path": outcome.snapshot_path.as_posix() if outcome.snapshot_path else None,
                }
                for portal_id, outcome in summary.portals.items()
            },
        }
    )
