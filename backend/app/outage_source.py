"""Exact GET-only collector for the reviewed public SSEN NaFIRS HV source."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, model_validator

from app.config import config
from app.outage_store import (
    commit_ingestion_run,
    record_failed_ingestion_run,
    source_observation_exists,
)
from app.outages import (
    PARSER_VERSION,
    OutageFetchAttemptPublicV1,
    OutageReject,
    SourceResource,
    SourceSnapshot,
    SyncResult,
    source_snapshot_id,
)
from app.ssen_nafirs import (
    SEPD_COLUMNS,
    SEPD_RESOURCE_ID,
    SHEPD_COLUMNS,
    SHEPD_RESOURCE_ID,
    OutageRowError,
    SourceContractError,
    iter_ssen_hv_csv,
)

SOURCE_MAX_RESPONSE_BYTES = 134_217_728
SOURCE_CONNECT_TIMEOUT_SECONDS = 10
SOURCE_READ_TIMEOUT_SECONDS = 60
SOURCE_TOTAL_DEADLINE_SECONDS = 180
_REDIRECT_HOST = (
    "83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_MANIFEST_PATH = _REPOSITORY_ROOT / "data/sources/ssen-nafirs-hv.json"
_EXPECTED_RESOURCE_IDS = tuple(sorted((SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID)))


class SourceLicenceEvidenceArtifactV1(BaseModel):
    schema_version: Literal[1] = 1
    evidence_url: str
    observed_at: datetime
    catalogue_observation_id: str
    portal_id: Literal["ssen"]
    source_dataset_id: str
    package_id: str
    source_resource_ids: tuple[str, str]
    licence_id: str
    licence_title: str
    licence_url: str
    attribution: str
    source_byte_redistribution: Literal["permitted_with_attribution"]
    catalogue_observation_content_sha256: str

    @model_validator(mode="after")
    def validate_public_canonical_evidence(self) -> SourceLicenceEvidenceArtifactV1:
        parsed = urlsplit(self.evidence_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "data.ssen.co.uk"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or parsed.path != "/dataset/nafirs-hv-faults"
        ):
            raise ValueError("licence evidence URL must be the stable public page")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("licence evidence observation must be timezone-aware")
        if self.source_resource_ids != _EXPECTED_RESOURCE_IDS:
            raise ValueError("licence evidence must bind the exact resource set")
        for value in (
            self.catalogue_observation_content_sha256,
        ):
            if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
                raise ValueError("licence evidence hash must be lowercase SHA-256")
        return self


class SourceLicenceEvidenceV1(SourceLicenceEvidenceArtifactV1):
    evidence_artifact_path: Literal[
        "data/sources/evidence/ssen-nafirs-hv-licence.json"
    ]
    evidence_artifact_sha256: str
    evidence_sha256: str


class SsenSourceManifestV1(BaseModel):
    schema_version: Literal[1]
    source_contract_version: Literal["ssen-nafirs-hv-v1"]
    source_id: Literal["ssen-nafirs-hv"]
    source_dataset_id: str
    package_id: str
    resources: list[SourceResource]
    request_method: Literal["GET"]
    redirect_host: str
    redirect_path_prefix: str
    licence_id: str
    licence_title: str
    licence_url: str
    attribution: str
    licence_evidence: SourceLicenceEvidenceV1
    source_byte_redistribution: Literal["permitted_with_attribution"]
    max_response_bytes: Literal[134217728]
    connect_timeout_seconds: Literal[10]
    read_timeout_seconds: Literal[60]
    total_deadline_seconds: Literal[180]
    analytical_role: Literal["historical_hv_outage_evidence"]
    limitations: list[str]
    timezone_name: None
    publisher_cadence: None

    @model_validator(mode="after")
    def validate_exact_source_contract(self) -> SsenSourceManifestV1:
        evidence = self.licence_evidence
        shared = (
            "source_dataset_id",
            "package_id",
            "licence_id",
            "licence_title",
            "licence_url",
            "attribution",
            "source_byte_redistribution",
        )
        if any(getattr(self, name) != getattr(evidence, name) for name in shared):
            raise ValueError("manifest and licence evidence fields differ")
        resource_ids = tuple(sorted(item.source_resource_id for item in self.resources))
        if resource_ids != _EXPECTED_RESOURCE_IDS or resource_ids != evidence.source_resource_ids:
            raise ValueError("manifest resource set differs from reviewed evidence")
        if len(self.resources) != 2:
            raise ValueError("manifest must contain exactly two resources")
        if self.redirect_host != _REDIRECT_HOST:
            raise ValueError("manifest redirect host differs from reviewed contract")
        if self.redirect_path_prefix != "/dx-sse-prod/resources/":
            raise ValueError("manifest redirect path differs from reviewed contract")
        for resource in self.resources:
            if (
                resource.source_dataset_id != self.source_dataset_id
                or resource.package_id != self.package_id
                or resource.format != "CSV"
                or resource.media_type != "text/csv"
                or resource.datastore_active is not True
            ):
                raise ValueError("manifest resource differs from reviewed contract")
            _validate_stable_resource_url(resource)
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _validate_stable_resource_url(resource: SourceResource) -> None:
    try:
        parsed = urlsplit(resource.stable_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("manifest resource URL is invalid") from error
    expected = (
        f"/dataset/{resource.package_id}/resource/"
        f"{resource.source_resource_id}/download/"
    )
    filename = parsed.path.removeprefix(expected)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "data-api.ssen.co.uk"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(expected)
        or not filename
        or "/" in filename
    ):
        raise ValueError("manifest resource URL differs from reviewed contract")


def load_ssen_source_manifest(
    path: Path | None = None,
) -> SsenSourceManifestV1:
    """Load and hash-verify the tracked reviewed source contract."""
    manifest_path = path or _SOURCE_MANIFEST_PATH
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = SsenSourceManifestV1.model_validate(raw)
    evidence_path = _REPOSITORY_ROOT / manifest.licence_evidence.evidence_artifact_path
    artifact_bytes = evidence_path.read_bytes()
    artifact_raw = json.loads(artifact_bytes.decode("utf-8"))
    expected_bytes = _canonical_json_bytes(artifact_raw) + b"\n"
    if artifact_bytes != expected_bytes:
        raise ValueError("licence evidence artifact is not exact canonical JSON")
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_hash != manifest.licence_evidence.evidence_artifact_sha256:
        raise ValueError("licence evidence artifact hash differs")
    artifact = SourceLicenceEvidenceArtifactV1.model_validate(artifact_raw)
    embedded = manifest.licence_evidence.model_dump()
    for extra in (
        "evidence_artifact_path",
        "evidence_artifact_sha256",
        "evidence_sha256",
    ):
        embedded.pop(extra)
    if artifact.model_dump() != embedded:
        raise ValueError("embedded licence evidence differs from artifact")
    evidence_raw = dict(raw["licence_evidence"])
    evidence_sha256 = evidence_raw.pop("evidence_sha256")
    if hashlib.sha256(_canonical_json_bytes(evidence_raw)).hexdigest() != evidence_sha256:
        raise ValueError("embedded licence evidence hash differs")
    return manifest


def _approved_redirect(location: str, resource_id: str) -> bool:
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError:
        return False
    prefix = f"/dx-sse-prod/resources/{resource_id}/"
    filename = parsed.path.removeprefix(prefix)
    return (
        parsed.scheme == "https"
        and parsed.hostname == _REDIRECT_HOST
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.fragment == ""
        and parsed.path.startswith(prefix)
        and bool(filename)
        and "/" not in filename
    )


def _send_stream(
    client: httpx.Client,
    url: str,
    timeout: httpx.Timeout,
) -> httpx.Response | None:
    failed = False
    response: httpx.Response | None = None
    try:
        request = client.build_request("GET", url, timeout=timeout)
        response = client.send(request, stream=True, follow_redirects=False)
    except Exception:
        failed = True
    if failed:
        return None
    return response


def download_ssen_hv_resource(
    client: httpx.Client,
    resource: SourceResource,
) -> bytes:
    """Download one resource through exactly one bounded approved redirect."""
    if getattr(client, "follow_redirects", False):
        raise SourceContractError("SSEN resource client must not follow redirects")
    _validate_stable_resource_url(resource)
    started = time.monotonic()

    def check_deadline() -> None:
        if time.monotonic() - started >= SOURCE_TOTAL_DEADLINE_SECONDS:
            raise SourceContractError("SSEN resource total deadline exceeded")

    timeout = httpx.Timeout(
        connect=SOURCE_CONNECT_TIMEOUT_SECONDS,
        read=SOURCE_READ_TIMEOUT_SECONDS,
        write=SOURCE_READ_TIMEOUT_SECONDS,
        pool=SOURCE_CONNECT_TIMEOUT_SECONDS,
    )
    check_deadline()
    first = _send_stream(client, resource.stable_url, timeout)
    if first is None:
        raise SourceContractError("SSEN resource request failed")
    try:
        check_deadline()
        if first.status_code != 302:
            raise SourceContractError(
                "SSEN resource did not return the required redirect",
                response_status=first.status_code,
                error_code="unexpected_initial_status",
            )
        location = first.headers.get("location", "")
        if not _approved_redirect(location, resource.source_resource_id):
            raise SourceContractError("SSEN resource returned an unapproved redirect")
    finally:
        first.close()

    check_deadline()
    second = _send_stream(client, location, timeout)
    location = ""
    if second is None:
        raise SourceContractError("SSEN redirected resource request failed")
    stream_failed = False
    chunks: list[bytes] = []
    total = 0
    try:
        check_deadline()
        if second.status_code != 200:
            raise SourceContractError(
                "SSEN redirected resource did not return 200",
                response_status=second.status_code,
                error_code="unexpected_final_status",
            )
        media_type = second.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "text/csv":
            raise SourceContractError("SSEN redirected resource is not text/csv")
        declared = second.headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared, 10)
            except ValueError:
                raise SourceContractError("SSEN resource content length is invalid") from None
            if declared_size < 0 or declared_size > SOURCE_MAX_RESPONSE_BYTES:
                raise SourceContractError("SSEN resource exceeds the response size limit")
        try:
            for chunk in second.iter_bytes():
                total += len(chunk)
                if total > SOURCE_MAX_RESPONSE_BYTES:
                    raise SourceContractError("SSEN resource exceeds the response size limit")
                chunks.append(chunk)
                check_deadline()
        except SourceContractError:
            raise
        except Exception:
            stream_failed = True
    finally:
        second.close()
    if stream_failed:
        raise SourceContractError("SSEN resource stream failed")
    return b"".join(chunks)


def _write_blob(
    content: bytes,
    content_sha256: str,
    snapshot_dir: Path,
    run_id: str,
) -> tuple[str, Path | None]:
    relative = Path("blobs") / content_sha256[:2] / f"{content_sha256}.csv"
    path = snapshot_dir / relative
    if path.exists():
        existing = path.read_bytes()
        if len(existing) != len(content) or hashlib.sha256(existing).hexdigest() != content_sha256:
            raise ValueError("existing outage blob failed hash and size verification")
        return relative.as_posix(), None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{run_id.rsplit(':', 1)[-1]}.tmp")
    try:
        temporary.write_bytes(content)
        if temporary.stat().st_size != len(content):
            raise ValueError("outage blob atomic write size mismatch")
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != content_sha256:
            raise ValueError("outage blob atomic write hash mismatch")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return relative.as_posix(), path


def sync_ssen_nafirs_hv(
    *,
    db_path: Path | None = None,
    snapshot_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> SyncResult:
    """Synchronise both reviewed resources into one atomic local evidence set."""
    manifest = load_ssen_source_manifest()
    resolved_db = db_path or config.outage_db_path
    resolved_snapshot_dir = snapshot_dir or config.outage_snapshot_dir
    run_id = f"ssen-nafirs-hv:{uuid.uuid4().hex}"
    snapshots: list[SourceSnapshot] = []
    events = []
    rejects: list[OutageReject] = []
    attempts: list[OutageFetchAttemptPublicV1] = []
    created_files: list[Path] = []
    own_client = client is None
    active_client = client or httpx.Client(follow_redirects=False)
    resources_seen = 0
    try:
        snapshots_created = 0
        for resource in sorted(
            manifest.resources, key=lambda item: item.source_resource_id
        ):
            resources_seen += 1
            attempted_at = datetime.now(timezone.utc)
            try:
                content = download_ssen_hv_resource(active_client, resource)
                digest = hashlib.sha256(content).hexdigest()
                snapshot_id = source_snapshot_id(resource.source_resource_id, digest)
                snapshots_created += int(
                    not source_observation_exists(snapshot_id, db_path=resolved_db)
                )
                relative_path, created_path = _write_blob(
                    content, digest, resolved_snapshot_dir, run_id
                )
                if created_path is not None:
                    created_files.append(created_path)
                parsed = list(
                    iter_ssen_hv_csv(
                        content,
                        licence_area=resource.licence_area,
                        source_dataset_id=resource.source_dataset_id,
                        source_resource_id=resource.source_resource_id,
                        snapshot_id=snapshot_id,
                    )
                )
                resource_events = [item for item in parsed if not isinstance(item, OutageRowError)]
                resource_rejects = [item for item in parsed if isinstance(item, OutageRowError)]
                events.extend(resource_events)
                rejects.extend(
                    OutageReject(
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        row_number=item.row_number or 1,
                        error_code=item.code,
                        error_message=item.message,
                        raw_row=item.raw_record,
                    )
                    for item in resource_rejects
                )
                observed_columns = list(
                    SEPD_COLUMNS if resource.licence_area == "SEPD" else SHEPD_COLUMNS
                )
                snapshot = SourceSnapshot(
                    snapshot_id=snapshot_id,
                    source_dataset_id=resource.source_dataset_id,
                    package_id=resource.package_id,
                    source_resource_id=resource.source_resource_id,
                    licence_area=resource.licence_area,
                    stable_source_url=resource.stable_url,
                    source_modified_at=resource.source_modified_at,
                    fetched_at=attempted_at,
                    content_sha256=digest,
                    byte_size=len(content),
                    row_count=len(parsed),
                    observed_columns=observed_columns,
                    licence_id=manifest.licence_id,
                    licence_title=manifest.licence_title,
                    licence_url=manifest.licence_url,
                    attribution=manifest.attribution,
                    parser_version=PARSER_VERSION,
                    local_snapshot_path=relative_path,
                )
                snapshots.append(snapshot)
                attempts.append(
                    OutageFetchAttemptPublicV1(
                        attempt_id=f"attempt:{uuid.uuid4().hex}",
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        attempted_at=attempted_at,
                        status="completed",
                        response_status=200,
                        source_modified_at=resource.source_modified_at,
                        source_snapshot_id=snapshot_id,
                        content_sha256=digest,
                        byte_size=len(content),
                        error_code=None,
                    )
                )
            except Exception as error:
                attempts.append(
                    OutageFetchAttemptPublicV1(
                        attempt_id=f"attempt:{uuid.uuid4().hex}",
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        attempted_at=attempted_at,
                        status="failed",
                        response_status=getattr(error, "response_status", None),
                        source_modified_at=resource.source_modified_at,
                        source_snapshot_id=None,
                        content_sha256=None,
                        byte_size=None,
                        error_code=getattr(
                            error,
                            "code",
                            "source_fetch_failed",
                        ),
                    )
                )
                raise
        return commit_ingestion_run(
            run_id=run_id,
            resources_seen=resources_seen,
            snapshots=snapshots,
            events=events,
            rejects=rejects,
            snapshots_created=snapshots_created,
            snapshots_reused=len(snapshots) - snapshots_created,
            warnings=[],
            fetch_attempts=attempts,
            db_path=resolved_db,
        )
    except Exception as error:
        for path in reversed(created_files):
            if path.exists():
                path.unlink()
        return record_failed_ingestion_run(
            run_id=run_id,
            resources_seen=resources_seen,
            error=error,
            fetch_attempts=attempts,
            db_path=resolved_db,
        )
    finally:
        if own_client:
            active_client.close()
