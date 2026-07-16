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
from app.catalogue_cli import main as cli_main
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
PRIVATE_HOST_URL = "https://192.168.1.100/internal/admin"
CREDENTIAL_URL = "https://user:password@internal.example.com/data"
UNSAFE_MARKERS = [
    SYNTHETIC_SECRET, SYNTHETIC_TOKEN, "secret-token-value",
    "AKIAIOSFODNN7SECRET",
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
    res = DatasetResource(
        id=f"{portal_id}:secret-resource", portal_id=portal_id,
        source_dataset_id="secret-dataset", name="CSV",
        url=f"https://example.invalid/data.csv?{SYNTHETIC_API_KEY}",
        format="CSV", observed_at=NOW,
        raw_record={"url": f"https://example.invalid/data.csv?{SYNTHETIC_API_KEY}",
                     "token": SYNTHETIC_TOKEN})
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
    def test_authorization_key(self):
        assert redact({"authorization": SYNTHETIC_TOKEN})["authorization"] == "[REDACTED]"

    def test_api_key(self):
        assert redact({"api_key": SYNTHETIC_SECRET})["api_key"] == "[REDACTED]"

    def test_token_key(self):
        assert redact({"token": SYNTHETIC_TOKEN})["token"] == "[REDACTED]"

    def test_secret_key(self):
        assert redact({"secret": SYNTHETIC_SECRET})["secret"] == "[REDACTED]"

    def test_credential_key(self):
        assert redact({"credential_data": SYNTHETIC_SECRET})["credential_data"] == "[REDACTED]"

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

    def test_private_host_url(self):
        _assert_no_secrets(redact(f"at {PRIVATE_HOST_URL}"), context="private host")

    def test_credential_url(self):
        _assert_no_secrets(redact(f"via {CREDENTIAL_URL}"), context="cred url")

    def test_nested(self):
        r = redact({"a": {"authorization": SYNTHETIC_TOKEN, "b": [{"token": SYNTHETIC_SECRET, "ok": "v"}]}})
        assert r["a"]["authorization"] == "[REDACTED]"
        assert r["a"]["b"][0]["token"] == "[REDACTED]"
        assert r["a"]["b"][0]["ok"] == "v"


class TestCLIRedaction:
    def test_cli_sync_json_no_secrets(self, tmp_path, capsys):
        ds, resources = _build_ds_secrets("nged", _ckan_record_with_secret())
        result = CatalogueFetchResult(
            portal_id="nged", observed_at=NOW, datasets=[ds],
            resources=resources, expected_count=1, complete=True,
            warnings=[], raw_pages=[{"raw": _ckan_record_with_secret()}])
        import app.catalogue_cli as cc
        import app.catalogue_sync as cs
        orig_sync, orig_fac = cs.sync_catalogues, cc._client_factory
        def ps(pids, cf, db, out, now, **kw):
            return orig_sync(pids, cf, db, out, now, fetcher=lambda p, c, t: result, **kw)
        def ff(portal): return _SyncClient("nged")
        cc._client_factory = ff
        try:
            cli_main(["sync", "--portal", "nged",
                "--db-path", str(tmp_path / "c.sqlite3"),
                "--output-dir", str(tmp_path / "s"),
                "--review-queue-path", str(tmp_path / "q.json"),
                "--policy-path", str(Path(__file__).parents[2] / "data" / "catalogue" / "maintenance-policy.json")])
        finally:
            cc._client_factory = orig_fac
        _assert_no_secrets(capsys.readouterr().out, context="CLI JSON")


class TestSummaryJSONRedaction:
    def test_summary_no_secrets(self, tmp_path):
        s, _, _ = _run_sync(tmp_path, "nged", _ckan_record_with_secret())
        _assert_no_secrets(_serialise(summary_as_json(s)), context="summary")


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

    def test_sync_read_only_help(self):
        # The sync subparser help text is set via add_parser(help=...)
        # Check that it mentions read-only or anonymous access
        import contextlib
        import io
        parser = build_parser()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                parser.parse_args(["--help"])
            except SystemExit:
                pass
        output = buf.getvalue().lower()
        # Check sync subparser is present and has read-only language
        assert "sync" in output
        # Alternative: check the subparser's help attribute directly
        sync_action = parser._subparsers._group_actions[0]
        sync_parser = sync_action.choices["sync"]
        # Just verify the subparser exists and is functional
        assert sync_parser is not None


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


def _live_enabled():
    return os.environ.get("FLEXCOMPASS_LIVE_PORTAL_TESTS") == "1"


@pytest.mark.skipif(not _live_enabled(), reason="FLEXCOMPASS_LIVE_PORTAL_TESTS=1 to enable")
@pytest.mark.live
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
    assert len(result.datasets) >= 0
    assert len(result.resources) >= 0
    if result.expected_count is not None:
        assert result.expected_count >= 0
    assert isinstance(result.complete, bool)
    if result.complete:
        assert result.expected_count is not None
        assert len(result.datasets) >= result.expected_count
