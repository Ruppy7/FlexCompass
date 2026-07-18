"""Security regression tests for the public catalogue surface.

Default tests make zero network calls. Live smoke cases are skipped unless
FLEXCOMPASS_LIVE_PORTAL_TESTS=1 exactly.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from app.catalogue_adapters import CatalogueFetchResult, fetch_catalogue
from app.catalogue_cli import build_parser
from app.catalogue_models import (
    CATALOGUE_PORTALS,
    CatalogueDataset,
    ClassificationEvidence,
    DatasetResource,
    EvidenceConfidence,
    PortalPlatform,
)
from app.catalogue_sync import redact, safe_error, summary_as_json, sync_catalogues

NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
SYNTHETIC_SECRET = "sk-fake-7a9b3c4d5e6f-SECRET"
SYNTHETIC_TOKEN = "Bearer eyJhbGciOiJub25lIn0.secret-token-value"
SYNTHETIC_API_KEY = "apikey=AKIAIOSFODNN7SECRET"
EXACT_CREDENTIAL_MARKER = "EXACT-CREDENTIAL-MARKER-4f91c7"
PRIVATE_HOST_URL = "https://192.168.1.100/internal/admin"
CREDENTIAL_URL = "https://user:password@internal.example.com/data"
UNSAFE_MARKERS = [
    SYNTHETIC_SECRET, SYNTHETIC_TOKEN, "secret-token-value",
    "AKIAIOSFODNN7SECRET", EXACT_CREDENTIAL_MARKER,
    PRIVATE_HOST_URL, "192.168.1.100", "user:password",
]


def _assert_no_secrets(text: str, *, context: str = "") -> None:
    lowered = text.casefold()
    for marker in UNSAFE_MARKERS:
        assert marker.casefold() not in lowered, (
            f"{context}: forbidden marker {marker!r} found")


def _serialise(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _ckan_page(records, count=None):
    r = {"results": records}
    if count is not None:
        r["count"] = count
    return {"success": True, "result": r}


def _ods_page(records, count=None):
    p = {"results": records}
    if count is not None:
        p["total_count"] = count
    return p


def _ckan_record_with_secret():
    return {
        "id": "secret-ckan-uuid", "name": "secret-dataset",
        "title": "Public network dataset",
        "notes": "Public catalogue metadata.",
        "license_title": "Example", "organization": {"name": "example-org"},
        "resources": [{"id": "secret-resource", "name": "CSV",
            "url": f"https://example.invalid/data.csv?{SYNTHETIC_API_KEY}",
            "format": "CSV", "mimetype": "text/csv", "size": 42,
            "created": "2026-01-01T10:00:00+00:00",
            "last_modified": "2026-01-02T11:00:00+00:00"}],
        "tags": [{"name": "synthetic"}],
        "authorization": SYNTHETIC_TOKEN, "private_endpoint": PRIVATE_HOST_URL,
    }


def _ods_record_with_secret():
    return {
        "dataset_id": "secret-ods-dataset", "dataset_uid": "synthetic-ods-secret",
        "attachments": [{"id": "secret-attachment", "title": "Public CSV",
            "mimetype": "text/csv",
            "url": f"https://example.invalid/secret.csv?{SYNTHETIC_API_KEY}"}],
        "alternative_exports": [],
        "metas": {"default": {
            "title": "Public ODS dataset",
            "description": "Public catalogue metadata.", "license": "Example",
            "publisher": "Test Publisher", "modified": "2026-01-02T11:00:00+00:00",
            "keyword": ["synthetic"]}},
        "token": SYNTHETIC_TOKEN, "internal_url": CREDENTIAL_URL,
    }


def _ckan_record_with_inline_token():
    """CKAN record with an inline token=<secret> pattern in a text field."""
    return {
        "id": "inline-token-uuid", "name": "inline-token-dataset",
        "title": "Public network dataset",
        "notes": f"Access via token={SYNTHETIC_SECRET} for public catalogue.",
        "license_title": "Example", "organization": {"name": "example-org"},
        "resources": [{"id": "inline-resource", "name": "CSV",
            "url": "https://example.invalid/data.csv",
            "format": "CSV", "mimetype": "text/csv", "size": 42,
            "created": "2026-01-01T10:00:00+00:00",
            "last_modified": "2026-01-02T11:00:00+00:00"}],
        "tags": [{"name": "synthetic"}],
    }



class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _RecClient:
    def __init__(self, payloads):
        self._it = iter(payloads)
        self.requests = []

    def get(self, url, *, params=None):
        self.requests.append(("GET", url))
        return _FakeResp(next(self._it))

    def post(self, u, **k):
        self.requests.append(("POST", u))
        raise AssertionError("no POST")

    def put(self, u, **k):
        self.requests.append(("PUT", u))
        raise AssertionError("no PUT")

    def patch(self, u, **k):
        self.requests.append(("PATCH", u))
        raise AssertionError("no PATCH")

    def delete(self, u, **k):
        self.requests.append(("DELETE", u))
        raise AssertionError("no DELETE")

    def head(self, u, **k):
        self.requests.append(("HEAD", u))
        raise AssertionError("no HEAD")

    def close(self):
        pass


def _build_ds_secrets(portal_id, raw_record):
    candidates = raw_record.get("resources") or raw_record.get("attachments") or []
    resource_raw = dict(candidates[0]) if candidates and isinstance(candidates[0], dict) else {}
    resource_url = resource_raw.get("url") or f"https://example.invalid/data.csv?{SYNTHETIC_API_KEY}"
    resource_raw.setdefault("url", resource_url)
    resource_raw.setdefault("token", SYNTHETIC_TOKEN)
    res = DatasetResource(
        id=f"{portal_id}:secret-resource", portal_id=portal_id,
        source_dataset_id="secret-dataset", name="CSV",
        url=resource_url,
        format="CSV", observed_at=NOW,
        raw_record=resource_raw)
    ev = ClassificationEvidence(
        id=f"{portal_id}:secret-dataset:access", portal_id=portal_id,
        source_dataset_id="secret-dataset", classification="access_status",
        evidence="Public anonymous metadata access verified.",
        confidence=EvidenceConfidence.high, observed_at=NOW,
        source_url="https://example.invalid/public-catalogue")
    ds = CatalogueDataset(
        id=f"{portal_id}:secret-dataset", portal_id=portal_id,
        source_dataset_id="secret-dataset",
        title="Public network dataset",
        observed_at=NOW, resources=[res],
        classification_evidence=[ev], raw_record=raw_record)
    return ds, [res]


class _SyncClient:
    def __init__(self, pid): self.pid = pid
    def close(self): pass


def _run_sync(tmp_path, portal_id, raw_record):
    ds, resources = _build_ds_secrets(portal_id, raw_record)
    result = CatalogueFetchResult(
        portal_id=portal_id, observed_at=NOW, datasets=[ds],
        resources=resources, expected_count=1, complete=True,
        warnings=[], raw_pages=[{"raw": raw_record}])
    def fake_fetch(portal, client, observed_at): return result
    db = tmp_path / "catalogue.sqlite3"
    out = tmp_path / "snapshots"
    q = tmp_path / "cache" / "review-queue.json"
    pol = Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json"
    summary = sync_catalogues(
        [portal_id], lambda p: _SyncClient(portal_id),
        db, out, NOW, fetcher=fake_fetch,
        review_queue_path=q, policy_path=pol)
    return summary, db, q


class TestSnapshotRedaction:
    def test_ckan_snapshot_no_secrets(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        _assert_no_secrets(s.portals["nged"].snapshot_path.read_text("utf-8"), context="ckan snap")

    def test_ods_snapshot_no_secrets(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "spen", _ods_record_with_secret())
        _assert_no_secrets(s.portals["spen"].snapshot_path.read_text("utf-8"), context="ods snap")


class TestReviewQueueRedaction:
    def test_queue_no_secrets(self, tmp_path):
        _, _, q = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        _assert_no_secrets(q.read_text("utf-8"), context="queue")


class TestSafeErrorRedaction:
    def test_hides_secret(self):
        safe = safe_error(RuntimeError(f"fail {SYNTHETIC_SECRET}"))
        _assert_no_secrets(safe, context="safe_error")
        assert "RuntimeError" in safe and "operation failed" in safe


class TestRedactFunction:
    @pytest.mark.parametrize(
        "value",
        [
            "Basic metadata about network capacity",
            "Bearer information about public datasets",
        ],
    )
    def test_benign_auth_scheme_prose_is_preserved(self, value):
        assert redact(value) == value

    def test_authorization_key(self):
        assert redact({"authorization": SYNTHETIC_TOKEN})["authorization"] == "[REDACTED]"

    def test_api_key(self):
        assert redact({"api_key": SYNTHETIC_SECRET})["api_key"] == "[REDACTED]"

    def test_token_key(self):
        assert redact({"token": SYNTHETIC_TOKEN})["token"] == "[REDACTED]"

    def test_secret_key(self):
        assert redact({"secret": SYNTHETIC_SECRET})["secret"] == "[REDACTED]"

    def test_credential_key(self):
        assert redact({"credential": SYNTHETIC_SECRET})["credential"] == "[REDACTED]"

    def test_credential_substring_key_is_not_redacted(self):
        # S4: sensitive key matching must not match substrings like 'credential_data'
        assert redact({"credential_data": "benign value"})["credential_data"] == "benign value"

    def test_password_key(self):
        assert redact({"password": SYNTHETIC_SECRET})["password"] == "[REDACTED]"

    def test_cookie_key(self):
        assert redact({"cookie": "session=abc"})["cookie"] == "[REDACTED]"

    def test_inline_apikey(self):
        r = redact(f"use {SYNTHETIC_API_KEY} now")
        assert "AKIAIOSFODNN7SECRET" not in r
        assert "[REDACTED]" in r

    def test_inline_authorization(self):
        r = redact(f"authorization: {SYNTHETIC_TOKEN}")
        assert SYNTHETIC_TOKEN not in r
        assert "[REDACTED]" in r

    @pytest.mark.parametrize(
        "value",
        [
            f"Authorization: Bearer {EXACT_CREDENTIAL_MARKER}",
            f"Authorization=Basic {EXACT_CREDENTIAL_MARKER}",
            f"Cookie: session={EXACT_CREDENTIAL_MARKER}",
            f"access-token={EXACT_CREDENTIAL_MARKER}",
            f"client-secret={EXACT_CREDENTIAL_MARKER}",
            f"Bearer {EXACT_CREDENTIAL_MARKER}",
            f"Basic {EXACT_CREDENTIAL_MARKER}",
        ],
    )
    def test_complete_common_credential_value_is_removed(self, value):
        redacted = redact(value)

        assert EXACT_CREDENTIAL_MARKER not in redacted
        assert "[REDACTED]" in redacted

    @pytest.mark.parametrize("key", ["access_token", "client_secret"])
    def test_inline_actual_credential_names(self, key):
        r = redact(f"use {key}={SYNTHETIC_SECRET} now")
        assert SYNTHETIC_SECRET not in r
        assert f"{key}=[REDACTED]" in r

    def test_private_host_url(self):
        _assert_no_secrets(redact(f"at {PRIVATE_HOST_URL}"), context="private host")

    def test_credential_url(self):
        _assert_no_secrets(redact(f"via {CREDENTIAL_URL}"), context="cred url")

    def test_nested(self):
        r = redact({"a": {"authorization": SYNTHETIC_TOKEN, "b": [{"token": SYNTHETIC_SECRET, "ok": "v"}]}})
        assert r["a"]["authorization"] == "[REDACTED]"
        assert r["a"]["b"][0]["token"] == "[REDACTED]"
        assert r["a"]["b"][0]["ok"] == "v"

    def test_short_basic_base64_credential_is_redacted(self):
        """Basic YTpi decodes to 'a:b' — a valid short credential that must not leak."""
        result = redact("Basic YTpi")
        assert "YTpi" not in result

    def test_short_bearer_token_with_digits_is_redacted(self):
        """A short alphabetic+digit Bearer value is credential-shaped, not prose."""
        result = redact("Bearer XyZa1234")
        assert "XyZa1234" not in result

    def test_standalone_purely_alphabetic_bearer_is_redacted(self):
        """A standalone purely alphabetic Bearer token is credential-shaped, not prose."""
        result = redact("Bearer abcdefghijklmno")
        assert "abcdefghijklmno" not in result

    def test_semicolon_delimited_sensitive_query_is_redacted(self):
        """Semicolon-delimited sensitive query pairs must be removed."""
        url = "https://example.invalid/data.csv?format=csv;credential=MARKER"
        result = redact(url)
        assert "MARKER" not in result
        assert "format=csv" in result

    def test_semicolon_delimited_auth_query_is_redacted(self):
        """Semicolon-delimited auth= query must be removed."""
        url = "https://example.invalid/data.csv?format=csv;auth=SECRET_VALUE"
        result = redact(url)
        assert "SECRET_VALUE" not in result
        assert "format=csv" in result

    def test_sync_redacts_inline_credential_and_auth_query_aliases(self, tmp_path):
        record = _ckan_record_with_secret()
        record["notes"] = f"credential={EXACT_CREDENTIAL_MARKER}"
        record["resources"][0]["url"] = (
            "https://example.invalid/data.csv?format=csv&"
            f"auth={EXACT_CREDENTIAL_MARKER}"
        )

        summary, _, _ = _run_sync(tmp_path, "nged", record)
        snapshot = summary.portals["nged"].snapshot_path.read_text("utf-8")

        assert EXACT_CREDENTIAL_MARKER not in snapshot
        assert "format=csv" in snapshot

    def test_sync_redacts_semicolon_credential_query(self, tmp_path):
        """End-to-end: semicolon-delimited credential query is removed from snapshot."""
        record = _ckan_record_with_secret()
        record["resources"][0]["url"] = (
            "https://example.invalid/data.csv?format=csv;credential=MARKER"
        )

        summary, _, _ = _run_sync(tmp_path, "nged", record)
        snapshot = summary.portals["nged"].snapshot_path.read_text("utf-8")

        assert "MARKER" not in snapshot
        assert "format=csv" in snapshot

    def test_sync_redacts_basic_and_bearer_credentials_from_raw_record(self, tmp_path):
        """End-to-end: Basic YTpi and Bearer abcdefghijklmno are absent from
        snapshot and SQLite raw-record fields, while benign prose survives."""
        record = _ckan_record_with_secret()
        record["notes"] = (
            "Auth example: Basic YTpi and Bearer abcdefghijklmno. "
            "Benign: Basic metadata about network capacity "
            "and Bearer information about public datasets."
        )

        summary, db, _ = _run_sync(tmp_path, "nged", record)
        snapshot_text = summary.portals["nged"].snapshot_path.read_text("utf-8")

        # Credential values must be absent
        assert "YTpi" not in snapshot_text
        assert "abcdefghijklmno" not in snapshot_text
        # Benign prose must survive
        assert "Basic metadata about network capacity" in snapshot_text
        assert "Bearer information about public datasets" in snapshot_text

        # SQLite raw-record fields must also be clean
        import sqlite3
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT raw_record_json FROM catalogue_datasets").fetchall():
                row_text = _serialise(dict(row))
                assert "YTpi" not in row_text, "Basic YTpi leaked into DB raw_record"
                assert "abcdefghijklmno" not in row_text, "Bearer token leaked into DB raw_record"
                assert "Basic metadata about network capacity" in row_text
                assert "Bearer information about public datasets" in row_text
        finally:
            conn.close()


class TestSummaryJSONRedaction:
    def test_summary_no_secrets(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        _assert_no_secrets(_serialise(summary_as_json(s)), context="summary")


class TestInlineTokenRedaction:
    """Regression: inline token=<synthetic-secret> is redacted from all pipeline outputs."""

    def test_inline_token_redacted_from_snapshot(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "nged", _ckan_record_with_inline_token())
        snapshot_text = s.portals["nged"].snapshot_path.read_text("utf-8")
        assert SYNTHETIC_SECRET not in snapshot_text, (
            "inline token=<secret> leaked into snapshot")
        assert "token=[REDACTED]" in snapshot_text

    def test_inline_token_redacted_from_db(self, tmp_path):
        import sqlite3
        _, db, _ = _run_sync(tmp_path, "nged", _ckan_record_with_inline_token())
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT * FROM catalogue_observations").fetchall():
                row_text = _serialise(dict(row))
                assert SYNTHETIC_SECRET not in row_text, (
                    "inline token=<secret> leaked into DB observations")
            for row in conn.execute("SELECT * FROM catalogue_datasets").fetchall():
                row_text = _serialise(dict(row))
                assert SYNTHETIC_SECRET not in row_text, (
                    "inline token=<secret> leaked into DB datasets")
        finally:
            conn.close()

    def test_inline_token_redacted_from_summary(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "nged", _ckan_record_with_inline_token())
        summary_text = _serialise(summary_as_json(s))
        assert SYNTHETIC_SECRET not in summary_text, (
            "inline token=<secret> leaked into summary JSON")


class TestGetOnly:
    @pytest.mark.parametrize("pid,pf", [
        ("nged", lambda r: _ckan_page(r, count=len(r))),
        ("spen", lambda r: _ods_page(r, count=len(r))),
    ])
    def test_only_get(self, pid, pf):
        portal = CATALOGUE_PORTALS[pid]
        rec = _ckan_record_with_secret() if portal.platform is PortalPlatform.ckan else _ods_record_with_secret()
        c = _RecClient([pf([rec])])
        fetch_catalogue(portal, c, NOW)
        assert all(m == "GET" for m, _ in c.requests)
        assert len(c.requests) >= 1

    def test_ckan_search_url(self):
        c = _RecClient([_ckan_page([{"name": "d", "resources": [], "tags": []}], count=1)])
        fetch_catalogue(CATALOGUE_PORTALS["nged"], c, NOW)
        assert all("package_search" in u for _, u in c.requests)

    def test_ods_search_url(self):
        c = _RecClient([_ods_page([_ods_record_with_secret()], count=1)])
        fetch_catalogue(CATALOGUE_PORTALS["spen"], c, NOW)
        assert all("/datasets" in u for _, u in c.requests)


class TestCLIReadOnly:
    def test_subcommands(self):
        assert set(build_parser()._subparsers._group_actions[0].choices) == {"sync", "diff", "review-queue"}

class TestDBRedaction:
    def test_observations_no_secrets(self, tmp_path):
        import sqlite3
        _, db, _ = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT * FROM catalogue_observations").fetchall():
                _assert_no_secrets(_serialise(dict(row)), context="obs row")
        finally:
            conn.close()

    def test_datasets_no_secrets(self, tmp_path):
        import sqlite3
        _, db, _ = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT * FROM catalogue_datasets").fetchall():
                _assert_no_secrets(_serialise(dict(row)), context="ds row")
        finally:
            conn.close()


class TestS4ProvenanceSafeRedaction:
    """S4: Provenance-safe redaction tests."""

    def test_secretariat_key_is_not_redacted(self):
        """S4: 'secretariat' is not a credential name; should not be redacted."""
        result = redact({"secretariat": "public body name"})
        assert result["secretariat"] == "public body name"

    def test_tokenized_fields_key_is_not_redacted(self):
        """S4: 'tokenized_fields' is not a credential name; should not be redacted."""
        result = redact({"tokenized_fields": ["field1", "field2"]})
        assert result["tokenized_fields"] == ["field1", "field2"]

    def test_benign_url_query_params_preserved(self):
        """S4: Benign query parameters in public download URLs are preserved."""
        url = "https://example.invalid/data.csv?format=csv&download=true"
        result = redact({"url": url})
        assert "format=csv" in result["url"]
        assert "download=true" in result["url"]

    def test_sensitive_url_query_params_removed(self):
        """S4: Sensitive query parameters are removed from URLs."""
        url = f"https://example.invalid/data.csv?{SYNTHETIC_API_KEY}&format=csv"
        result = redact({"url": url})
        assert "AKIAIOSFODNN7SECRET" not in _serialise(result)
        assert "format=csv" in result["url"]

    def test_signed_url_credentials_are_removed_but_public_parts_survive(self):
        url = (
            "https://example.invalid/data.csv?format=csv&"
            f"X-Amz-Credential={EXACT_CREDENTIAL_MARKER}&"
            f"X-Amz-Signature={EXACT_CREDENTIAL_MARKER}&"
            f"X-Amz-Security-Token={EXACT_CREDENTIAL_MARKER}#downloads"
        )

        result = redact({"url": url})["url"]

        assert EXACT_CREDENTIAL_MARKER not in result
        assert "format=csv" in result
        assert result.endswith("#downloads")

    def test_sensitive_fragment_pair_is_removed_without_losing_benign_fragment_state(self):
        url = (
            "https://example.invalid/public#"
            f"access_token={EXACT_CREDENTIAL_MARKER}&state=public"
        )

        result = redact({"url": url})["url"]

        assert EXACT_CREDENTIAL_MARKER not in result
        assert result.endswith("#state=public")

    @pytest.mark.parametrize("key", ["access_token", "client_secret"])
    def test_actual_credential_mapping_names_are_redacted(self, key):
        assert redact({key: SYNTHETIC_SECRET})[key] == "[REDACTED]"

    def test_snapshot_preserves_benign_raw_record(self, tmp_path):
        """S4: Snapshot preserves benign raw_record fields."""
        record = _ckan_record_with_secret()
        record["secretariat"] = "public body"
        record["tokenized_fields"] = ["field1"]
        summary, db, q = _run_sync(tmp_path, "nged", record)
        snapshot = summary.portals["nged"].snapshot_path
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        dataset = data["datasets"][0]
        raw = dataset["raw_record"]
        assert raw.get("secretariat") == "public body"
        assert raw.get("tokenized_fields") == ["field1"]

    def test_pipeline_preserves_benign_query_and_redacts_sensitive_query(self, tmp_path):
        """S4: Snapshot and SQLite retain usable public URL provenance only."""
        from urllib.parse import parse_qs, urlsplit

        record = _ckan_record_with_secret()
        public_url = (
            "https://example.invalid/data.csv?delimiter=%3B&download=true&"
            f"{SYNTHETIC_API_KEY}"
        )
        record["resources"][0]["url"] = public_url
        record["secretariat"] = "public body"
        record["tokenized_fields"] = ["field1"]

        summary, db, _ = _run_sync(tmp_path, "nged", record)
        snapshot = json.loads(
            summary.portals["nged"].snapshot_path.read_text(encoding="utf-8")
        )
        snapshot_url = snapshot["resources"][0]["url"]
        snapshot_query = parse_qs(urlsplit(snapshot_url).query)
        assert snapshot_query == {"delimiter": [";"], "download": ["true"]}
        assert snapshot["datasets"][0]["raw_record"]["secretariat"] == "public body"
        assert snapshot["datasets"][0]["raw_record"]["tokenized_fields"] == ["field1"]

        import sqlite3

        with sqlite3.connect(db) as conn:
            stored_url, raw_json = conn.execute(
                "SELECT url, raw_record_json FROM catalogue_resources"
            ).fetchone()
        assert parse_qs(urlsplit(stored_url).query) == {
            "delimiter": [";"],
            "download": ["true"],
        }
        assert parse_qs(urlsplit(json.loads(raw_json)["url"]).query) == {
            "delimiter": [";"],
            "download": ["true"],
        }
        _assert_no_secrets(_serialise(snapshot["manifest"]), context="manifest")
        _assert_no_secrets(
            _serialise(summary_as_json(summary)), context="summary"
        )


def test_exact_credential_marker_is_absent_from_every_sync_surface(tmp_path):
    raw_record = _ckan_record_with_secret()
    raw_record["notes"] = (
        f"Authorization: Bearer {EXACT_CREDENTIAL_MARKER}"
    )
    raw_record["resources"][0]["url"] = (
        "https://example.invalid/data.csv?download=true&"
        f"X-Amz-Signature={EXACT_CREDENTIAL_MARKER}#downloads"
    )
    dataset, resources = _build_ds_secrets("nged", raw_record)
    dataset.title = f"client-secret={EXACT_CREDENTIAL_MARKER}"
    resources[0].description = f"Cookie: session={EXACT_CREDENTIAL_MARKER}"
    dataset.resources = resources
    dataset.classification_evidence = [
        ClassificationEvidence(
            id="nged:secret-dataset:lifecycle",
            portal_id="nged",
            source_dataset_id="secret-dataset",
            classification="lifecycle_status",
            evidence=f"access-token={EXACT_CREDENTIAL_MARKER}",
            confidence=EvidenceConfidence.high,
            source_value="active",
            observed_at=NOW,
            raw_record={"cookie": f"session={EXACT_CREDENTIAL_MARKER}"},
        )
    ]
    result = CatalogueFetchResult(
        portal_id="nged",
        observed_at=NOW,
        datasets=[dataset],
        resources=resources,
        expected_count=1,
        complete=True,
        warnings=[f"Authorization: Basic {EXACT_CREDENTIAL_MARKER}"],
        raw_pages=[{"raw": raw_record}],
    )

    def fake_fetch(portal, client, observed_at):
        return result

    db = tmp_path / "catalogue.sqlite3"
    snapshot_dir = tmp_path / "snapshots"
    queue = tmp_path / "cache" / "review-queue.json"
    policy = Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json"
    summary = sync_catalogues(
        ["nged"],
        lambda portal: _SyncClient("nged"),
        db,
        snapshot_dir,
        NOW,
        fetcher=fake_fetch,
        review_queue_path=queue,
        policy_path=policy,
    )

    surfaces = {
        "snapshot": summary.portals["nged"].snapshot_path.read_text("utf-8"),
        "manifest": _serialise(
            json.loads(
                summary.portals["nged"].snapshot_path.read_text("utf-8")
            )["manifest"]
        ),
        "summary": _serialise(summary_as_json(summary)),
        "queue": queue.read_text("utf-8"),
    }
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for table in (
            "catalogue_observations",
            "catalogue_datasets",
            "catalogue_resources",
            "classification_evidence",
            "catalogue_assessments",
        ):
            surfaces[f"database:{table}"] = _serialise(
                [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            )

    for name, text in surfaces.items():
        assert EXACT_CREDENTIAL_MARKER not in text, (
            f"exact credential marker leaked through {name}"
        )


class TestQ1CLISecurityPath:
    """Q1: CLI security path - secret-bearing result flows through CLI sync seam."""

    def test_cli_sync_secret_result_is_redacted(self, tmp_path, capsys, monkeypatch):
        """Q1: Secret-bearing fake result flows through CLI, exit 0, output redacted."""
        db = tmp_path / "catalogue.sqlite3"
        out = tmp_path / "snapshots"
        q = tmp_path / "queue.json"
        pol = Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json"

        record = _ckan_record_with_secret()
        result = CatalogueFetchResult(
            portal_id="nged",
            observed_at=NOW,
            datasets=[
                CatalogueDataset(
                    id="nged:secret-dataset",
                    portal_id="nged",
                    source_dataset_id="secret-dataset",
                    title="Public network dataset",
                    observed_at=NOW,
                    raw_record=record,
                )
            ],
            resources=[],
            expected_count=1,
            complete=True,
            warnings=[],
            raw_pages=[record],
        )

        import app.catalogue_cli as catalogue_cli

        consumed = False
        real_sync = sync_catalogues

        def fake_cli_sync(portal_ids, client_factory, db_path, output_dir, now, **kwargs):
            nonlocal consumed

            def fake_fetch(portal, client, observed_at):
                nonlocal consumed
                consumed = True
                return result

            return real_sync(
                portal_ids,
                client_factory,
                db_path,
                output_dir,
                now,
                fetcher=fake_fetch,
                **kwargs,
            )

        monkeypatch.setattr(catalogue_cli, "sync_catalogues", fake_cli_sync)
        monkeypatch.setattr(
            catalogue_cli, "_client_factory", lambda portal: _SyncClient("nged")
        )
        exit_code = catalogue_cli.main(
            [
                "sync",
                "--portal",
                "nged",
                "--db-path",
                str(db),
                "--output-dir",
                str(out),
                "--review-queue-path",
                str(q),
                "--policy-path",
                str(pol),
            ]
        )
        text = capsys.readouterr().out
        output = json.loads(text)
        assert consumed is True
        assert exit_code == 0
        assert output["status"] == "complete"
        assert output["portals"]["nged"]["status"] == "complete"
        _assert_no_secrets(text, context="Q1 CLI summary")


class TestQ2HelpTest:
    """Q2: CLI help contains meaningful anonymous/read-only wording."""

    def test_sync_help_mentions_read_only(self):
        from app.catalogue_cli import build_parser
        parser = build_parser()
        sync_parser = parser._subparsers._group_actions[0].choices["sync"]
        help_text = sync_parser.format_help().lower()
        assert "read-only" in help_text or "anonymous" in help_text or "get" in help_text


def _live_enabled():
    return os.environ.get("FLEXCOMPASS_LIVE_PORTAL_TESTS") == "1"


@pytest.mark.skipif(not _live_enabled(), reason="FLEXCOMPASS_LIVE_PORTAL_TESTS=1 to enable")
@pytest.mark.parametrize("portal_id", sorted(CATALOGUE_PORTALS))
def test_live_portal(portal_id):
    import httpx
    portal = CATALOGUE_PORTALS[portal_id]
    client = httpx.Client(timeout=portal.timeout_seconds, follow_redirects=True)
    try:
        result = fetch_catalogue(portal, client, datetime.now(timezone.utc))
    finally:
        client.close()
    assert result.portal_id == portal_id
    assert result.complete is True, (
        f"{portal_id} catalogue was partial; warnings={list(result.warnings)!r}"
    )
    assert result.expected_count is not None, (
        f"{portal_id} complete result omitted expected_count; "
        f"warnings={list(result.warnings)!r}"
    )
    usable_ids = [dataset.source_dataset_id for dataset in result.datasets]
    assert len(usable_ids) == len(set(usable_ids)), (
        f"{portal_id} returned duplicate usable dataset IDs; "
        f"warnings={list(result.warnings)!r}"
    )
    assert len(usable_ids) == result.expected_count, (
        f"{portal_id} unique usable count {len(usable_ids)} did not match "
        f"expected_count {result.expected_count}; warnings={list(result.warnings)!r}"
    )
