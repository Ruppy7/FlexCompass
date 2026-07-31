# Catalogue Observatory API and Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the completed seven-portal registry into a truthful, read-only
catalogue observatory with durable refresh state, last-valid snapshot semantics,
versioned API contracts, and an accessible frontend.

**Architecture:** The application reads the dedicated catalogue registry and
validated immutable snapshots, never legacy seeds or mutable current rows as a
substitute for the last complete observation. Every requested portal records a
durable refresh attempt, including failures. A GET-only `/api/v1/catalogue`
router exposes safe Pydantic projections; a tested React observatory renders
coverage, datasets, evidence, assessments, and observation history.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLite migration 8, pytest,
Ruff, Node.js 18+, Next.js 15, React 18, strict TypeScript, Vitest, Testing
Library.

## Global Constraints

- Phase 0 and WP2.1 must be accepted and merged before execution.
- Use `FLEXCOMPASS_CATALOGUE_DB_PATH`, default
  `data/cache/catalogue/registry.sqlite3`.
- Use `FLEXCOMPASS_CATALOGUE_SNAPSHOT_DIR`, default
  `data/snapshots/catalogues`.
- All routes in `catalogue_router` are GET-only.
- A missing or invalid last complete snapshot is `unavailable`; never fall back
  to partial data, mutable current tables, local legacy rows, or JSON seeds.
- Public responses exclude auth environment-variable names, raw errors,
  request URLs, raw pages/records, snapshot/local paths, and reviewer identity.
- Failed refreshes remain visible beside, not instead of, the last valid
  complete observation.
- Review windows are FlexCompass operational policy, not publisher cadence.
- Unknown, restricted, unreachable, partial, failed, archival, and superseded
  states use visible text and not colour alone.
- Immediately before every listed Git write, rerun the mandatory `ruppy7`
  identity/email/remote gate in the completion execution index and stop on any
  mismatch.

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

### Task 1: Persist every catalogue refresh attempt

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/catalogue_store.py`
- Modify: `backend/app/catalogue_sync.py`
- Modify: `backend/app/catalogue_cli.py`
- Modify: `backend/app/config.py`
- Create: `data/catalogue/refresh-policy.json`
- Modify: `backend/tests/test_catalogue_store.py`
- Modify: `backend/tests/test_catalogue_sync.py`

**Interfaces:**
- Produces migration 8 and:

```python
def refresh_attempt_key(portal_id: str, attempted_at: datetime) -> str: ...


def record_catalogue_refresh_attempt(
    conn: sqlite3.Connection,
    *,
    portal_id: str,
    attempted_at: datetime,
    status: ObservationStatus,
    observation_id: str | None,
    warnings: Sequence[str],
    safe_error_text: str | None,
) -> str: ...
```

- [ ] **Step 1: Write failing migration and failure-durability tests**

```python
def test_migration_eight_adds_refresh_attempts(tmp_path: Path) -> None:
    run_migrations(tmp_path / "registry.sqlite3")
    with get_connection(tmp_path / "registry.sqlite3") as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(catalogue_refresh_attempts)"
            )
        }
    assert columns == {
        "attempt_id",
        "portal_id",
        "attempted_at",
        "status",
        "observation_id",
        "warning_count",
        "safe_error",
        "created_at",
    }


def test_failed_sync_persists_attempt_without_mutating_last_valid(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_complete_observation(db_path)
    sync_catalogues(
        portals=["nged"],
        db_path=db_path,
        output_dir=tmp_path / "snapshots",
        fetcher=raising_fetcher,
        client_factory=fake_client_factory,
    )
    with get_connection(db_path) as conn:
        attempts = conn.execute(
            "SELECT status, observation_id FROM catalogue_refresh_attempts"
        ).fetchall()
        last = latest_catalogue_observation(conn, "nged")
    assert attempts[-1] == ("failed", None)
    assert last["status"] == "complete"
```

Add migration rollback, idempotence, successful-observation FK, and one-attempt-
per-requested-portal tests.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_store.py backend/tests/test_catalogue_sync.py -k "refresh_attempt or migration_eight or failed_sync" -v
```

Expected: table and store functions are absent; failed attempts vanish after
the process returns.

- [ ] **Step 3: Append migration 8**

Add:

```sql
CREATE TABLE IF NOT EXISTS catalogue_refresh_attempts (
    attempt_id      TEXT PRIMARY KEY,
    portal_id       TEXT NOT NULL,
    attempted_at    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('complete','partial','failed')),
    observation_id  TEXT,
    warning_count   INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    safe_error      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (portal_id, attempted_at),
    FOREIGN KEY (observation_id)
        REFERENCES catalogue_observations(observation_id),
    CHECK (
        (status = 'failed' AND observation_id IS NULL)
        OR (status IN ('complete','partial') AND observation_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_catalogue_attempts_portal_time
    ON catalogue_refresh_attempts(portal_id, attempted_at DESC);
```

Insert schema version 8 in the same transaction.

- [ ] **Step 4: Record every sync outcome**

`record_catalogue_refresh_attempt()` stores only already-sanitised warning count
and `safe_error()`. Update `sync_catalogues()` so each requested portal records
one attempt whether `_sync_one()` completes, is partial, or raises. A failure
must not call `persist_catalogue_result()`.

Add `catalogue_db_path` and `catalogue_snapshot_dir` to
`FlexCompassConfig`. Make CLI defaults use those settings.

- [ ] **Step 5: Add operational review policy**

Create:

```json
{
  "schema_version": 1,
  "review_window_hours": {
    "nged": 168,
    "spen": 168,
    "enwl": 168,
    "ssen": 168,
    "ukpn": 168,
    "npg": 168,
    "neso": 168
  }
}
```

Document in code that this is a FlexCompass review SLA, not source cadence.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_store.py backend/tests/test_catalogue_sync.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/db.py", "backend/app/catalogue_store.py", "backend/app/catalogue_sync.py", "backend/app/catalogue_cli.py", "backend/app/config.py", "data/catalogue/refresh-policy.json", "backend/tests/test_catalogue_store.py", "backend/tests/test_catalogue_sync.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 1 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 1 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: persist catalogue refresh attempts"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 1 commit"
```

### Task 2: Promote immutable last-valid snapshot queries

**Files:**
- Create: `backend/app/catalogue_snapshot.py`
- Create: `backend/app/catalogue_repository.py`
- Modify: `backend/app/catalogue_sync.py`
- Modify: `backend/app/catalogue_store.py`
- Create: `backend/tests/test_catalogue_repository.py`
- Modify: `backend/tests/test_catalogue_sync.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CatalogueSnapshot:
    portal_id: str
    observation_id: str
    observed_at: datetime
    content_hash: str
    datasets: tuple[CatalogueDataset, ...]
    resources: tuple[DatasetResource, ...]
    evidence: tuple[ClassificationEvidence, ...]


def load_catalogue_snapshot(
    snapshot_path: Path,
    *,
    snapshot_root: Path,
    expected_portal_id: str,
    expected_content_hash: str,
) -> CatalogueSnapshot: ...


class CatalogueRepository:
    def portal_state(self, portal_id: PortalId, *, now: datetime) -> PortalState: ...
    def load_complete_observation(
        self,
        portal_id: PortalId,
        observation_id: str,
    ) -> CatalogueSnapshot: ...
    def list_last_valid_datasets(self, portal_id: PortalId) -> tuple[CatalogueDataset, ...]: ...
    def get_last_valid_dataset(
        self,
        portal_id: PortalId,
        source_dataset_id: str,
    ) -> CatalogueDataset | None: ...
```

- [ ] **Step 1: Write failing path and last-valid tests**

```python
def test_snapshot_loader_rejects_path_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(valid_snapshot_json(), "utf-8")
    with pytest.raises(ValueError, match="snapshot root"):
        load_catalogue_snapshot(
            outside,
            snapshot_root=tmp_path / "approved",
            expected_portal_id="nged",
            expected_content_hash=CONTENT_HASH,
        )


def test_partial_refresh_does_not_replace_last_complete_snapshot(
    repository: CatalogueRepository,
) -> None:
    state = repository.portal_state("nged", now=NOW)
    assert state.current_attempt_status == "partial"
    assert state.last_complete_observation_id == COMPLETE_OBSERVATION_ID
    assert repository.list_last_valid_datasets("nged") == COMPLETE_DATASETS


def test_invalid_newest_complete_falls_back_to_older_valid_snapshot(
    repository: CatalogueRepository,
) -> None:
    corrupt_newest_complete_file(repository)
    state = repository.portal_state("nged", now=NOW)
    assert state.latest_complete_snapshot_valid is False
    assert state.degraded is True
    assert state.last_valid_observation_id == OLDER_COMPLETE_OBSERVATION_ID
    assert repository.list_last_valid_datasets("nged") == OLDER_DATASETS


def test_all_complete_snapshots_invalid_is_unavailable(
    repository: CatalogueRepository,
) -> None:
    corrupt_every_complete_file(repository)
    state = repository.portal_state("nged", now=NOW)
    assert state.snapshot_available is False
    assert state.last_valid_observation_id is None
    assert repository.list_last_valid_datasets("nged") == ()
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_repository.py -v
```

Expected: repository and public snapshot loader are absent.

- [ ] **Step 3: Extract snapshot validation**

Move validation, manifest/count/association checks, and content-hash
verification from private `catalogue_sync` helpers into
`catalogue_snapshot.py`. Resolve both root and candidate path and require:

```python
candidate.is_relative_to(snapshot_root.resolve())
```

Reconstruct Pydantic records from validated content. Do not expose the stored
path from `CatalogueSnapshot`.

- [ ] **Step 4: Implement repository semantics**

Query the newest refresh attempt and complete observations separately.
`load_complete_observation()` validates any named complete observation through
the single snapshot loader. Scan complete observations newest-first until one
valid snapshot is found. Expose the newest complete observation and its
validation failure separately from the older `last_valid_observation_id`; set
`degraded=True` while fallback is active. Return unavailable only when no
complete observation validates. Do not query `catalogue_datasets` as a
fallback.

Make classification assessment IDs observation-specific:

```python
sha256(
    f"{portal_id}\n{source_dataset_id}\n"
    f"{observation_id}\n{assessment_type}".encode()
).hexdigest()
```

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_repository.py backend/tests/test_catalogue_sync.py backend/tests/test_catalogue_store.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/catalogue_snapshot.py backend/app/catalogue_repository.py backend/app/catalogue_sync.py backend/app/catalogue_store.py backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/catalogue_snapshot.py", "backend/app/catalogue_repository.py", "backend/app/catalogue_sync.py", "backend/app/catalogue_store.py", "backend/tests/test_catalogue_repository.py", "backend/tests/test_catalogue_sync.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 2 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 2 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: query validated catalogue snapshots"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 2 commit"
```

### Task 3: Add versioned GET-only catalogue API contracts

**Files:**
- Create: `backend/app/catalogue_identity.py`
- Create: `backend/app/catalogue_api_models.py`
- Create: `backend/app/catalogue_routes.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routes.py`
- Create: `backend/tests/test_catalogue_api.py`

**Interfaces:**
- Produces:

```python
def encode_dataset_ref(portal_id: str, source_dataset_id: str) -> str: ...
def decode_dataset_ref(value: str) -> tuple[str, str]: ...

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def create_app(settings: FlexCompassConfig | None = None) -> FastAPI: ...
```

Routes:

```text
GET /api/v1/catalogue/portals
GET /api/v1/catalogue/portals/{portal_id}
GET /api/v1/catalogue/datasets
GET /api/v1/catalogue/datasets/{dataset_ref}
GET /api/v1/catalogue/datasets/{dataset_ref}/resources
GET /api/v1/catalogue/datasets/{dataset_ref}/evidence
GET /api/v1/catalogue/datasets/{dataset_ref}/assessments
GET /api/v1/catalogue/observations
```

- [ ] **Step 1: Write failing identity and API tests**

```python
def test_dataset_ref_round_trips_source_ids_with_slashes() -> None:
    ref = encode_dataset_ref("ssen", "folder/dataset:id")
    assert decode_dataset_ref(ref) == ("ssen", "folder/dataset:id")
    assert "=" not in ref


@pytest.mark.parametrize("value", ["x" * 2049, "%2F", "not-base64"])
def test_dataset_ref_rejects_noncanonical_input(value: str) -> None:
    with pytest.raises(ValueError):
        decode_dataset_ref(value)


def test_catalogue_api_reads_last_valid_snapshot_not_legacy_seed(
    client,
    catalogue_repository,
) -> None:
    response = client.get("/api/v1/catalogue/datasets?portal_id=nged")
    assert response.status_code == 200
    assert response.json()["total"] == len(COMPLETE_DATASETS)
    assert all(item["portal_id"] == "nged" for item in response.json()["items"])


def test_catalogue_router_is_get_only() -> None:
    for route in catalogue_router.routes:
        assert route.methods <= {"GET", "HEAD"}


def test_api_startup_migrates_distinct_catalogue_database(
    tmp_path: Path,
) -> None:
    app_db = tmp_path / "app.sqlite3"
    catalogue_db = tmp_path / "catalogue" / "registry.sqlite3"
    settings = test_settings(
        app_db=app_db,
        catalogue_db=catalogue_db,
        snapshot_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings)):
        pass
    assert schema_version(catalogue_db) == 8
```

Also test pagination 1–200, stable order, filters, 404s, failed refresh beside
last complete, corrupt-newest degradation beside older last-valid evidence,
distinct-database upgrade from schema 7, and absence of
raw/local/auth/request fields.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_api.py -v
```

Expected: modules and versioned routes are absent.

- [ ] **Step 3: Implement opaque references**

Encode canonical compact JSON `[portal_id, source_dataset_id]` with unpadded
URL-safe base64. Decode only input at most 2,048 characters, require two
non-empty strings, require `portal_id` in `CATALOGUE_PORTAL_IDS`, and re-encode
to prove canonical form.

- [ ] **Step 4: Implement safe response models**

`CataloguePortalSummaryV1` contains configured public identity, current
attempt status/time, 168-hour operational window/due time, review status
`current|overdue|never_attempted`, newest-complete observation and validation
state, last-valid observation/time/counts, `degraded`, partial/failed state,
and `snapshot_available`.

Dataset/resource/evidence/assessment projections contain safe canonical fields
but omit:

```text
raw_record
raw_pages
snapshot_path
request_url
endpoint
safe_error
auth_env_var
reviewer identity
URL query and fragment
```

- [ ] **Step 5: Implement and mount the router**

During FastAPI lifespan, call `run_migrations(config.catalogue_db_path)` before
serving catalogue routes, independently of the application database migration.
Tests inject both paths and never touch a user database.

Use default limit 50 and bounds 1–200. Stable dataset order is
`(portal_id, source_dataset_id)`; stable resource/evidence/assessment order
uses publisher/stable IDs. Filters include portal, text query, lifecycle,
publication pattern, access status, and maintenance state.

Add a compatibility response:

```python
@router.get("/portal/datasets", status_code=410)
def retired_portal_dataset_route() -> dict[str, str]:
    return {"detail": "Use /api/v1/catalogue/datasets"}
```

It never reads legacy rows.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_api.py backend/tests/test_catalogue_repository.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/catalogue_identity.py", "backend/app/catalogue_api_models.py", "backend/app/catalogue_routes.py", "backend/app/config.py", "backend/app/main.py", "backend/app/routes.py", "backend/tests/test_catalogue_api.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 3 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 3 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: expose read-only catalogue API"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 3 commit"
```

### Task 4: Add exact frontend catalogue contracts

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces:

```typescript
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type CatalogueTab = "coverage" | "datasets";

export interface CatalogueRequestOptions {
  signal?: AbortSignal;
}

export async function fetchCataloguePortals(
  options?: CatalogueRequestOptions,
): Promise<Page<CataloguePortalSummary>>;
export async function fetchCatalogueDatasets(
  filters: CatalogueDatasetFilters,
  options?: CatalogueRequestOptions,
): Promise<Page<CatalogueDatasetSummary>>;
export async function fetchCatalogueDataset(
  datasetRef: string,
  options?: CatalogueRequestOptions,
): Promise<CatalogueDatasetDetail>;
```

- [ ] **Step 1: Write failing API-client tests**

```typescript
it("uses only versioned catalogue GET endpoints", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 })),
  );
  await fetchCatalogueDatasets({
    portalId: "ssen",
    query: "outage",
    limit: 50,
    offset: 0,
  });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalogue/datasets?portal_id=ssen&q=outage&limit=50&offset=0",
    { method: "GET" },
  );
});


it("does not request legacy portal, zone, signal or ingest routes", async () => {
  await loadCatalogueInitialState();
  const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
  expect(urls.every((url) => url.startsWith("/api/v1/catalogue/"))).toBe(true);
});


it("forwards the caller AbortSignal to catalogue fetch", async () => {
  const controller = new AbortController();
  await fetchCatalogueDatasets(
    { portalId: "ssen", limit: 50, offset: 0 },
    { signal: controller.signal },
  );
  expect(fetch).toHaveBeenLastCalledWith(
    expect.any(String),
    expect.objectContaining({
      method: "GET",
      signal: controller.signal,
    }),
  );
});
```

- [ ] **Step 2: Verify RED**

```powershell
Push-Location frontend
try {
  npm test -- src/lib/api.test.ts
  if ($LASTEXITCODE -eq 0) { throw "Catalogue API tests unexpectedly passed" }
} finally {
  Pop-Location
}
```

Expected: versioned types and functions are absent.

- [ ] **Step 3: Implement typed GET functions**

Use `URLSearchParams` and omit undefined filters. Every call passes
`{ method: "GET" }`. Preserve the full `Page<T>` instead of discarding
pagination metadata. Map non-2xx to stable user-facing messages without
including raw response bodies.

- [ ] **Step 4: Run GREEN and commit**

```powershell
Push-Location frontend
try {
  npm test -- src/lib/api.test.ts
  if ($LASTEXITCODE -ne 0) { throw "Catalogue API client tests failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
} finally {
  Pop-Location
}
$taskFiles = @("frontend/src/lib/types.ts", "frontend/src/lib/api.ts", "frontend/src/lib/api.test.ts")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 4 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 4 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add catalogue frontend contracts"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 4 commit"
```

### Task 5: Build the coverage and dataset observatory

**Files:**
- Create: `frontend/src/components/catalogue/CatalogueObservatory.tsx`
- Create: `frontend/src/components/catalogue/PortalCoverageGrid.tsx`
- Create: `frontend/src/components/catalogue/DatasetTable.tsx`
- Create: `frontend/src/components/catalogue/DatasetDetail.tsx`
- Create: `frontend/src/components/catalogue/ObservationHistory.tsx`
- Create: `frontend/src/components/catalogue/CatalogueStateBadge.tsx`
- Create: corresponding `.test.tsx` files
- Create: `frontend/src/components/PortalIntelligence.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Consumes: Task 4 API functions.
- Preserves the accepted Phase 0 top-level `Research Overview` and
  `Synthetic Demo` workflows.
- Produces top-level navigation `Research Overview`, `Catalogue Observatory`,
  and `Synthetic Demo`; the catalogue view owns inner tabs `Coverage` and
  `Datasets`.

- [ ] **Step 1: Write failing component tests**

```tsx
it("shows a failed refresh beside the last complete observation", () => {
  render(<PortalCoverageGrid portals={[FAILED_WITH_LAST_COMPLETE]} />);
  expect(screen.getByText("Refresh failed")).toBeVisible();
  expect(screen.getByText(/Last complete/)).toBeVisible();
});


it("shows an invalid newest attempt beside the older last-valid timestamp", () => {
  render(<PortalCoverageGrid portals={[INVALID_NEWEST_WITH_LAST_VALID]} />);
  expect(screen.getByText("Snapshot checksum invalid")).toBeVisible();
  expect(
    screen.getByText("Latest attempt: 30 July 2026, 12:00 UTC"),
  ).toBeVisible();
  expect(
    screen.getByText("Last valid: 29 July 2026, 12:00 UTC"),
  ).toBeVisible();
});


it.each([
  ["unknown", "Unknown"],
  ["restricted", "Restricted"],
  ["unreachable", "Unreachable"],
  ["historical_archive", "Historical archive"],
])("renders %s as visible text", (state, label) => {
  render(<CatalogueStateBadge state={state} />);
  expect(screen.getByText(label)).toBeVisible();
});


it("provides keyboard accessible named tabs", async () => {
  render(<CatalogueObservatory />);
  const coverage = screen.getByRole("tab", { name: "Coverage" });
  const datasets = screen.getByRole("tab", { name: "Datasets" });
  coverage.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(datasets).toHaveFocus();
});


it("preserves the labelled synthetic demo after catalogue integration", async () => {
  render(<Home />);
  await userEvent.click(
    screen.getByRole("tab", { name: "Synthetic Demo" }),
  );
  expect(
    screen.getByText(/no live or current portal data is used/i),
  ).toBeVisible();
});


it("ignores an older dataset response after filters change", async () => {
  const first = deferredResponse();
  const second = deferredResponse();
  mockCatalogueFetches(first, second);
  render(<DatasetTable />);
  await choosePortal("nged");
  await choosePortal("ssen");
  second.resolve(SSEN_PAGE);
  expect(await screen.findByText("SSEN dataset")).toBeVisible();
  first.resolve(NGED_PAGE);
  expect(screen.queryByText("NGED stale dataset")).not.toBeInTheDocument();
});


it("aborts requests on unmount and resets detail on filter change", async () => {
  const { unmount } = render(<CatalogueObservatory />);
  await openDataset(DATASET_A);
  await choosePortal("ssen");
  expect(screen.queryByText(DATASET_A.title)).not.toBeInTheDocument();
  unmount();
  expect(lastFetchSignal().aborted).toBe(true);
});
```

Also test server pagination/filter retention, safe dataset detail, empty and
error states, and absence of zones/signals/ingested cards. The degraded-state
fixture must contain a newest complete observation that fails validation and
an older validated observation; the component must render the fixed public
validation reason and both distinct timestamps. API-client/component tests use
exact FastAPI-shaped JSON and cover initial loading, replacement requests,
unmount, stale-response suppression, and detail reset when dataset, portal, or
filters change.

- [ ] **Step 2: Verify RED**

```powershell
Push-Location frontend
try {
  npm test -- src/components/catalogue
  if ($LASTEXITCODE -eq 0) { throw "Catalogue component tests unexpectedly passed" }
} finally {
  Pop-Location
}
```

Expected: catalogue components are absent.

- [ ] **Step 3: Implement the observatory**

Recreate `PortalIntelligence` as a thin wrapper around
`CatalogueObservatory`. Coverage shows exactly seven configured portals,
refresh attempt, operational due state, last complete observation, dataset and
resource counts, and snapshot availability. When the newest complete
observation is invalid or unavailable, show its attempt time and fixed
validation state beside the older last-valid observation time; never relabel
the older evidence as current.

`page.tsx` keeps the Phase 0 research overview as the default top-level tab,
adds `Catalogue Observatory`, and keeps the persistently labelled synthetic
demo reachable as the third tab. Catalogue tabs are nested inside the
observatory and do not replace top-level product navigation.

Datasets use server pagination and filters. Dataset detail loads safe metadata,
resources, evidence, assessments, and observation identity. Unknown or missing
values display “Unknown”; the data model remains `null`.

Every catalogue request uses an `AbortController` and a monotonically
increasing request token. A filter, page, portal, dataset, or tab change aborts
the prior request, clears incompatible detail state, and applies a result only
when its token is still current. Cleanup aborts on unmount. Abort is not shown
as an error; the latest real failure remains visible. Components pass
`{ signal: controller.signal }` through the Task 4 client option and the client
forwards it unchanged to `fetch`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
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
git diff --check
if ($LASTEXITCODE -ne 0) { throw "Task 5 diff check failed" }
$taskFiles = @("frontend/src/components/catalogue/CatalogueObservatory.tsx", "frontend/src/components/catalogue/PortalCoverageGrid.tsx", "frontend/src/components/catalogue/DatasetTable.tsx", "frontend/src/components/catalogue/DatasetDetail.tsx", "frontend/src/components/catalogue/ObservationHistory.tsx", "frontend/src/components/catalogue/CatalogueStateBadge.tsx", "frontend/src/components/catalogue/CatalogueObservatory.test.tsx", "frontend/src/components/catalogue/PortalCoverageGrid.test.tsx", "frontend/src/components/catalogue/DatasetTable.test.tsx", "frontend/src/components/catalogue/DatasetDetail.test.tsx", "frontend/src/components/catalogue/ObservationHistory.test.tsx", "frontend/src/components/catalogue/CatalogueStateBadge.test.tsx", "frontend/src/components/PortalIntelligence.tsx", "frontend/src/app/page.tsx", "frontend/src/lib/api.ts", "frontend/src/lib/api.test.ts")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 5 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 5 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add catalogue observatory"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 5 commit"
```

### Task 6: Close WP1.2–WP1.3

**Files:**
- Modify: `README.md`
- Modify: `docs/data-model.md`
- Modify: `docs/public-data-sources.md`
- Inspect: all Task 1–5 files.

**Interfaces:**
- Produces: accepted catalogue API/frontend head and truthful public docs.

- [ ] **Step 1: Document the product workflow**

Document registry/snapshot path settings, GET routes, last-valid semantics,
operational review windows, failed/partial behavior, dataset reference format,
pagination, UI workflow, and the distinction between catalogue metadata and
analytical ingestion.

- [ ] **Step 2: Run full gates**

```powershell
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check .
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
$trackedGenerated = git ls-files -- data/cache data/snapshots data/curation data/exports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedGenerated) { throw "Generated evidence is tracked" }
$status = git status --porcelain
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$expected = @("README.md", "docs/data-model.md", "docs/public-data-sources.md")
if ($status | Where-Object {
  $path = $_.Substring(3)
  $expected -notcontains $path
}) { throw "Unexpected WP1.2-WP1.3 closeout change" }
```

Run `scripts/check_public_boundary.py .` from a clean tracked worktree.

- [ ] **Step 3: Obtain independent review**

The Sol-high reviewer must verify:

```text
Every portal has durable refresh state.
Failed/partial current attempts do not replace last complete.
Missing/corrupt snapshot never falls back to mutable rows or seeds.
All catalogue routes are GET-only and response-safe.
Exactly seven portals are visible.
Frontend uses only versioned catalogue routes.
Unknown and failure states are textually accessible.
```

Expected: PASS with no remaining finding.

- [ ] **Step 4: Commit documentation**

```powershell
$taskFiles = @("README.md", "docs/data-model.md", "docs/public-data-sources.md")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Catalogue closeout staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged closeout change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "docs: document catalogue observatory"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Catalogue closeout commit"
```
