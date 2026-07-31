"""Behavioral public-doc contract for the reviewed SSEN NaFIRS HV workflow."""

import subprocess
from pathlib import Path


def _section(document: str, heading: str, next_heading: str) -> str:
    text = Path(document).read_text("utf-8")
    return text.split(heading, maxsplit=1)[1].split(next_heading, maxsplit=1)[0]


def _normalise(text: str) -> str:
    return " ".join(text.split())


def test_source_register_binds_identity_licence_and_source_limits() -> None:
    source = _normalise(
        _section(
            "docs/public-data-sources.md",
            "## Accepted SSEN NaFIRS HV source",
            "## Catalogue intelligence workflow",
        )
    )

    required = (
        "SSEN Distribution dataset `nafirs-hv-faults`, package "
        "`b0a58349-2ce6-4fa8-9238-a5564f966433`",
        "SEPD maps to resource `ab32515f-76f2-421d-8034-7d5b01325a33`.",
        "SHEPD maps to resource `673578c9-f531-41a5-a17c-0b35bc0fae4c`.",
        "[Creative Commons Attribution 4.0]"
        "(https://creativecommons.org/licenses/by/4.0/)",
        "source bytes may be redistributed with SSEN Distribution attribution",
        "raw CSV downloads are authoritative",
        "DataStore was observed to contain a day/month defect",
        "day-first",
        "publisher timezone is unknown",
        "publisher cadence is unknown",
        "SEPD and SHEPD have different schemas",
        "stable origin URL",
        "does not persist the temporary signed download URL",
        "resource-specific immutable snapshots and immutable event versions",
        "atomic current set",
        "safe reason codes",
        "quality flags",
    )
    assert all(claim in source for claim in required)

    forbidden = (
        "publisher timezone is UTC",
        "publisher cadence is daily",
        "real-time outage feed",
        "forecasts outages",
        "proves flexibility causality",
        "proves outage prevention",
        "establishes eligibility",
        "published record count",
        "household outage histories",
        "contains private customer data",
    )
    assert all(claim not in source for claim in forbidden)


def test_data_model_owns_time_schema_and_provenance_semantics() -> None:
    model = _normalise(
        _section(
            "docs/data-model.md",
            "## SSEN historical-outage evidence",
            "## Confidence",
        )
    )
    required = (
        "resource-specific immutable snapshot",
        "immutable event versions",
        "two-resource sync replaces the atomic current set",
        "explicit snapshot set to replay",
        "raw CSV is authoritative",
        "day-first",
        "publisher timezone is unknown",
        "publisher cadence is unknown",
        "SEPD and SHEPD have different schemas",
        "stable origin URL",
        "signed download URL",
    )
    assert all(claim in model for claim in required)
    assert "publisher timestamps are UTC" not in model
    assert "daily cadence" not in model


def test_readme_provides_copyable_sync_api_and_product_workflow() -> None:
    readme = _normalise(Path("README.md").read_text("utf-8"))
    required = (
        '$env:PYTHONPATH = "backend"',
        "python -m app.outage_cli sync ssen-nafirs-hv",
        "python -m uvicorn app.main:app --reload --port 8099",
        'Invoke-RestMethod -Uri "$apiBase/events?limit=1"',
        "$event.event_id",
        "$event.source_snapshot_id",
        "[uri]::EscapeDataString",
        "exactly one `source_snapshot_id`",
        "Zero or two detail selectors return `422`",
        "repeatable singular `source_snapshot_id`",
        "exact two-resource snapshot set",
        "read-only SSEN historical-outage queries",
        "Next.js",
        "does not expose",
        "neither API nor web surface starts",
        "read-only catalogue CLI, SSEN outage sync/query CLI and API",
    )
    assert all(claim in readme for claim in required)

    forbidden = (
        "The active public-data workflow is the anonymous",
        "does not yet expose the catalogue registry or verified analytical",
        "proves flexibility causality",
        "proves outage prevention",
    )
    assert all(claim not in readme for claim in forbidden)


def test_api_selector_contract_is_bound_to_both_operating_documents() -> None:
    readme = _normalise(Path("README.md").read_text("utf-8"))
    source = _normalise(
        _section(
            "docs/public-data-sources.md",
            "## Accepted SSEN NaFIRS HV source",
            "## Catalogue intelligence workflow",
        )
    )
    for text in (readme, source):
        assert "exactly one `source_snapshot_id`" in text
        assert "Zero or two detail selectors return `422`" in text
        assert "repeatable singular `source_snapshot_id`" in text
        assert "exact two-resource snapshot set" in text


def test_only_ssen_auth_example_is_absent_and_local_outputs_are_ignored() -> None:
    env_example = Path(".env.example").read_text("utf-8")
    assert "SSEN_DATAPORTAL_TOKEN=" not in env_example
    assert all(
        token in env_example
        for token in (
            "NGED_DATAPORTAL_TOKEN=",
            "SPEN_DATAPORTAL_TOKEN=",
            "ENWL_DATAPORTAL_TOKEN=",
            "UKPN_DATAPORTAL_TOKEN=",
            "NPG_DATAPORTAL_TOKEN=",
            "NESO_DATAPORTAL_TOKEN=",
        )
    )

    paths = (
        "data/cache/outages/registry.sqlite3",
        "data/snapshots/outages/example.csv",
    )
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", path],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
