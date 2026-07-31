# Phase 0 Product Truth and Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every active path that presents unverified, synthetic, empty,
stale, or unknown data as verified public-portal evidence.

**Architecture:** The canonical seven-portal catalogue configuration becomes
the only active portal registry. Unverified generic ingestion and seed-backed
public routes are retired; the public API becomes read-only except for a
separate, explicitly synthetic `/api/demo` namespace. Nullable models,
validation, safe error handlers, restrictive local CORS, and persistent UI
labelling make evidence status explicit.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLite migrations retained
for compatibility, pytest, Ruff, Node.js 18.18+, Next.js 15, React 18, strict
TypeScript, Vitest, Testing Library.

## Global Constraints

- Use only public sources and read-only portal operations.
- Unknown service, location, requirement, price, eligibility, cadence, and
  geography remain `None` or `unknown`; never substitute a plausible value.
- Preserve exact safe `raw_record` and `source_dataset_id` when a derived
  canonical record exists.
- Keep historical database migrations; do not delete or alter the user’s
  ignored local database.
- The synthetic demonstration may not claim that live or current portal data
  was used.
- Browser routes may not start ingestion or drift checks.
- Authentication and account state remain a user handoff.
- Immediately before every listed Git write, rerun the mandatory `ruppy7`
  identity/email/remote gate in the completion execution index and stop on any
  mismatch.
- Every task uses RED–GREEN TDD and a task-scoped commit.
- Only the orchestrator edits ignored `memory/` and `project-plan/`.

Run these fail-closed helpers at the start of every fresh PowerShell session
that will execute a commit block in this plan:

```powershell
function Assert-TaskCommitScope {
  param([Parameter(Mandatory)][string[]]$Expected)
  $untracked = @(git ls-files --others --exclude-standard)
  if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate untracked files" }
  if ($untracked) { throw "Unexpected untracked file: $($untracked -join ', ')" }
  $staged = @(git diff --cached --name-only)
  if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate staged files" }
  $delta = @(Compare-Object ($Expected | Sort-Object) ($staged | Sort-Object))
  if ($delta) { throw "Staged paths differ from exact task scope: $delta" }
  git diff --cached --check
  if ($LASTEXITCODE -ne 0) { throw "Staged diff check failed" }
}

function Assert-CleanGitState {
  param([Parameter(Mandatory)][string]$Context)
  $status = @(git status --porcelain)
  if ($LASTEXITCODE -ne 0) { throw "Unable to read Git status for $Context" }
  if ($status) { throw "$Context is not clean: $($status -join ', ')" }
}
```

---

### Task 1: Make the seven-portal catalogue configuration authoritative

**Files:**
- Modify: `backend/app/catalogue_models.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_catalogue_models.py`
- Modify: `backend/tests/test_core.py`
- Delete: `backend/app/portal_fetcher.py`

**Interfaces:**
- Consumes: immutable `CATALOGUE_PORTALS`.
- Produces:

```python
PortalId = Literal["nged", "spen", "enwl", "ssen", "ukpn", "npg", "neso"]
CATALOGUE_PORTAL_IDS: tuple[PortalId, ...]
```

`FlexCompassConfig` retains paths, local runtime settings, sampling, confidence
thresholds, and CORS only. It no longer contains `portals`, `portal()`,
or `PortalConfig`. The route token is removed with the mutation routes in
Task 3 so each intermediate commit retains its existing route behavior.

- [ ] **Step 1: Write failing authority and retirement tests**

Replace the legacy-configuration test and add:

```python
from importlib.util import find_spec

from app.catalogue_models import CATALOGUE_PORTAL_IDS, CATALOGUE_PORTALS
from app.config import config


def test_canonical_portal_ids_match_exact_configuration() -> None:
    assert CATALOGUE_PORTAL_IDS == (
        "nged", "spen", "enwl", "ssen", "ukpn", "npg", "neso"
    )
    assert tuple(CATALOGUE_PORTALS) == CATALOGUE_PORTAL_IDS


def test_application_config_has_no_duplicate_portal_registry() -> None:
    assert not hasattr(config, "portals")
    assert not hasattr(config, "portal")


def test_unverified_catalogue_fetcher_is_retired() -> None:
    assert find_spec("app.portal_fetcher") is None
```

Replace `TestConfig.test_portals_configured` in `test_core.py` with an assertion
against `CATALOGUE_PORTAL_IDS`; no test may use the retired
`config.portals`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_catalogue_models.py backend/tests/test_core.py -v
```

Expected: FAIL because duplicate configuration and retired modules still exist.

- [ ] **Step 3: Add the stable portal ID contract**

In `catalogue_models.py`, import `TypeAlias` and define:

```python
PortalId: TypeAlias = Literal[
    "nged", "spen", "enwl", "ssen", "ukpn", "npg", "neso"
]
```

Immediately after `CATALOGUE_PORTALS`, add:

```python
CATALOGUE_PORTAL_IDS: tuple[PortalId, ...] = (
    "nged",
    "spen",
    "enwl",
    "ssen",
    "ukpn",
    "npg",
    "neso",
)
```

Keep model fields such as `CatalogueDataset.portal_id` as `str`; store and
classifier tests deliberately exercise foreign IDs at invariant boundaries.

- [ ] **Step 4: Remove duplicate and unverified runtime clients**

Delete `PortalConfig`, `FlexCompassConfig.portals`, and
`FlexCompassConfig.portal()` from `config.py`. Delete `portal_fetcher.py`,
whose catalogue responsibility is replaced by the accepted adapters. Retain
`admin_token` and the currently mounted mutation modules until Task 3 removes
their routes in the same commit. Do not change historical tables in `db.py`.

Confirm no active import remains:

```powershell
$hits = rg -n "portal_fetcher|config\.portal|config\.portals" backend/app
$searchExit = $LASTEXITCODE
if ($searchExit -eq 0) {
  $hits
  throw "Active legacy portal client reference remains"
} elseif ($searchExit -ne 1) {
  throw "Legacy portal reference search failed with exit $searchExit"
}
```

Expected: no active hit outside a test asserting module retirement.

- [ ] **Step 5: Run GREEN gates**

```powershell
python -m pytest backend/tests/test_catalogue_models.py backend/tests/test_core.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/catalogue_models.py backend/app/config.py backend/tests/test_catalogue_models.py backend/tests/test_core.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

```powershell
$taskFiles = @("backend/app/catalogue_models.py", "backend/app/config.py", "backend/app/portal_fetcher.py", "backend/tests/test_catalogue_models.py", "backend/tests/test_core.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 1 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 1 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "refactor: make catalogue portals authoritative"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 1 commit"
```

### Task 2: Represent unknown analytical evidence and validate inputs

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/normaliser.py`
- Modify: `backend/app/confidence.py`
- Modify: `backend/app/matching.py`
- Modify: `backend/app/report_generator.py`
- Modify: `backend/app/routes.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/tests/test_core.py`
- Modify: `backend/tests/test_matching.py`
- Modify: `backend/tests/test_api.py`
- Modify: `data/seed/example_portfolios.json`
- Create: `backend/tests/test_model_validation.py`

**Interfaces:**
- Consumes: `PortalId` from Task 1.
- Produces:

```python
def _map_service_type(raw: str | None) -> ServiceType | None: ...

class GenerateAssetGroupRequest(BaseModel):
    asset_type: AssetType
    count: int = Field(ge=1, le=1_000_000)
    portal_id: PortalId
```

`FlexSignal.service_type`, `market_name`, `area_name`, `location_type`,
`location_reference`, `requirement_type`, `procurement_type`,
`eligible_asset_types`, and `platform` become nullable. `FlexZone.area_name`,
`zone_type`, and `platform` remain or become nullable.

- [ ] **Step 1: Write failing unknown-evidence tests**

Add to `test_core.py`:

```python
import pytest

from app.models import RatingLevel
from app.normaliser import normalise_nged_signal, normalise_nged_zone


def test_missing_service_and_requirement_remain_unknown() -> None:
    signal = normalise_nged_signal({"trade_id": "T-unknown"})
    assert signal.service_type is None
    assert signal.requirement_type is None
    assert signal.procurement_type is None
    assert signal.price_unit is None


def test_unrecognised_service_type_remains_unknown() -> None:
    signal = normalise_nged_signal(
        {"trade_id": "T-other", "service_type": "publisher-new-service"}
    )
    assert signal.service_type is None


def test_nged_zone_without_source_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing zone identity"):
        normalise_nged_zone({"area_name": "Unidentified"})
```

Add to `test_matching.py`:

```python
from app.matching import (
    _check_asset_compatibility,
    _check_geography,
    assess_portfolio,
)


def test_missing_service_evidence_is_unclear_not_incompatible() -> None:
    signal = _make_signal(service_type=None)
    level, _ = _check_asset_compatibility(_make_portfolio(), signal)
    assert level == CompatibilityLevel.unclear


def test_missing_region_evidence_is_unknown_not_weak() -> None:
    portfolio = _make_portfolio(
        assets=[_make_asset_group(regional_distribution={})]
    )
    level, _ = _check_geography(portfolio, _make_signal(dso="NGED"))
    assert level == RatingLevel.unknown


def test_assess_portfolio_handles_all_nullable_signal_evidence() -> None:
    signal = _make_signal(
        service_type=None,
        market_name=None,
        area_name=None,
        location_type=None,
        location_reference=None,
        requirement_type=None,
        procurement_type=None,
        eligible_asset_types=None,
        platform=None,
    )
    assessment = assess_portfolio(_make_portfolio(), [signal], [])[0]
    assert assessment.asset_type_compatibility == CompatibilityLevel.unclear
    assert "None" not in "\n".join(
        assessment.evidence_summary + assessment.next_steps
    )
```

- [ ] **Step 2: Write failing validation tests**

Create `test_model_validation.py`:

```python
import pytest
from pydantic import ValidationError

from app.models import AssetGroup, AssetSource, AssetType, Portfolio
from app.seed_loader import load_example_portfolios


def valid_asset(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source": AssetSource.synthetic,
        "asset_type": AssetType.battery,
        "asset_count": 1,
        "rated_power_kw": 10.0,
        "controllable_power_kw": 5.0,
        "availability_percent": 0.5,
        "response_reliability_percent": 0.9,
        "regional_distribution": {"nged": 0.5},
        "postcode_distribution": {},
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_count": 0},
        {"availability_percent": 1.01},
        {"response_reliability_percent": -0.01},
        {"controllable_power_kw": 11.0},
        {"regional_distribution": {"nged": 0.6, "spen": 0.5}},
        {"postcode_distribution": {"B1": 0.6, "B2": 0.5}},
    ],
)
def test_asset_group_rejects_impossible_inputs(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AssetGroup(**valid_asset(**overrides))


def test_asset_group_requires_explicit_source() -> None:
    value = valid_asset()
    value.pop("source")
    with pytest.raises(ValidationError):
        AssetGroup(**value)


def test_portfolio_rejects_more_than_one_thousand_groups() -> None:
    asset = AssetGroup(**valid_asset())
    with pytest.raises(ValidationError):
        Portfolio(portfolio_id="p", portfolio_name="P", assets=[asset] * 1001)


def test_checked_in_examples_use_explicit_synthetic_sources() -> None:
    portfolios = load_example_portfolios()
    assert portfolios
    assert all(
        asset.source is AssetSource.synthetic
        for portfolio in portfolios
        for asset in portfolio.assets
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_asset_group_rejects_non_finite_numbers(value: float) -> None:
    for field in (
        "rated_power_kw",
        "controllable_power_kw",
        "availability_percent",
        "response_reliability_percent",
    ):
        with pytest.raises(ValidationError):
            AssetGroup(**valid_asset(**{field: value}))
    for field in ("regional_distribution", "postcode_distribution"):
        with pytest.raises(ValidationError):
            AssetGroup(**valid_asset(**{field: {"nged": value}}))
```

Update existing API test portfolio payloads and every asset in
`data/seed/example_portfolios.json` with `"source": "synthetic"`. Loading old
or unlabeled examples must fail validation; do not add a fallback default.

Create a fail-closed application-client fixture in
`backend/tests/conftest.py`:

```python
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as app_db
from app.config import config


@pytest.fixture
def isolated_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    test_db = tmp_path / "flexcompass-test.sqlite3"
    opened: list[Path] = []
    real_connect = sqlite3.connect

    def guarded_connect(
        database: str | Path,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        resolved = Path(database).resolve()
        if resolved != test_db.resolve():
            raise AssertionError(f"application opened unexpected DB: {resolved}")
        opened.append(resolved)
        return real_connect(str(resolved), *args, **kwargs)

    original_db = config.db_path
    object.__setattr__(config, "db_path", test_db)
    try:
        monkeypatch.setattr(app_db.sqlite3, "connect", guarded_connect)

        # Importing app is allowed earlier because it performs no DB I/O;
        # entering lifespan must happen only after the guard.
        from app.main import app

        with TestClient(
            app,
            raise_server_exceptions=False,
        ) as client:
            yield client, test_db
    finally:
        object.__setattr__(config, "db_path", original_db)

    assert set(opened) <= {test_db.resolve()}


@pytest.fixture
def client(
    isolated_api_client: tuple[TestClient, Path],
) -> TestClient:
    return isolated_api_client[0]
```

Remove the module-scoped client from `test_api.py`. Every `TestClient` for the
real application consumes this function-scoped `client` fixture; only
self-contained probe applications without application imports may construct
their own clients. The frozen configuration field is set and restored with
`object.__setattr__` in `try/finally`. The guard intercepts the connection call itself, raises
before any path other than `test_db` can open, and records every accepted
connection. During Task 2, add an API assertion that the temporary database
exists and the repository's ignored `data/flexcompass.db` never appears in
`opened`. Task 3 removes startup database I/O and therefore retains only the
fail-closed subset assertion. Explicit per-test database arguments remain
authoritative in non-application tests.

- [ ] **Step 3: Run the tests and verify RED**

```powershell
python -m pytest backend/tests/test_core.py backend/tests/test_matching.py backend/tests/test_model_validation.py backend/tests/test_api.py -v
```

Expected: missing/unrecognised services currently become demand turn-down,
missing zones are invented, and model bounds are absent.

- [ ] **Step 4: Implement nullable models and bounded assets**

In `models.py`, use:

```python
import math


class AssetGroup(BaseModel):
    asset_group_id: str | None = None
    source: AssetSource
    asset_type: AssetType
    asset_count: int = Field(ge=1, le=1_000_000)
    postcode: str | None = None
    postcode_prefix: str | None = None
    rated_power_kw: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    controllable_power_kw: float = Field(
        ge=0, le=1_000_000, allow_inf_nan=False
    )
    availability_percent: float = Field(
        ge=0, le=1, allow_inf_nan=False
    )
    response_reliability_percent: float = Field(
        ge=0, le=1, allow_inf_nan=False
    )
    supported_service_types: list[ServiceType] = Field(default_factory=list)
    regional_distribution: dict[str, float] = Field(default_factory=dict)
    postcode_distribution: dict[str, float] = Field(default_factory=dict)
    baseline_assumption: str = Field(default="", max_length=2_000)
    metering_assumption: str = Field(default="", max_length=2_000)
    operational_notes: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_capacity_and_distributions(self) -> "AssetGroup":
        if self.controllable_power_kw > self.rated_power_kw:
            raise ValueError("controllable_power_kw cannot exceed rated_power_kw")
        for name, values in (
            ("regional_distribution", self.regional_distribution),
            ("postcode_distribution", self.postcode_distribution),
        ):
            if any(
                not math.isfinite(value) or value < 0 or value > 1
                for value in values.values()
            ):
                raise ValueError(f"{name} shares must be between zero and one")
            if sum(values.values()) > 1.0 + 1e-9:
                raise ValueError(f"{name} shares cannot total more than one")
        return self


class Portfolio(BaseModel):
    portfolio_id: str = Field(min_length=1, max_length=200)
    portfolio_name: str = Field(min_length=1, max_length=200)
    assets: list[AssetGroup] = Field(min_length=1, max_length=1_000)
```

Make the signal and zone fields listed under **Interfaces** nullable with
defaults of `None`.

Update the still-mounted Task 2 asset-generation route to consume
`spec.portal_id` rather than the removed `spec.region`, use the already parsed
`AssetType`, and emit an explicit synthetic source. This is an intermediate
compatibility change only; Task 3 retires the route and Task 4 recreates it
under `/api/demo`.

Update `_make_asset_group()` in `test_matching.py` with
`source=AssetSource.synthetic`, and make `_make_portfolio()` default to one
such valid asset instead of `assets=[]`. Tests that require a different asset
set pass it explicitly.

- [ ] **Step 5: Remove normaliser assumptions**

Use:

```python
def _map_service_type(raw: str | None) -> ServiceType | None:
    if not raw:
        return None
    mapping = {
        "demand_turn_down": ServiceType.demand_turn_down,
        "dtd": ServiceType.demand_turn_down,
        "demand turn down": ServiceType.demand_turn_down,
        "demand_turn_up": ServiceType.demand_turn_up,
        "dtu": ServiceType.demand_turn_up,
        "demand turn up": ServiceType.demand_turn_up,
        "generation_turn_up": ServiceType.generation_turn_up,
        "gtu": ServiceType.generation_turn_up,
        "generation turn up": ServiceType.generation_turn_up,
        "generation_turn_down": ServiceType.generation_turn_down,
        "gtd": ServiceType.generation_turn_down,
        "generation turn down": ServiceType.generation_turn_down,
    }
    return mapping.get(raw.casefold().strip())
```

In `normalise_nged_signal()` and `normalise_spen_signal()`:

```python
service_type = _map_service_type(raw.get("service_type"))
requirement_type = (
    _map_requirement_type(raw.get("requirement_type"))
    if raw.get("requirement_type")
    else None
)
```

Use this exact evidence mapping for both sources:

```text
market_name              raw.market_name only
area_name                raw.area_name only
platform                 raw.platform only
requirement_type         allow-listed raw.requirement_type only
procurement_type         raw.procurement_type only
price_unit               raw.price_unit only
eligible_asset_types     validated raw list only, otherwise None
location_reference       explicit zone_id argument or publisher zone only
location_type            zone only when location_reference exists, else None
zone.area_name           raw.area_name only
zone.zone_type           raw.zone_type only
```

`service_type` uses only the allow-list above. Pass
`service_type.value if service_type else None`, `GeographyMatch.NONE` unless
verified geography evidence is supplied, and the publisher’s actual
`eligible_asset_types` or `None` to confidence scoring. Remove fixed
`long_term`, `Electron`, `Unknown`, `constraint_zone`, `£/kW/year`, and default
eligible-asset values. Add empty and unrecognised-input tests for every mapped
field for both NGED and SPEN. Raise
`ValueError("NGED zone record is missing zone identity")` when both `zone` and
`zone_id` are blank.

- [ ] **Step 6: Make matching and reports tolerate missing evidence**

Return `CompatibilityLevel.unclear` when `signal.service_type` is `None`.
Return `CompatibilityLevel.unclear` when eligible-asset evidence is `None`.
Return `RatingLevel.unknown` when no regional or postcode evidence exists.
Make `_check_data_completeness()` test nullable location evidence without
dereferencing `.value`. Use `signal.area_name or "Unknown area"` in generated
next-step text.
Render missing fields as “Unknown” presentation text only; never write that
text into canonical records.

- [ ] **Step 7: Run GREEN gates**

```powershell
python -m pytest backend/tests/test_core.py backend/tests/test_matching.py backend/tests/test_model_validation.py backend/tests/test_api.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: all commands pass.

- [ ] **Step 8: Commit**

```powershell
$taskFiles = @("backend/app/models.py", "backend/app/normaliser.py", "backend/app/confidence.py", "backend/app/matching.py", "backend/app/report_generator.py", "backend/app/routes.py", "backend/tests/conftest.py", "backend/tests/test_core.py", "backend/tests/test_matching.py", "backend/tests/test_api.py", "backend/tests/test_model_validation.py", "data/seed/example_portfolios.json")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 2 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 2 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "fix: preserve unknown analytical evidence"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 2 commit"
```

### Task 3: Remove public mutation and seed-backed product routes

**Files:**
- Create: `backend/app/api_errors.py`
- Create: `backend/tests/test_api_security.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Replace: `backend/app/routes.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_api.py`
- Modify: `.env.example`
- Modify: `backend/app/seed_loader.py`
- Delete: `backend/app/db_loader.py`
- Delete: `backend/app/db_seed.py`
- Delete: `backend/app/ingest.py`
- Delete: `backend/app/ingest_nged.py`
- Delete: `backend/app/ingest_spen.py`
- Delete: `backend/app/ingest_enwl.py`
- Delete: `backend/app/ingest_ssen.py`
- Delete: `backend/app/drift.py`
- Delete: `data/seed/portal_datasets.json`
- Delete: `data/seed/data_sources.json`
- Delete: `data/seed/flex_zones.json`
- Delete: `data/seed/flex_signals.json`
- Delete: `data/seed/market_rules.json`

**Interfaces:**
- Produces:

```python
def _cors_origins_from_env(value: str | None) -> tuple[str, ...]: ...
def public_exception_response(request: Request, exc: Exception) -> JSONResponse: ...
def validation_exception_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse: ...
```

The public router contains only `GET /api/health` until Task 4 mounts the
explicit demo router.

- [ ] **Step 1: Write failing route and CORS tests**

Create `test_api_security.py`:

```python
import logging
from importlib.util import find_spec

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from app.api_errors import (
    public_exception_response,
    validation_exception_response,
)
from app.config import _cors_origins_from_env
from app.main import app


class SecretBearingProbe(BaseModel):
    value: str

    @model_validator(mode="after")
    def reject(self) -> "SecretBearingProbe":
        raise ValueError(f"invalid submitted value {self.value}")


class SecretKeyProbe(BaseModel):
    values: dict[str, int]


def test_public_openapi_has_no_ingest_or_drift_paths() -> None:
    paths = app.openapi()["paths"]
    assert all("ingest" not in path and "drift" not in path for path in paths)


def test_unverified_mutation_modules_are_retired() -> None:
    retired = (
        "app.ingest",
        "app.ingest_nged",
        "app.ingest_spen",
        "app.ingest_enwl",
        "app.ingest_ssen",
        "app.drift",
    )
    assert all(find_spec(name) is None for name in retired)


def test_browser_mutation_routes_are_absent_without_dispatch() -> None:
    paths = app.openapi()["paths"]
    assert "/api/ingest" not in paths
    assert "/api/drift/check" not in paths


def test_default_cors_is_local_and_never_wildcard() -> None:
    assert _cors_origins_from_env(None) == (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins_from_env("*")


def test_public_exception_never_echoes_or_logs_secret(caplog) -> None:
    secret = "https://example.test/?token=do-not-leak"
    with caplog.at_level(logging.ERROR):
        response = public_exception_response(None, RuntimeError(secret))
    assert secret not in response.body.decode()
    assert secret not in caplog.text


def test_validation_handler_never_echoes_custom_secret() -> None:
    secret = "do-not-echo-validator-input"
    test_app = FastAPI()
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )

    @test_app.post("/probe")
    def probe(payload: SecretBearingProbe) -> None:
        return None

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.post("/probe", json={"value": secret})
    assert response.status_code == 422
    assert secret not in response.text


def test_validation_handler_never_echoes_attacker_controlled_location() -> None:
    secret_key = "attacker-controlled-secret-key"
    test_app = FastAPI()
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )

    @test_app.post("/probe")
    def probe(payload: SecretKeyProbe) -> None:
        return None

    response = TestClient(
        test_app,
        raise_server_exceptions=False,
    ).post("/probe", json={"values": {secret_key: "not-an-int"}})
    assert response.status_code == 422
    assert secret_key not in response.text
```

Replace the legacy assertions in `test_api.py` for sources, signals, rules,
portfolios, reports, portal datasets, zones, ingest status, generated assets,
and drift with:

```python
def test_phase_zero_public_api_contains_health_only() -> None:
    paths = set(app.openapi()["paths"])
    assert paths == {"/", "/health", "/api/health"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/sources",
        "/api/signals",
        "/api/market-rules",
        "/api/example-portfolios",
        "/api/analyse",
        "/api/report",
        "/api/portal/datasets",
        "/api/zones",
        "/api/ingest/status",
    ],
)
def test_unverified_product_routes_are_retired(path: str) -> None:
    assert path not in app.openapi()["paths"]
```

Task 4 adds back only the explicitly labelled synthetic demo contract.
RED and GREEN retirement tests inspect only the route table/OpenAPI; they never
dispatch an active ingestion, drift, or legacy product route. Any real-app
request must use the isolated `client` fixture.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_api_security.py backend/tests/test_api.py -v
```

Expected: import failure for `api_errors`, mutation routes exist, and CORS is a
credentialed wildcard.

- [ ] **Step 3: Implement restrictive CORS**

In `config.py`:

```python
def _cors_origins_from_env(value: str | None) -> tuple[str, ...]:
    raw_values = (
        value.split(",")
        if value
        else ["http://127.0.0.1:3000", "http://localhost:3000"]
    )
    origins: list[str] = []
    for raw in raw_values:
        origin = raw.strip()
        parsed = urlsplit(origin)
        if origin == "*":
            raise ValueError("CORS wildcard is prohibited")
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("CORS origins must be absolute HTTP(S) origins")
        normalised = f"{parsed.scheme}://{parsed.netloc}"
        if normalised not in origins:
            origins.append(normalised)
    return tuple(origins)
```

Set `FlexCompassConfig.cors_origins` from
`FLEXCOMPASS_CORS_ORIGINS`.

- [ ] **Step 4: Implement public-safe exception handlers**

Create `api_errors.py`:

```python
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
DEMO_PATHS = {
    "/api/demo/portfolios",
    "/api/demo/analyse",
    "/api/demo/report",
    "/api/demo/asset-groups/generate",
}


def _public_error_content(
    request: Request | None,
    content: dict[str, object],
) -> dict[str, object]:
    if request is not None and request.url.path in DEMO_PATHS:
        return {
            **content,
            "workflow_kind": "synthetic_demo",
            "portal_data_used": False,
        }
    return content


def public_exception_response(
    request: Request | None,
    exc: Exception,
) -> JSONResponse:
    logger.error("Unhandled API exception type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=_public_error_content(
            request,
            {"detail": "Internal server error", "code": "internal_error"},
        ),
    )


def validation_exception_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_roots = {"body", "query", "path", "header", "cookie"}
    errors = [
        {
            "loc": [
                item["loc"][0]
                if item["loc"] and item["loc"][0] in safe_roots
                else "request"
            ],
            "code": item["type"],
            "message": "Invalid value",
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_public_error_content(
            request,
            {
                "detail": "Request validation failed",
                "code": "validation_error",
                "errors": errors,
            },
        ),
    )
```

Never return Pydantic `msg`, `input`, `ctx`, exception text, rejected values,
field names, mapping keys, or any location segment after the fixed request
root. The only public location values are `body`, `query`, `path`, `header`,
`cookie`, and `request`.
Register both handlers in `main.py`; the integration probe above uses a model
validator whose internal error contains its submitted value. The fixed
`DEMO_PATHS` set anticipates Task 4 and labels validation or internal errors
from those declared endpoints without echoing any request-derived path or
value. Unknown paths continue to use the generic envelope.

- [ ] **Step 5: Reduce the public API to truthful read-only health**

Replace `routes.py` with an `APIRouter(prefix="/api")` containing only:

```python
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_status": "no_verified_analytical_data"}
```

In `main.py`, remove startup seeding and route-cache loading. Register the two
exception handlers. Configure:

```python
allow_credentials=False
allow_methods=["GET", "POST", "OPTIONS"]
allow_headers=["Content-Type"]
```

Root metadata advertises only `/health` and `/api/health` until Task 4.

- [ ] **Step 6: Retire seed-backed application loaders**

Delete the loader, mutation, drift, and seed files listed under **Files** only
after the replacement router is in place. Remove `admin_token` from
`FlexCompassConfig`. Retain `data/seed/example_portfolios.json` and a single
`load_example_portfolios()` function in `seed_loader.py` for the isolated demo.
Do not alter the user’s ignored database or historical migrations.

Keep `backend/tests/conftest.py` fail-closed but permit zero application
connections after startup DB use is retired:
`set(opened) <= {test_db.resolve()}`. Remove only the Task 2 assertion that the
temporary database must exist; never remove the wrong-path guard.

Add to `.env.example`:

```dotenv
FLEXCOMPASS_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

- [ ] **Step 7: Run GREEN gates**

```powershell
python -m pytest backend/tests/test_api_security.py backend/tests/test_api.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: no public ingestion/drift route, safe errors, local CORS, and a green
suite.

- [ ] **Step 8: Commit**

```powershell
$taskFiles = @("backend/app/api_errors.py", "backend/tests/test_api_security.py", "backend/app/config.py", "backend/app/main.py", "backend/app/routes.py", "backend/tests/conftest.py", "backend/tests/test_api.py", ".env.example", "backend/app/seed_loader.py", "backend/app/db_loader.py", "backend/app/db_seed.py", "backend/app/ingest.py", "backend/app/ingest_nged.py", "backend/app/ingest_spen.py", "backend/app/ingest_enwl.py", "backend/app/ingest_ssen.py", "backend/app/drift.py", "data/seed/portal_datasets.json", "data/seed/data_sources.json", "data/seed/flex_zones.json", "data/seed/flex_signals.json", "data/seed/market_rules.json")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 3 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 3 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "security: separate public API from local mutation"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 3 commit"
```

### Task 4: Isolate and label the synthetic demonstration

**Files:**
- Create: `backend/app/demo_routes.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/report_generator.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `data/seed/example_portfolios.json`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/.eslintrc.json`
- Modify: `frontend/tsconfig.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/components/ResearchOverview.tsx`
- Create: `frontend/src/components/SyntheticDemo.tsx`
- Create: `frontend/src/components/SyntheticDemo.test.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/PortfolioForm.tsx`
- Modify: `frontend/src/components/ReportView.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/api.test.ts`
- Create: `frontend/src/app/page.test.tsx`
- Create: `frontend/src/components/PortfolioForm.test.tsx`
- Create: `frontend/src/components/ReportView.test.tsx`
- Delete: `frontend/src/components/PortalIntelligence.tsx`
- Delete: `frontend/src/components/portal/DatasetsTab.tsx`
- Delete: `frontend/src/components/portal/SignalsTab.tsx`
- Delete: `frontend/src/components/portal/SummaryCard.tsx`
- Delete: `frontend/src/components/portal/ZonesTab.tsx`

**Interfaces:**
- Produces `demo_router = APIRouter(prefix="/api/demo")`.
- Every success, validation error, and internal error from the four declared
  demo endpoints includes:

```python
workflow_kind: Literal["synthetic_demo"] = "synthetic_demo"
portal_data_used: Literal[False] = False
```

- [ ] **Step 1: Write failing backend demo tests**

```python
@pytest.fixture
def demo_portfolio() -> dict[str, object]:
    return load_example_portfolios()[0].model_dump(mode="json")


def test_legacy_portfolios_route_is_absent(client) -> None:
    assert client.get("/api/portfolios").status_code == 404


def test_demo_portfolios_are_explicitly_synthetic(client) -> None:
    response = client.get("/api/demo/portfolios")
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_kind"] == "synthetic_demo"
    assert payload["portal_data_used"] is False
    assert all(
        asset["source"] == "synthetic"
        for portfolio in payload["items"]
        for asset in portfolio["assets"]
    )


def test_demo_report_states_no_portal_data_is_used(client, demo_portfolio) -> None:
    response = client.post(
        "/api/demo/report", json={"portfolio": demo_portfolio}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["portal_data_used"] is False
    assert payload["markdown"].startswith(
        "# Synthetic Flexibility Fit Demonstration"
    )
    assert "no live or current portal data is used." in payload["markdown"].lower()


@pytest.mark.parametrize("endpoint", ["analyse", "report"])
def test_demo_rejects_real_asset_source(
    client,
    demo_portfolio,
    endpoint: str,
) -> None:
    demo_portfolio["assets"][0]["source"] = "real"
    response = client.post(
        f"/api/demo/{endpoint}", json={"portfolio": demo_portfolio}
    )
    assert response.status_code == 422
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/demo/portfolios"),
        ("post", "/api/demo/analyse"),
        ("post", "/api/demo/report"),
        ("post", "/api/demo/asset-groups/generate"),
    ],
)
def test_every_demo_response_is_labelled(
    client,
    demo_portfolio: dict[str, object],
    method: str,
    path: str,
) -> None:
    body = (
        {"asset_type": "battery", "count": 2, "portal_id": "nged"}
        if path.endswith("/generate")
        else {"portfolio": demo_portfolio}
    )
    if method == "get":
        body = None
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False


def test_demo_handlers_never_open_database_or_network(
    client,
    demo_portfolio,
    monkeypatch,
) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("demo attempted external I/O")

    test_client_send = client.send
    monkeypatch.setattr(app_db.sqlite3, "connect", unexpected)
    monkeypatch.setattr(httpx.Client, "send", unexpected)
    monkeypatch.setattr(httpx.AsyncClient, "send", unexpected)
    # Starlette TestClient subclasses httpx.Client. Preserve only this already
    # constructed in-process transport entry point; application-created HTTPX
    # clients still hit the class-level guard.
    monkeypatch.setattr(client, "send", test_client_send)

    assert client.get("/api/demo/portfolios").status_code == 200
    assert client.post(
        "/api/demo/analyse", json={"portfolio": demo_portfolio}
    ).status_code == 200
    assert client.post(
        "/api/demo/report", json={"portfolio": demo_portfolio}
    ).status_code == 200
    assert client.post(
        "/api/demo/asset-groups/generate",
        json={"asset_type": "battery", "count": 2, "portal_id": "nged"},
    ).status_code == 200


def test_demo_internal_error_keeps_labels_and_redaction(
    client,
    demo_portfolio,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        demo_routes,
        "analyse_synthetic_portfolio",
        lambda *_: (_ for _ in ()).throw(RuntimeError("private-value")),
    )
    response = client.post(
        "/api/demo/analyse", json={"portfolio": demo_portfolio}
    )
    assert response.status_code == 500
    assert response.json()["workflow_kind"] == "synthetic_demo"
    assert response.json()["portal_data_used"] is False
    assert "private-value" not in response.text
```

- [ ] **Step 2: Verify backend RED**

```powershell
python -m pytest backend/tests/test_api.py -v
```

Expected: `/api/demo` is absent.

- [ ] **Step 3: Implement demo contracts and router**

Add:

```python
def require_synthetic_portfolio(portfolio: Portfolio) -> Portfolio:
    if any(
        asset.source is not AssetSource.synthetic
        for asset in portfolio.assets
    ):
        raise ValueError("demo workflow accepts synthetic assets only")
    return portfolio


class DemoAnalyseRequest(BaseModel):
    portfolio: Portfolio

    @model_validator(mode="after")
    def require_synthetic_assets(self) -> "DemoAnalyseRequest":
        require_synthetic_portfolio(self.portfolio)
        return self


class DemoReportRequest(BaseModel):
    portfolio: Portfolio

    @model_validator(mode="after")
    def require_synthetic_assets(self) -> "DemoReportRequest":
        require_synthetic_portfolio(self.portfolio)
        return self


class DemoPortfolioListResponse(BaseModel):
    workflow_kind: Literal["synthetic_demo"] = "synthetic_demo"
    portal_data_used: Literal[False] = False
    items: list[Portfolio]


class DemoAnalyseResponse(AnalyseResponse):
    workflow_kind: Literal["synthetic_demo"] = "synthetic_demo"
    portal_data_used: Literal[False] = False


class DemoReportResponse(ReportResponse):
    workflow_kind: Literal["synthetic_demo"] = "synthetic_demo"
    portal_data_used: Literal[False] = False


class DemoAssetGroupResponse(BaseModel):
    workflow_kind: Literal["synthetic_demo"] = "synthetic_demo"
    portal_data_used: Literal[False] = False
    item: AssetGroup
```

Mount GET `/portfolios`, POST `/analyse`, POST `/report`, and POST
`/asset-groups/generate` only under `/api/demo`. The generated request uses
`portal_id: PortalId`, and every generated group sets
`source=AssetSource.synthetic`. Assign the four exact response models above to
their routes. The module may import only the checked-in synthetic seed loader,
models, matching/report pure functions, and FastAPI/Pydantic contracts; it must
not import the database, catalogue repositories/adapters, outage store, portal
clients, or network libraries. `GET /portfolios` reads only the checked-in
synthetic JSON. Analyse and report pass only the submitted synthetic portfolio
and explicit empty verified-signal/zone collections into pure analysis
functions. The generator is a pure transformation of its request. No handler
opens SQLite, loads a catalogue snapshot, or performs network I/O.

Change the report heading and first paragraph to:

```markdown
# Synthetic Flexibility Fit Demonstration

> Synthetic demonstration — no live or current portal data is used.
```

- [ ] **Step 4: Add the frontend test harness**

Run exact Node-18-compatible versions and lock them:

```powershell
Push-Location frontend
try {
  npm install --save-dev --save-exact vitest@2.1.9 jsdom@25.0.1 @testing-library/react@16.1.0 @testing-library/jest-dom@6.6.3 @testing-library/user-event@14.5.2
  if ($LASTEXITCODE -ne 0) { throw "Frontend test dependency install failed" }
} finally {
  Pop-Location
}
```

Add scripts:

```json
"test": "vitest run",
"lint": "eslint \"src/**/*.{ts,tsx}\" --max-warnings=0"
```

Create `.eslintrc.json`:

```json
{
  "extends": ["next/core-web-vitals"],
  "globals": {
    "afterEach": "readonly",
    "beforeEach": "readonly",
    "describe": "readonly",
    "expect": "readonly",
    "it": "readonly",
    "vi": "readonly"
  }
}
```

Add `"vitest/globals"` and `"@testing-library/jest-dom"` to
`compilerOptions.types` in `frontend/tsconfig.json`; retain all existing
compiler options and included paths. This makes test globals explicit to both
TypeScript and ESLint rather than relying on editor/runtime inference.

Create `vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"]
  },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
});
```

Create `src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
});
```

Every mounted component test installs an explicit `globalThis.fetch` mock
before render; no test may depend on a running API.

- [ ] **Step 5: Write failing frontend truth tests**

```tsx
const DEMO_PORTFOLIO = {
  portfolio_id: "frontend-demo",
  portfolio_name: "Frontend synthetic demo",
  assets: [{
    source: "synthetic",
    asset_type: "battery",
    asset_count: 1,
    rated_power_kw: 10,
    controllable_power_kw: 5,
    availability_percent: 0.5,
    response_reliability_percent: 0.9,
    regional_distribution: {},
    postcode_distribution: {},
  }],
};


it("defaults to research overview without the synthetic form", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { name: /research status/i })).toBeVisible();
  expect(screen.queryByText(/build synthetic scenario/i)).not.toBeInTheDocument();
});

it("labels the synthetic demonstration persistently", async () => {
  render(<Home />);
  await userEvent.click(screen.getByRole("tab", { name: /synthetic demo/i }));
  expect(
    screen.getByText(/no live or current portal data is used/i),
  ).toBeVisible();
});


it("submits every custom asset with an explicit synthetic source", async () => {
  render(<PortfolioForm onSubmit={onSubmit} />);
  await completeValidForm();
  await userEvent.click(screen.getByRole("button", { name: /analyse/i }));
  expect(onSubmit).toHaveBeenCalledWith(
    expect.objectContaining({
      assets: [
        expect.objectContaining({ source: "synthetic" }),
      ],
    }),
  );
});


it("downloads only the labelled synthetic report filename", async () => {
  render(<ReportView report={SYNTHETIC_REPORT} />);
  await userEvent.click(screen.getByRole("button", { name: /download/i }));
  expect(lastDownloadName()).toBe("flexcompass-synthetic-demo.md");
});


it("uses only labelled demo API contracts", async () => {
  mockFetchJson(DEMO_ANALYSE_RESPONSE);
  await analyseDemoPortfolio(DEMO_PORTFOLIO);
  expect(fetch).toHaveBeenCalledWith(
    "/api/demo/analyse",
    expect.objectContaining({ method: "POST" }),
  );
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body)))
    .toEqual(expect.objectContaining({
      portfolio: expect.objectContaining({
        assets: [
          expect.objectContaining({ source: "synthetic" }),
        ],
      }),
    }));
});


it.each([
  ["portfolios", () => fetchDemoPortfolios(), "/api/demo/portfolios", "GET"],
  [
    "analyse",
    () => analyseDemoPortfolio(DEMO_PORTFOLIO),
    "/api/demo/analyse",
    "POST",
  ],
  [
    "report",
    () => generateDemoReport(DEMO_PORTFOLIO),
    "/api/demo/report",
    "POST",
  ],
])("uses the exact %s helper contract", async (_name, invoke, path, method) => {
  mockFetchJson(responseFor(path));
  await invoke();
  expect(fetch).toHaveBeenLastCalledWith(
    path,
    expect.objectContaining({ method }),
  );
});
```

Expected: FAIL because the current page renders legacy portal intelligence and
unlabelled portfolio analysis, the old API paths remain, asset source is not
sent, and the report uses the legacy download name.

- [ ] **Step 6: Verify frontend RED**

```powershell
Push-Location frontend
try {
  npm test
  if ($LASTEXITCODE -eq 0) { throw "Frontend truth tests unexpectedly passed" }
} finally {
  Pop-Location
}
```

- [ ] **Step 7: Implement the truthful frontend**

Use two top-level tabs:

```typescript
type Tab = "overview" | "synthetic_demo";
```

Default to `Research Overview`. Its fixed evidence-status copy is:

```text
Catalogue metadata: seven public portal catalogues are available through the
local read-only catalogue CLI; the product observatory is not connected yet.
Analytical data: no verified canonical flexibility signal or zone dataset is
available in this release.
```

The `Synthetic Demo` tab wraps form and report in a persistent amber banner:

```text
Synthetic demonstration — no live or current portal data is used.
```

Rename frontend functions to `fetchDemoPortfolios()`,
`analyseDemoPortfolio()`, and `generateDemoReport()` and call only
`/api/demo/*`. Require `AssetGroup.source` in TypeScript. Use download filename
`flexcompass-synthetic-demo.md`.

- [ ] **Step 8: Run GREEN gates**

```powershell
python -m pytest backend/tests/test_api.py backend/tests/test_api_security.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm test
  if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }
  npm run lint
  if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
  Pop-Location
}
```

Expected: all commands pass.

- [ ] **Step 9: Commit**

```powershell
$taskFiles = @("backend/app/demo_routes.py", "backend/app/models.py", "backend/app/report_generator.py", "backend/app/main.py", "backend/tests/test_api.py", "data/seed/example_portfolios.json", "frontend/package.json", "frontend/package-lock.json", "frontend/.eslintrc.json", "frontend/tsconfig.json", "frontend/vitest.config.ts", "frontend/src/test/setup.ts", "frontend/src/components/ResearchOverview.tsx", "frontend/src/components/SyntheticDemo.tsx", "frontend/src/components/SyntheticDemo.test.tsx", "frontend/src/app/page.tsx", "frontend/src/components/PortfolioForm.tsx", "frontend/src/components/ReportView.tsx", "frontend/src/lib/api.ts", "frontend/src/lib/types.ts", "frontend/src/lib/api.test.ts", "frontend/src/app/page.test.tsx", "frontend/src/components/PortfolioForm.test.tsx", "frontend/src/components/ReportView.test.tsx", "frontend/src/components/PortalIntelligence.tsx", "frontend/src/components/portal/DatasetsTab.tsx", "frontend/src/components/portal/SignalsTab.tsx", "frontend/src/components/portal/SummaryCard.tsx", "frontend/src/components/portal/ZonesTab.tsx")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 4 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 4 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: isolate synthetic demonstration"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 4 commit"
```

### Task 5: Rebaseline public documentation and close Phase 0

**Files:**
- Modify: `README.md`
- Modify: `docs/data-model.md`
- Modify: `docs/public-data-sources.md`
- Orchestrator modify after the public commit: `memory/CURRENT.md`
- Orchestrator modify after the public commit: `project-plan/README.md`
- Orchestrator modify after the public commit: `project-plan/backlog.md`
- Orchestrator modify after the public commit: `project-plan/decisions.md`

**Interfaces:**
- Consumes: accepted Tasks 1–4.
- Produces: public documentation that exactly matches the Phase 0 runtime.

- [ ] **Step 1: Write the documentation changes**

Make these exact statements:

```text
The active public-data workflow is the anonymous, read-only seven-portal
catalogue CLI.

The web application exposes a research-status overview and an explicitly
synthetic demonstration. It does not yet expose the catalogue registry or
verified analytical portal records.

The legacy generic portal ingestors and browser-triggered mutation routes were
retired because they lacked accepted source contracts and end-to-end
provenance.
```

Remove legacy `python -m backend.app.ingest`, `/api/ingest`, `/api/drift`, and
database-seeding instructions. Document `CATALOGUE_PORTALS` as the sole active
portal registry.

- [ ] **Step 2: Scan active public and local routing text**

```powershell
$patterns = "pending final user review|four metadata-only|all four implemented|python -m backend\.app\.ingest|/api/ingest|/api/drift|nged_params|api/v2/catalog/datasets"
$hits = rg -n $patterns README.md docs/data-model.md docs/public-data-sources.md backend/app .env.example
if ($LASTEXITCODE -eq 0) { $hits; exit 1 }
if ($LASTEXITCODE -ne 1) { exit $LASTEXITCODE }
```

Expected: no active hit.

- [ ] **Step 3: Run the complete Phase 0 gate**

```powershell
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
  npm test
  if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }
  npm run lint
  if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
  Pop-Location
}
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$status = git status --porcelain
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$expected = @("README.md", "docs/data-model.md", "docs/public-data-sources.md")
# Fail unless every status path is one of the three Task 5 documentation files.
if ($status | Where-Object {
  $path = $_.Substring(3)
  $expected -notcontains $path
}) { throw "Unexpected Phase 0 gate change" }
```

Expected: all checks pass; status contains only Task 5 public documentation
before commit. Known ignored local `.env` and SQLite files remain untouched.

- [ ] **Step 4: Obtain independent final review**

The Sol-high reviewer must verify:

```text
No unknown-to-fact default remains in active normalisation.
No active public route starts ingestion or drift.
No raw exception value reaches a response.
CORS has no wildcard or credentialed cross-origin access.
The default UI contains no synthetic form or legacy catalogue claims.
Every synthetic input, response, report, and download is labelled.
The seven canonical portal IDs and API bases remain unchanged.
```

Expected: PASS with no Critical, Important, or Minor finding.

- [ ] **Step 5: Commit**

```powershell
$taskFiles = @("README.md", "docs/data-model.md", "docs/public-data-sources.md")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 5 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 5 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "docs: rebaseline Phase 0 product truth"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 5 commit"
```

- [ ] **Step 6: Synchronise orchestrator-owned local records**

After the public documentation commit, the orchestrator—not the implementation
subagent—updates the four local files named under **Files** with the accepted
Phase 0 head, capability truth, retired backlog items, decisions, verification,
cleanliness, and next WP2.1 action. Verify:

```powershell
git status --short --branch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git check-ignore memory/CURRENT.md project-plan/README.md project-plan/backlog.md project-plan/decisions.md
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: local continuity is current, all four files remain ignored, and none
is staged or committed.
