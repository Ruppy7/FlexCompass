# SSEN NaFIRS HV Foundation Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete WP2.1 as one auditable, idempotent, read-only path from the
public SSEN NaFIRS HV CSV resources to canonical outage events, provenance,
rejects, local CLI sync, and a GET-only API.

**Architecture:** Accepted Tasks 1–2 and the safe parts of Task 3 remain the
baseline. A bounded persistence-safety module closes the outstanding encoded
signed-target bypass without ever mutating a canonical event’s `raw_record`.
The collector permits one exact SSEN-to-R2 download redirect, writes immutable
content blobs and resource-specific snapshot observations, versions events by
snapshot, and atomically advances the two-resource current-snapshot set. Query
routes only read an explicit snapshot set or that atomic current set.

**Tech Stack:** Python 3.11+, standard-library `csv`, `hashlib`, `json`,
`argparse`, httpx, Pydantic 2, SQLite, FastAPI, pytest, Ruff.

## Global Constraints

- Execute in the existing native worktree
  `C:/Users/rupes/Documents/FlexCompass/.worktrees/ssen-nafirs-hv-foundation`.
- Preserve accepted Tasks 1–2 at `9e0b8b4` and `8477516`.
- Do not accept Task 3 until the bounded persistence matrix passes independent
  security re-review.
- Dataset slug: `nafirs-hv-faults`; package ID
  `b0a58349-2ce6-4fa8-9238-a5564f966433`.
- Resource IDs:
  `ab32515f-76f2-421d-8034-7d5b01325a33` for SEPD and
  `673578c9-f531-41a5-a17c-0b35bc0fae4c` for SHEPD.
- Licence: CC BY 4.0 with SSEN Distribution attribution.
- Parse raw incident times day-first. Timezone and publisher cadence remain
  unknown.
- Every canonical event preserves source dataset/resource identity, snapshot
  ID, exact safe `raw_record`, parser version, and quality flags.
- Signed redirect targets and query material never enter logs, output,
  exceptions, snapshots, returned models, SQLite, or Git.
- Portal calls are GET-only. Authentication and browser state are out of scope.
- Generated CSVs, databases, snapshots, caches, and exports remain ignored.
- Use `data/cache/outages/registry.sqlite3` as the explicit outage database and
  `data/snapshots/outages` as the explicit snapshot root in every CLI, API,
  test, verification, and documentation example.
- Use the same implementation owner for Task 1 rework and a different Sol-high
  reviewer.
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

### Task 0: Rebase the plan onto accepted Phase 0 without rewriting history

**Files:**
- Read: `memory/CURRENT.md`
- Read: `docs/superpowers/specs/2026-07-30-flexcompass-completion-programme-design.md`
- Read: `project-plan/2026-07-15-ssen-nafirs-hv-foundation-implementation-plan.md`
- Modify: Git merge state only.

**Interfaces:**
- Consumes: accepted Phase 0 `main` head and clean SSEN head `f1f3f7c`.
- Produces: a normal merge commit in the SSEN branch; no rebase or history
  rewrite.

- [ ] **Step 1: Verify exact state and identity**

```powershell
$status = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Unable to read SSEN worktree status" }
if ($status) { throw "SSEN worktree is not clean: $($status -join ', ')" }
$head = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve SSEN head" }
$name = git config --local --get user.name
if ($LASTEXITCODE -ne 0) { throw "Unable to read local Git name" }
$email = git config --local --get user.email
if ($LASTEXITCODE -ne 0) { throw "Unable to read local Git email" }
$remote = git remote get-url origin
if ($LASTEXITCODE -ne 0) { throw "Unable to read origin" }
if ($name -ne "ruppy7" -or
    $email -ne "71883711+Ruppy7@users.noreply.github.com" -or
    $remote -notmatch "^https://github\.com/Ruppy7/FlexCompass(?:\.git)?$") {
  throw "FlexCompass Git identity or remote is not the required ruppy7 account"
}
$head
```

Expected: clean `feature/ssen-nafirs-hv-foundation` at the head recorded in
`memory/CURRENT.md`, identity `ruppy7` /
`71883711+Ruppy7@users.noreply.github.com`, and the `Ruppy7/FlexCompass`
origin.

- [ ] **Step 2: Merge current local main**

```powershell
git merge --no-ff main -m "Merge Phase 0 into SSEN outage foundation"
if ($LASTEXITCODE -ne 0) { throw "Phase 0 merge failed" }
```

Expected: a normal merge. Resolve by retaining the Phase 0 public API/config
boundary and the accepted `outages.py`, `ssen_nafirs.py`, `outage_store.py`,
and migration 6.

- [ ] **Step 3: Run the accepted baseline**

```powershell
python -m pytest backend/tests/test_ssen_nafirs.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "Accepted SSEN test slice failed" }
python -m pytest -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "Accepted full backend suite failed" }
python -m ruff check . --no-cache
if ($LASTEXITCODE -ne 0) { throw "Accepted Ruff gate failed" }
git diff --check
if ($LASTEXITCODE -ne 0) { throw "Accepted diff gate failed" }
Assert-CleanGitState "Post-merge SSEN baseline"
```

Expected: all accepted tests pass and the merge head is clean.

### Task 1: Close the bounded persistence-safety invariant

**Files:**
- Create: `backend/app/persistence_safety.py`
- Modify: `backend/app/outage_store.py`
- Modify: `backend/app/ssen_nafirs.py`
- Modify: `backend/tests/test_ssen_nafirs.py`

**Interfaces:**
- Produces:

```python
MAX_PERSISTED_STRING_BYTES = 64 * 1024
MAX_STRUCTURED_VALUE_BYTES = 512 * 1024
MAX_DECODE_PASSES = 8
MAX_CONTAINER_DEPTH = 32
MAX_CONTAINER_ITEMS = 10_000
UNSAFE_VALUE_SENTINEL = "[REDACTED_UNSAFE_VALUE]"


class UnsafePersistenceValueError(ValueError): ...


def sanitise_diagnostic_value(value: Any) -> Any: ...


def require_exact_safe_structure(value: Any) -> None: ...


def require_exact_safe_raw_record(
    raw_record: Mapping[str, Any],
) -> None: ...
```

- [ ] **Step 1: Write the failing depth and budget matrix**

Add helpers and tests:

```python
from urllib.parse import quote


def encoded(value: str, depth: int) -> str:
    for _ in range(depth):
        value = quote(value, safe="")
    return value


@pytest.mark.parametrize("depth", [0, 1, 4, 8])
def test_signed_detector_covers_permitted_decode_budget(depth: int) -> None:
    value = encoded(
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/x?X-Amz-Signature=secret",
        depth,
    )
    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL


def test_ninth_decoding_layer_fails_closed() -> None:
    value = encoded(
        "https://83025b28472d6aa2bf5ae59f3724aa78."
        "r2.cloudflarestorage.com/x?X-Amz-Signature=secret",
        9,
    )
    assert sanitise_diagnostic_value(value) == UNSAFE_VALUE_SENTINEL


@pytest.mark.parametrize(
    "value",
    ["95%", "95%25", "%GG", "line one\nline two"],
)
def test_benign_percent_and_multiline_values_round_trip(value: str) -> None:
    assert sanitise_diagnostic_value(value) == value


def test_event_raw_record_is_never_sanitised(valid_event) -> None:
    unsafe = valid_event.model_copy(
        update={"raw_record": {"note": "x" * (64 * 1024 + 1)}}
    )
    with pytest.raises(UnsafePersistenceValueError):
        upsert_outage_events([unsafe], db_path=TEST_DB)
```

Also add:

```text
test_encoded_signed_mapping_keys_fail_closed_at_eight_and_nine_layers
test_persistence_rejects_structured_value_over_512_kib
test_exact_safe_structure_rejects_signed_or_oversize_nested_evidence
test_persistence_rejects_oversize_mapping_key
test_persistence_rejects_depth_over_32_and_items_over_10000
test_persistence_rejects_cycles_and_non_json_values
test_unsafe_event_raw_record_becomes_stable_row_reject
test_mixed_safe_and_unsafe_rows_complete_with_one_reject
test_budget_failures_leave_no_partial_run_state
test_completed_failed_reject_and_returned_results_share_the_same_boundary
```

Each test must assert the unsafe marker and original secret are absent from the
returned model, SQLite dump, warnings, errors, and reject JSON.

- [ ] **Step 2: Run RED and retain the exploit evidence**

```powershell
python -m pytest backend/tests/test_ssen_nafirs.py -k "signed or persistence or raw_record or budget or percent" -q -p no:cacheprovider
```

Expected: the four/eight/nine-layer and size-budget cases fail; the four-layer
target can still cross current persistence.

- [ ] **Step 3: Implement bounded detection**

In `persistence_safety.py`, use detection-only decoding:

```python
def _decoded_layers(value: str) -> tuple[list[str], bool]:
    layers = [value]
    current = value
    for _ in range(MAX_DECODE_PASSES):
        decoded = unquote(current)
        if decoded == current:
            return layers, False
        layers.append(decoded)
        current = decoded
    return layers, unquote(current) != current
```

Reject or redact when any inspected layer contains the exact R2 hostname,
`x-amz-` query material, or a mapping key that case-folds to `signed_url` or
`redirect_url`. Measure UTF-8 leaf bytes before decoding. Measure structured
values using bounded canonical JSON; stop once 512 KiB is exceeded. Never log
or include the unsafe value in an exception.

Count mapping keys against the 64 KiB leaf limit. Reject/redact at depth 33,
after 10,000 aggregate container items, on cycles, or on non-JSON-compatible
values before calling `json.dumps`. Traversal is iterative or otherwise
provably bounded and does not build an unbounded intermediate representation.

`sanitise_diagnostic_value()` returns the fixed sentinel for an unsafe leaf or
structured value, then applies Package 1 `redact()` to safe output.

`require_exact_safe_structure()` applies the same bounded detector but raises
without returning or mutating the value whenever exact preservation is unsafe.
`require_exact_safe_raw_record()` delegates to it and raises
`UnsafePersistenceValueError("raw record is unsafe for persistence")` if
sanitisation would change the record. It returns `None` and does not mutate the
mapping when safe.

- [ ] **Step 4: Apply one persistence boundary everywhere**

In `_event_values()`:

```python
require_exact_safe_raw_record(event.raw_record)
raw_json = json.dumps(
    event.raw_record,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

Use `sanitise_diagnostic_value()` for run warnings, failure state, rejects, and
returned `SyncResult`. In `iter_ssen_hv_csv()`, call
`require_exact_safe_raw_record(raw_record)` before yielding each event and
convert `UnsafePersistenceValueError` to:

```python
OutageRowError(
    code="unsafe_raw_record",
    message="raw outage row is unsafe for persistence",
    raw_record=sanitise_diagnostic_value(raw_record),
)
```

Canonical events retain their original exact safe row; unsafe rows become
rejects while later safe rows continue. `_event_values()` repeats the exact
check as defense in depth; a direct unsafe store call fails the transaction.

- [ ] **Step 5: Run GREEN and security review**

```powershell
python -m pytest backend/tests/test_ssen_nafirs.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/persistence_safety.py backend/app/outage_store.py backend/app/ssen_nafirs.py backend/tests/test_ssen_nafirs.py --no-cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: all pass.

Independent Sol-high review must probe literal, default-port, mixed-case,
malformed, zero/one/four/eight/nine layer, oversized, nested, completed,
failed, reject, returned-result, SQLite-dump, and exact-raw-record surfaces.

- [ ] **Step 6: Commit accepted Task 3**

```powershell
$taskFiles = @("backend/app/persistence_safety.py", "backend/app/outage_store.py", "backend/app/ssen_nafirs.py", "backend/tests/test_ssen_nafirs.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 1 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 1 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "fix: bound outage persistence sanitization"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 1 commit"
```

### Task 2: Implement the exact read-only collector and local CLI

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/config.py`
- Create: `backend/app/outage_source.py`
- Modify: `backend/app/outages.py`
- Modify: `backend/app/ssen_nafirs.py`
- Modify: `backend/app/outage_store.py`
- Create: `backend/app/outage_cli.py`
- Modify: `backend/tests/test_ssen_nafirs.py`
- Create: `data/sources/ssen-nafirs-hv.json`
- Create: `data/sources/evidence/ssen-nafirs-hv-licence.json`
- Modify: `.gitignore`

**Interfaces:**
- Produces:

```python
PARSER_VERSION = "ssen-nafirs-hv-v1"
CANONICAL_EVENT_SCHEMA_VERSION = 1
SOURCE_MAX_RESPONSE_BYTES = 134_217_728
SOURCE_CONNECT_TIMEOUT_SECONDS = 10
SOURCE_READ_TIMEOUT_SECONDS = 60
SOURCE_TOTAL_DEADLINE_SECONDS = 180


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


def source_snapshot_id(source_resource_id: str, content_sha256: str) -> str: ...


def outage_reject_id(
    snapshot_id: str,
    row_number: int,
    reason_code: str,
    safe_detail_sha256: str,
) -> str: ...


class OutageEvidenceScopeV1(BaseModel):
    snapshot_ids: tuple[str, ...]
    source_resource_ids: tuple[str, ...]
    resolution: Literal["current_atomic_set", "explicit_snapshot_set"]


class OutageFetchAttemptPublicV1(BaseModel):
    attempt_id: str
    run_id: str
    source_resource_id: str
    attempted_at: datetime
    status: Literal["completed", "failed"]
    response_status: int | None
    source_modified_at: datetime | None
    source_snapshot_id: str | None
    content_sha256: str | None
    byte_size: int | None
    error_code: str | None


class SsenFetchManifestV1(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_contract_version: Literal["ssen-nafirs-hv-v1"]
    attempted_at: datetime
    attempts: tuple[OutageFetchAttemptPublicV1, ...]


def download_ssen_hv_resource(
    client: httpx.Client,
    resource: SourceResource,
) -> bytes: ...


def sync_ssen_nafirs_hv(
    *,
    db_path: Path | None = None,
    snapshot_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> SyncResult: ...


def list_ingestion_run_snapshots(
    run_id: str,
    *,
    db_path: Path | None = None,
) -> list[SourceSnapshot]: ...


def build_ssen_fetch_manifest(
    run_id: str,
    *,
    db_path: Path | None = None,
) -> SsenFetchManifestV1: ...


def current_outage_snapshot_ids(
    *,
    licence_area: LicenceArea | None = None,
    db_path: Path | None = None,
) -> tuple[str, ...]: ...


def resolve_outage_evidence_scope(
    *,
    source_snapshot_ids: Sequence[str] | None = None,
    licence_area: LicenceArea | None = None,
    db_path: Path | None = None,
) -> OutageEvidenceScopeV1: ...


def list_outage_event_versions(
    snapshot_ids: Sequence[str],
    *,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[OutageEvent]: ...


def main(argv: Sequence[str] | None = None) -> int: ...
```

- [ ] **Step 1: Write failing redirect, atomicity, and CLI tests**

```python
def test_download_accepts_only_exact_one_hop_r2_redirect() -> None:
    client = FakeClient(
        [
            response(
                302,
                headers={
                    "location": (
                        "https://83025b28472d6aa2bf5ae59f3724aa78."
                        "r2.cloudflarestorage.com/dx-sse-prod/resources/"
                        f"{SEPD_RESOURCE_ID}/sample.csv?X-Amz-Signature=secret"
                    )
                },
            ),
            response(200, content=b"A,B\n1,2\n", content_type="text/csv"),
        ]
    )
    assert download_ssen_hv_resource(client, sepd_resource()) == b"A,B\n1,2\n"
    assert [request.method for request in client.requests] == ["GET", "GET"]


@pytest.mark.parametrize(
    "location",
    [
        "http://83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com/x",
        "https://127.0.0.1/x",
        "https://example.test/x",
        "/relative",
    ],
)
def test_download_rejects_unapproved_redirects(location: str) -> None:
    with pytest.raises(SourceContractError):
        download_ssen_hv_resource(
            FakeClient([response(302, headers={"location": location})]),
            sepd_resource(),
        )
```

Add:

```text
test_download_rejects_second_redirect_without_following
test_download_stream_size_boundaries_at_limit_minus_one_limit_and_plus_one
test_download_rejects_oversize_content_length_before_streaming
test_download_uses_exact_connect_and_read_timeouts
test_download_enforces_total_deadline_across_redirects_and_slow_chunks
test_sync_records_two_snapshots_events_and_rejects_atomically
test_reject_versions_are_snapshot_scoped_and_stable_across_identical_fetches
test_bootstrap_reparse_recreates_exact_reject_ids_and_hashes
test_migration_seven_adds_immutable_snapshot_version_tables
test_migration_seven_backfills_legacy_rows_without_inventing_current_state
test_completed_run_persists_exact_snapshot_associations
test_sync_reuses_identical_content_without_rewriting_snapshot
test_same_content_in_two_resources_has_distinct_source_snapshot_ids
test_snapshot_reuse_validates_every_immutable_field
test_snapshot_reuse_ignores_later_fetch_and_source_modified_times
test_changed_parser_or_canonical_schema_cannot_overwrite_v1_materialization
test_unavailable_legacy_blob_becomes_available_only_after_hash_verification
test_repeated_fetch_records_attempt_without_mutating_snapshot
test_fetch_manifest_is_complete_safe_and_contains_no_request_query
test_changed_event_is_versioned_in_both_old_and_new_snapshots
test_removed_event_disappears_from_current_but_remains_in_old_snapshot
test_old_manifest_snapshot_set_replays_after_later_sync
test_current_snapshot_pointer_advances_for_both_resources_atomically
test_sync_cleans_first_snapshot_when_second_download_fails
test_sync_cleans_new_files_but_preserves_preexisting_snapshot
test_sync_persistence_failure_leaves_only_one_failed_run
test_sync_signed_target_never_crosses_output_log_file_or_sqlite
test_source_manifest_matches_exact_reviewed_contract
test_source_manifest_explicitly_permits_attributed_source_byte_redistribution
test_source_manifest_binds_exact_licence_evidence_hash_and_observation
test_source_manifest_verifies_hash_addressed_licence_evidence_artifact
test_outage_cli_exposes_only_local_sync
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_ssen_nafirs.py -k "download or sync or cli or migration or snapshot or version or manifest" -q -p no:cacheprovider
```

Expected: collector and CLI imports are absent.

- [ ] **Step 3: Implement one-hop download**

Use `follow_redirects=False`, the manifest's exact connect/read timeouts, and
one monotonic `SOURCE_TOTAL_DEADLINE_SECONDS` deadline that starts before the
first request and covers the redirect plus every streamed chunk.
Accept exactly one `302` from the stable SSEN
resource URL to HTTPS host
`83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com`, optional port
443, and path:

```text
/dx-sse-prod/resources/{expected-resource-id}/{filename}
```

Require final `200` and `text/csv`. Pass signed location only to the second
GET; never return or persist it. Stream the body, reject a declared
`Content-Length` above `134_217_728` before reading, and abort as soon as the
stream exceeds that same bound even when length is absent or false. Never use
an unbounded `.content` read. Abort when the monotonic deadline is reached even
if each individual chunk arrives within the read timeout. Fake-clock tests
cover deadline minus one tick, exact deadline, and deadline plus one tick.
All failures use constant messages plus `safe_error()`.

- [ ] **Step 4: Implement content-addressed sync**

Add `outage_db_path` and `outage_snapshot_dir` to `FlexCompassConfig`, default
`data/cache/outages/registry.sqlite3` and `data/snapshots/outages`.

Append forward-only migration 7. Keep migration 6 byte-for-byte unchanged and
leave its tables as read-only legacy evidence after the migration:

```sql
CREATE TABLE IF NOT EXISTS outage_content_blobs (
    content_sha256       TEXT PRIMARY KEY,
    byte_size            INTEGER NOT NULL,
    relative_snapshot_path TEXT,
    available            INTEGER NOT NULL CHECK (available IN (0, 1))
);
CREATE TABLE IF NOT EXISTS outage_source_observations (
    snapshot_id           TEXT PRIMARY KEY,
    source_dataset_id     TEXT NOT NULL,
    package_id            TEXT NOT NULL,
    source_resource_id    TEXT NOT NULL,
    licence_area          TEXT NOT NULL,
    stable_source_url     TEXT NOT NULL,
    content_sha256        TEXT NOT NULL,
    row_count             INTEGER NOT NULL,
    observed_columns_json TEXT NOT NULL,
    licence_id            TEXT NOT NULL,
    licence_title         TEXT NOT NULL,
    licence_url           TEXT NOT NULL,
    attribution           TEXT NOT NULL,
    parser_version        TEXT NOT NULL,
    source_contract_version TEXT NOT NULL,
    canonical_event_schema_version INTEGER NOT NULL,
    FOREIGN KEY (content_sha256)
        REFERENCES outage_content_blobs(content_sha256)
);
CREATE TABLE IF NOT EXISTS outage_event_versions (
    snapshot_id                    TEXT NOT NULL,
    event_id                       TEXT NOT NULL,
    source_resource_id             TEXT NOT NULL,
    licence_area                   TEXT NOT NULL,
    incident_started_local         TEXT NOT NULL,
    reporting_year                 INTEGER NOT NULL,
    voltage_kv                     REAL,
    district_short_code            TEXT NOT NULL,
    equipment_code                 TEXT,
    cause_code                     TEXT,
    customers_affected             INTEGER,
    customer_minutes_lost          INTEGER,
    average_minutes_off_supply     REAL,
    quality_flags_json             TEXT NOT NULL,
    event_json                     TEXT NOT NULL,
    event_sha256                   TEXT NOT NULL,
    canonical_event_schema_version INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, event_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS outage_reject_versions (
    snapshot_id       TEXT NOT NULL,
    reject_id         TEXT NOT NULL,
    source_resource_id TEXT NOT NULL,
    row_number        INTEGER NOT NULL,
    reason_code       TEXT NOT NULL,
    safe_detail_json  TEXT NOT NULL,
    reject_sha256     TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, reject_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS current_outage_snapshots (
    source_resource_id  TEXT PRIMARY KEY,
    snapshot_id         TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id),
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id)
);
CREATE TABLE IF NOT EXISTS ingestion_run_snapshots (
    run_id      TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    PRIMARY KEY (run_id, snapshot_id),
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
CREATE TABLE IF NOT EXISTS outage_fetch_attempts (
    attempt_id         TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    source_resource_id TEXT NOT NULL,
    attempted_at       TEXT NOT NULL,
    status             TEXT NOT NULL,
    response_status    INTEGER,
    source_modified_at TEXT,
    snapshot_id        TEXT,
    content_sha256     TEXT,
    byte_size          INTEGER,
    error_code         TEXT,
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES outage_source_observations(snapshot_id)
);
```

Add indexes for `(source_resource_id, content_sha256)`, every projected event
filter, `(event_id, snapshot_id)`, `(snapshot_id, row_number)` rejects,
run/snapshot lookup, and fetch attempts.
Insert schema version 7 in the same transaction.

The Python migration step copies each legacy `source_snapshots` row into an
immutable observation whose ID is
`ssen-nafirs-hv:{source_resource_id}:sha256:{content_sha256}`, copies each
remaining legacy `outage_events` row into the matching
`outage_event_versions` snapshot, and verifies canonical hashes. It does not
invent current pointers: migration-6 event upserts may already have lost older
versions, so current state remains unavailable until one new two-resource sync
commits. Legacy run-scoped rejects are not promoted unless their exact
resource/snapshot association is provable; otherwise the historical
materialization's reject count remains unavailable until a verified reparse.
Fetch time and publisher-modified time are attempt evidence, not
content identity; migrate them into `outage_fetch_attempts` only where the
legacy run/resource association proves them, otherwise leave them unknown
rather than inventing a value. Because migration 6 stored
environment-specific paths, backfilled
legacy blobs are always marked `available=0` with no path; never infer retained
bytes, trust an old absolute path, or fail startup merely because ignored legacy
bytes are absent. A later verified sync or evidence bootstrap creates an
available canonical blob without mutating the historical observation.
Migration rollback and repeat tests prove this boundary.

`commit_ingestion_run()` inserts immutable blobs, observations, event versions,
snapshot-scoped reject versions, run associations, and fetch attempts, then
advances both
`current_outage_snapshots` rows in the same transaction. A source observation
is never updated. Reuse performs a byte-for-byte comparison of every immutable
field and fails on any mismatch. Immutable observation identity includes only
the stable source contract, source/resource identity, exact content hash,
parser version, canonical event schema version, licence/attribution, observed
columns, and derived row count. `attempted_at`, response status, and
`source_modified_at` live only in fetch attempts. A repeated fetch therefore
records a new attempt and run association without mutating or falsely
invalidating the observation. A failed two-resource run leaves the prior
two-resource current set unchanged.

Rejects are immutable materialization evidence, not ingestion-run diagnostics.
Canonicalize each bounded safe reject detail, derive its SHA-256 and
`outage_reject_id()` from snapshot, source row number, fixed reason code, and
detail hash, and compare the entire reject set when reusing a snapshot.
Operational run warnings remain run-scoped but never enter analytical hashes.

Phase 2 freezes parser `ssen-nafirs-hv-v1` and canonical event schema version 1
for this materialization table. A parser or canonical-schema change for
identical source bytes must fail closed instead of overwriting or reinterpreting
the v1 snapshot; supporting a later materialization requires an explicit
forward migration and versioned storage design.

Content identity and byte size are immutable. Local availability is operational
state: the only allowed blob update is `available=0` with no path to
`available=1` with the canonical root-relative path after the bytes themselves
have passed SHA-256 and size verification. No reverse transition or path/hash/
size rewrite is permitted.

For each resource:

```python
digest = hashlib.sha256(content).hexdigest()
path = (
    snapshot_dir
    / "blobs"
    / digest[:2]
    / f"{digest}.csv"
)
```

The blob table stores only this validated root-relative path, never an absolute
local path. Write atomically, build
`SourceSnapshot(snapshot_id=source_snapshot_id(resource_id, digest), ...)` with
the stable SSEN URL only, parse both resources, and call
`commit_ingestion_run()` once. The content blob may be shared; source
observations and event versions are resource-specific. On failure, remove only
new files from this attempt, preserve pre-existing identical snapshots and the
previous current pointer set, and record one sanitised failed run plus one safe
fetch-attempt row per attempted resource.

Replace migration-6 event upsert/query use with the versioned repository path.
Keep compatibility functions only as explicit migration helpers; application
sync, API, analysis, and export code must not write or query `outage_events` or
`source_snapshots`. `resolve_outage_evidence_scope()` accepts either an
explicit validated snapshot set or the current set. A current set is valid only
when it contains the exact expected resource IDs and both pointers name the
same completed run; otherwise it reports unavailable rather than mixing runs.

Load and validate `data/sources/ssen-nafirs-hv.json` before any request. It is
the reviewed contract for the exact dataset/package/resource IDs, stable GET
URLs, one-hop redirect allowlist, CC BY 4.0 licence and attribution,
historical-HV analytical role, non-uses, unknown timezone, and unknown cadence.
It must explicitly record
`source_byte_redistribution="permitted_with_attribution"` based on the reviewed
CC BY 4.0 source evidence. The tracked
`data/sources/evidence/ssen-nafirs-hv-licence.json` is exactly a
`SourceLicenceEvidenceArtifactV1`: UTF-8 canonical JSON with sorted keys,
compact separators, exactly one terminal LF, and no self-hash field.
`source_resource_ids` is the two exact manifest resource IDs in lexicographic
order. `evidence_artifact_sha256` is computed over all those artifact bytes.

`SourceLicenceEvidenceV1` embeds that same exact safe reviewed evidence rather
than only its conclusion, then adds the artifact path/hash and
`evidence_sha256`. Its URL is stripped to scheme/host/path, `observed_at` is
aware UTC, its dataset/package/resource IDs must equal the source manifest, and
`evidence_sha256` is recomputed from canonical JSON excluding only
`evidence_sha256`. The observation ID and content hash therefore bind the exact
public catalogue/licence evidence reviewed for these resources without a
self-reference. Recompute the artifact hash, verify exact byte equality between
the artifact fields and their embedded counterparts, verify its
dataset/package/resource/licence title/ID/URL and attribution against the
retained observation during acceptance, and include that hash-addressed
artifact in the later bootstrap bundle. Validate all
nested values and equality with the manifest licence/attribution before
downloading or bundling. Do not duplicate those values as a second mutable
in-code manifest.

- [ ] **Step 5: Implement the CLI**

The parser accepts:

```text
python -m app.outage_cli sync ssen-nafirs-hv
  [--db-path data/cache/outages/registry.sqlite3]
  [--snapshot-dir data/snapshots/outages]
```

It prints a redacted JSON `SyncResult`, returns 0 for completed, 2 for completed
with rejects/partial, and 1 for failed. It has no portal-write command.

Add to `.gitignore`:

```gitignore
/data/raw/
/data/exports/
```

Keep the existing snapshot/database ignores.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_ssen_nafirs.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:PYTHONPATH = "backend"
python -m app.outage_cli --help
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/db.py backend/app/config.py backend/app/outage_source.py backend/app/outages.py backend/app/outage_store.py backend/app/outage_cli.py backend/app/ssen_nafirs.py backend/tests/test_ssen_nafirs.py --no-cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/db.py", "backend/app/config.py", "backend/app/outage_source.py", "backend/app/outages.py", "backend/app/outage_store.py", "backend/app/ssen_nafirs.py", "backend/app/outage_cli.py", "backend/tests/test_ssen_nafirs.py", "data/sources/ssen-nafirs-hv.json", "data/sources/evidence/ssen-nafirs-hv-licence.json", ".gitignore")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 2 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 2 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add SSEN outage sync command"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 2 commit"
```

Expected: all commands pass and the commit contains no generated snapshot.

### Task 3: Expose the accepted outage store through GET-only routes

**Files:**
- Modify: `backend/app/routes.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_outage_api.py`

**Interfaces:**
- Produces:

```python
class OutageEventPageV1(BaseModel):
    items: list[OutageEvent]
    total: int
    limit: int
    offset: int
    evidence_scope: OutageEvidenceScopeV1


class OutageSummaryResponseV1(BaseModel):
    summary: OutageSummary
    evidence_scope: OutageEvidenceScopeV1
```

```text
GET /api/v1/outages/events
GET /api/v1/outages/summary
GET /api/v1/outages/events/{event_id}
GET /api/v1/outages/snapshots
```

List filters remain `licence_area`, `district_short_code`, `reporting_year`,
`cause_code`, and repeatable `source_snapshot_id`, with limit 1–1000 and offset
>=0. `reporting_year` is an exact-value compatibility field and
`source_snapshot_id` is the canonical repeatable singular wire name; the
explorer plan extends the same query model with ranges and defines conflict
rules without silently dropping either accepted parameter. Omitted snapshots
resolve the atomic current set before event filters.

- [ ] **Step 1: Write failing API tests against a temporary DB**

```python
def test_outage_list_uses_seeded_temporary_database(client, seeded_db) -> None:
    response = client.get("/api/v1/outages/events?licence_area=SEPD&limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["licence_area"] == "SEPD"


def test_outage_detail_exposes_exact_safe_provenance(client, seeded_event) -> None:
    payload = client.get(
        f"/api/v1/outages/events/{seeded_event.event_id}",
        params={"source_snapshot_id": seeded_event.source_snapshot_id},
    ).json()
    assert payload["raw_record"] == seeded_event.raw_record
    assert payload["source_snapshot_id"] == seeded_event.source_snapshot_id


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/outages/events",
        "/api/v1/outages/summary",
        "/api/v1/outages/events/event-1",
        "/api/v1/outages/snapshots",
    ],
)
def test_outage_routes_are_read_only(client, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 405
```

Event detail requires one `source_snapshot_id`; event identity alone is not a
version identity. Also test summary unknown totals, 404 detail, snapshot public
projection, filter
parity, year bounds 1900–2100, pagination bounds, explicit old-snapshot replay
after a later sync, removed events absent from current, an empty current set as
 503/unavailable, zero-result filters retaining their resolved snapshot scope,
 every non-GET method absent from OpenAPI, and that tests never read the default
user database. All unversioned `/api/outages*` and `/api/outage-snapshots`
aliases return 410 with a stable migration message; they never retain divergent
query logic.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_outage_api.py -v -p no:cacheprovider
```

Expected: GET routes return 404.

- [ ] **Step 3: Add explicit route functions**

Register static routes before `/events/{event_id}`. During app lifespan, migrate
the configured `outage_db_path` independently of the app and catalogue
databases. Tests inject all paths. Inject the explicit outage DB path and call
only accepted `outage_store` query functions. Resolve
`OutageEvidenceScopeV1` before applying event filters. Return:

```python
{
    "items": events,
    "total": count,
    "limit": limit,
    "offset": offset,
    "evidence_scope": evidence_scope,
}
```

Return `SourceSnapshotPublic`, never `local_snapshot_path` or a redirect URL.
Map unknown event to 404 and invalid filters to 422 without raw exception text.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_outage_api.py backend/tests/test_ssen_nafirs.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/routes.py backend/app/main.py backend/tests/test_outage_api.py --no-cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/routes.py", "backend/app/main.py", "backend/tests/test_outage_api.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 3 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 3 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: expose read-only outage evidence API"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 3 commit"
```

### Task 4: Publish exact source and operating documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/data-model.md`
- Modify: `docs/public-data-sources.md`
- Modify: `.env.example`
- Create: `backend/tests/test_ssen_documentation.py`

**Interfaces:**
- Produces: public documentation for the exact accepted SSEN workflow.

- [ ] **Step 1: Write the failing documentation contract**

```python
def test_ssen_docs_include_identity_licence_and_caveats() -> None:
    text = (
        Path("README.md").read_text("utf-8")
        + Path("docs/public-data-sources.md").read_text("utf-8")
        + Path("docs/data-model.md").read_text("utf-8")
    )
    required = (
        "nafirs-hv-faults",
        "b0a58349-2ce6-4fa8-9238-a5564f966433",
        "ab32515f-76f2-421d-8034-7d5b01325a33",
        "673578c9-f531-41a5-a17c-0b35bc0fae4c",
        "Creative Commons Attribution 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        "day-first",
        "timezone is unknown",
    )
    assert all(value in text for value in required)
    assert "SSEN_DATAPORTAL_TOKEN=" not in Path(".env.example").read_text("utf-8")
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_ssen_documentation.py -v
```

Expected: current documents do not describe the complete workflow and the
example environment advertises an unnecessary SSEN token.

- [ ] **Step 3: Write verified documentation**

Document package/resource identity, SSEN Distribution attribution, CC BY 4.0,
raw CSV authority, the reviewed tracked source manifest, observed DataStore
day/month defect, SEPD/SHEPD schema differences, unknown timezone/cadence,
stable origin only, immutable resource-specific snapshot/event versioning,
atomic current-set semantics, explicit local ignored paths, sync/API commands,
rejects/quality flags, and the limitation that events are aggregate incidents
rather than household histories or flexibility-causality evidence. Remove
`SSEN_DATAPORTAL_TOKEN` from `.env.example`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_ssen_documentation.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py README.md
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py docs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("README.md", "docs/public-data-sources.md", "docs/data-model.md", ".env.example", "backend/tests/test_ssen_documentation.py")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 4 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 4 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "docs: document SSEN outage evidence workflow"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 4 commit"
```

### Task 5: Close WP2.1 with exact-head verification

**Files:**
- Inspect: every Task 1–4 diff and commit.
- Modify: no production file unless review returns a finding to the same owner.

**Interfaces:**
- Consumes: Tasks 1–4 exact head.
- Produces: independently accepted WP2.1 head.

- [ ] **Step 1: Run full deterministic gates**

```powershell
$baseTemp = Join-Path $env:LOCALAPPDATA "Temp\flexcompass-ssen-pytest"
$env:PYTHONPATH = "backend"
python -m pytest backend/tests/test_ssen_nafirs.py backend/tests/test_outage_api.py backend/tests/test_ssen_documentation.py -q -p no:cacheprovider --basetemp $baseTemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q -p no:cacheprovider --basetemp $baseTemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check . --no-cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.outage_cli --help
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
  Pop-Location
}
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$trackedGenerated = git ls-files -- data/cache data/snapshots data/raw data/exports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedGenerated) { throw "Generated outage evidence is tracked" }
$status = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Unable to read WP2.1 worktree status" }
if ($status) { throw "WP2.1 tracked worktree is not clean: $($status -join ', ')" }
```

Expected: all gates pass and the tracked worktree is clean.

- [ ] **Step 2: Run public-boundary verification from a clean tracked tree**

Create a temporary clean worktree at an explicit child of
`$env:LOCALAPPDATA\Temp`, run:

```powershell
python scripts/check_public_boundary.py .
```

Expected: pass. Remove only that verified temporary worktree through Git after
recording the result; do not touch the active SSEN worktree’s ignored local
files.

- [ ] **Step 3: Obtain final independent reviews**

Specification review must confirm exact source/licence/schema contracts,
GET-only behavior, and every WP2.1 deliverable. Security/quality review must
cover:

```text
0/1/4/8/9 encoding depth.
64 KiB and 512 KiB budgets.
Exact-safe raw_record rejection rather than mutation.
Snapshot cleanup and atomic rollback.
Immutable event versions, removed-event current semantics, and old-snapshot replay.
Resource-specific snapshot identity and immutable reuse validation.
Signed URL absence from output, logs, returns, files and SQLite.
CC BY attribution and unknown timezone/cadence.
No generated tracked artifacts.
```

Expected: both reviews PASS with no remaining Critical, Important, or Minor
finding.

- [ ] **Step 4: Record the accepted head**

```powershell
$acceptedHead = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve accepted WP2.1 head" }
$branchStatus = git status --short --branch
if ($LASTEXITCODE -ne 0) { throw "Unable to read accepted WP2.1 status" }
Assert-CleanGitState "Accepted WP2.1 head"
$acceptedHead
$branchStatus
```

Expected: exact accepted head and clean branch are recorded in
`memory/CURRENT.md` by the orchestrator.
