"""Public documentation contract for the reviewed SSEN NaFIRS HV workflow."""

from pathlib import Path


def test_ssen_docs_publish_the_accepted_evidence_contract() -> None:
    text = "\n".join(
        Path(path).read_text("utf-8")
        for path in (
            "README.md",
            "docs/public-data-sources.md",
            "docs/data-model.md",
        )
    )
    required = (
        "nafirs-hv-faults",
        "b0a58349-2ce6-4fa8-9238-a5564f966433",
        "ab32515f-76f2-421d-8034-7d5b01325a33",
        "673578c9-f531-41a5-a17c-0b35bc0fae4c",
        "SSEN Distribution",
        "Creative Commons Attribution 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        "source bytes may be redistributed with attribution",
        "day-first",
        "timezone is unknown",
        "publisher cadence is unknown",
        "raw CSV",
        "DataStore",
        "day/month",
        "SEPD and SHEPD have different schemas",
        "stable origin URL",
        "signed download URL",
        "resource-specific",
        "immutable snapshot",
        "immutable event version",
        "atomic current set",
        "explicit snapshot",
        "data/cache/outages/registry.sqlite3",
        "data/snapshots/outages/",
        "python -m app.outage_cli sync ssen-nafirs-hv",
        '$env:PYTHONPATH = "backend"',
        "/api/v1/outages/events",
        "/api/v1/outages/events/{event_id}",
        "/api/v1/outages/summary",
        "/api/v1/outages/snapshots",
        "rejects",
        "quality flags",
        "aggregate incidents",
        "not household histories",
        "non-household",
        "does not establish causality",
        "outage prevention",
    )
    missing = [value for value in required if value not in text]
    assert not missing, f"missing SSEN documentation terms: {missing}"

    readme = Path("README.md").read_text("utf-8")
    assert "The active public-data workflow is the anonymous" not in readme
    assert "does not yet expose the catalogue registry or\nverified analytical" not in readme
    assert "Run these commands from the `backend/` directory" in readme


def test_ssen_docs_do_not_advertise_authentication_or_track_local_outputs() -> None:
    env_example = Path(".env.example").read_text("utf-8")
    ignored_paths = Path(".gitignore").read_text("utf-8")

    assert "SSEN_DATAPORTAL_TOKEN=" not in env_example
    assert "data/cache/" in ignored_paths
    assert "data/snapshots/" in ignored_paths
