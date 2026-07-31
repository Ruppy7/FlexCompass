# Catalogue Curation, Change Review, and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 1 by adding evidence-led dataset profiles, immutable
human decisions, a deterministic review queue, fine-grained change review, and
licence-aware reproducible public catalogue exports.

**Architecture:** Automated catalogue observations remain immutable source
evidence. Local CLI commands import reviewed profiles and record decisions as
new append-only revisions; no public route mutates them. A curation repository
joins only validated last-complete snapshots to current reviewed decisions.
GET-only API projections drive the Reviews and Changes tabs. Export policy
includes dataset-level records only when the recorded licence and access
evidence permit metadata redistribution; everything else is excluded with an
aggregate reason and never guessed.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLite migrations 9 and 10, FastAPI,
pytest, Ruff, Next.js 15, React 18, strict TypeScript, Vitest, Testing Library.

## Global Constraints

- Phase 0, WP2.1, and the Catalogue Observatory API and Frontend plan must be
  accepted and merged before execution.
- Profiles and decisions are versioned evidence, not mutable annotations on
  `catalogue_datasets`.
- Every profile and decision names an observation from a validated
  last-complete snapshot and preserves `portal_id` and `source_dataset_id`.
- Unknown licence, access, schema, cadence, geography, eligibility, and value
  remain explicit unknowns.
- A decision never authorises bidding, dispatch, portal mutation, or source-data
  redistribution.
- Profile import and decision recording are local CLI operations only. The
  `/api/v1/catalogue` router remains GET-only.
- Unsafe raw evidence is rejected atomically; canonical evidence is never
  altered to make it persistable.
- Public API and exports omit raw records, local paths, reviewer identity,
  credentials, raw errors, URL queries, and URL fragments.
- Generated exports remain ignored under `data/exports/catalogue/`.
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

### Task 1: Add immutable dataset profiles and local import

**Files:**
- Modify: `backend/app/db.py`
- Create: `backend/app/catalogue_curation_models.py`
- Create: `backend/app/catalogue_curation_store.py`
- Modify: `backend/app/catalogue_cli.py`
- Create: `backend/tests/test_catalogue_curation.py`
- Create: `backend/tests/fixtures/catalogue/profile-v1.json`

**Interfaces:**
- Produces migration 9 and:

```python
class SchemaFieldV1(BaseModel):
    name: str
    source_type: str | None = None
    nullable: bool | None = None
    description: str | None = None


class ProfileEvidenceV1(BaseModel):
    evidence_id: str = Field(min_length=1)
    portal_id: str
    source_dataset_id: str
    source_resource_id: str | None = None
    evidence_type: Literal[
        "catalogue_metadata",
        "resource_schema",
        "resource_sample",
        "publisher_documentation",
        "access_check",
        "licence_statement",
    ]
    dimension: Literal[
        "access",
        "licence",
        "schema",
        "temporal_coverage",
        "analytical_role",
        "geography",
        "granularity",
    ]
    statement: str
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    source_url: str | None = None
    source_value: Any | None = None
    metadata_redistribution: Literal[
        "permitted",
        "restricted",
        "unknown",
    ] | None = None
    access_result: Literal[
        "anonymous_public",
        "registration_required",
        "restricted",
        "unreachable",
        "unknown",
    ] | None = None
    licence_identifier: str | None = None
    attribution: str | None = None
    observed_at: datetime
    raw_record: dict[str, Any] = Field(default_factory=dict)


class DatasetProfileImportV1(BaseModel):
    schema_version: Literal[1] = 1
    profile_id: str | None = None
    portal_id: str
    source_dataset_id: str
    observation_id: str
    profiled_at: datetime
    profiler: str = Field(min_length=1)
    profile_status: Literal["complete", "partial", "blocked"]
    access_state: Literal[
        "public",
        "registered",
        "restricted",
        "unreachable",
        "unknown",
    ]
    licence_state: Literal[
        "confirmed_open",
        "metadata_only",
        "restricted",
        "not_stated",
        "unknown",
    ]
    schema_state: Literal[
        "documented",
        "observed",
        "conflicting",
        "unavailable",
        "unknown",
    ]
    temporal_state: Literal[
        "bounded",
        "open_ended",
        "not_applicable",
        "conflicting",
        "unknown",
    ]
    analytical_roles: list[Literal[
        "outage",
        "flexibility_requirement",
        "flexibility_procurement",
        "flexibility_dispatch",
        "flexibility_result",
        "planning_context",
        "geography_reference",
        "system_context",
        "other",
        "unknown",
    ]] = Field(min_length=1)
    purpose: str | None = None
    geography: str | None = None
    temporal_coverage_start: datetime | None = None
    temporal_coverage_end: datetime | None = None
    granularity: str | None = None
    access_notes: str | None = None
    licence_notes: str | None = None
    schema_fingerprint: str | None = None
    fields: list[SchemaFieldV1] = Field(default_factory=list)
    evidence: list[ProfileEvidenceV1] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class DatasetProfileV1(DatasetProfileImportV1):
    profile_id: str


class DatasetProfileReviewTemplateV1(BaseModel):
    schema_version: Literal[1] = 1
    portal_id: str
    source_dataset_id: str
    observation_id: str
    profile: DatasetProfileImportV1 | None = None


def profile_id(
    portal_id: str,
    source_dataset_id: str,
    observation_id: str,
    content_hash: str,
) -> str: ...


def import_dataset_profile(
    conn: sqlite3.Connection,
    profile: DatasetProfileImportV1,
    repository: CatalogueRepository,
) -> str: ...


def latest_dataset_profile(
    conn: sqlite3.Connection,
    dataset_key: str,
    *,
    observation_id: str | None = None,
) -> DatasetProfileV1 | None: ...
```

- [ ] **Step 1: Write failing model, migration, and atomicity tests**

```python
def test_migration_nine_adds_immutable_profiles(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    run_migrations(db_path)
    with get_connection(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(catalogue_dataset_profiles)"
            )
        }
    assert columns == {
        "profile_id",
        "dataset_key",
        "observation_id",
        "profile_version",
        "profile_json",
        "content_hash",
        "profiled_at",
        "created_at",
    }


def test_profile_must_match_last_complete_dataset(
    seeded_repository: CatalogueRepository,
) -> None:
    profile = valid_profile(source_dataset_id="not-in-snapshot")
    with pytest.raises(ValueError, match="validated last-complete snapshot"):
        import_dataset_profile(
            seeded_repository.connection,
            profile,
            seeded_repository,
        )


def test_profile_must_match_current_valid_non_degraded_observation(
    seeded_repository: CatalogueRepository,
) -> None:
    historical = valid_profile(observation_id=OLDER_COMPLETE_OBSERVATION)
    with pytest.raises(ValueError, match="current last-valid observation"):
        import_dataset_profile(
            seeded_repository.connection,
            historical,
            seeded_repository,
        )


def test_equal_time_profiles_have_total_current_order(
    seeded_repository: CatalogueRepository,
) -> None:
    first = import_profile(valid_profile(profiled_at=PROFILED_AT))
    second = import_profile(
        valid_profile(profiled_at=PROFILED_AT, purpose="revised evidence")
    )
    assert latest_dataset_profile(
        seeded_repository.connection,
        DATASET_KEY,
    ).profile_id == max(first, second)


def test_profile_rejects_duplicate_evidence_ids_atomically(
    seeded_repository: CatalogueRepository,
) -> None:
    profile = valid_profile(
        evidence=[ACCESS_EVIDENCE, ACCESS_EVIDENCE],
    )
    with pytest.raises(ValueError, match="unique evidence_id"):
        import_dataset_profile(
            seeded_repository.connection,
            profile,
            seeded_repository,
        )
    assert profile_count(seeded_repository.connection) == 0


def test_unsafe_profile_evidence_rolls_back_all_rows(
    seeded_repository: CatalogueRepository,
) -> None:
    profile = valid_profile(
        evidence=[unsafe_signed_target_evidence()]
    )
    with pytest.raises(UnsafePersistenceValueError):
        import_dataset_profile(
            seeded_repository.connection,
            profile,
            seeded_repository,
        )
    assert count_rows(
        seeded_repository.connection,
        "catalogue_dataset_profiles",
    ) == 0
```

Also test aware UTC timestamps, temporal range order, non-empty profiler,
analytical roles and evidence, state/evidence consistency, unique field names,
evidence identity parity with the profile, canonical schema fingerprint and
content hashing, ID derivation excluding the optional supplied ID, mismatched
supplied-ID rejection, idempotent re-import, conflicting same-ID rejection, and
migration rollback. Evidence IDs must be non-empty and unique within the
profile before any persistence or decision validation. `access_state="public"`
requires at least one same-dataset
`dimension="access"` evidence item with
`access_result="anonymous_public"`; every other structured result fails closed.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_curation.py -k "profile or migration_nine" -v
```

Expected: curation contracts, migration 9, and import command are absent.

- [ ] **Step 3: Append migration 9**

```sql
CREATE TABLE IF NOT EXISTS catalogue_dataset_profiles (
    profile_id      TEXT PRIMARY KEY,
    dataset_key     TEXT NOT NULL,
    observation_id  TEXT NOT NULL,
    profile_version INTEGER NOT NULL CHECK (profile_version = 1),
    profile_json    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    profiled_at     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (dataset_key, observation_id, content_hash),
    FOREIGN KEY (dataset_key) REFERENCES catalogue_datasets(dataset_key),
    FOREIGN KEY (observation_id)
        REFERENCES catalogue_observations(observation_id)
);
CREATE INDEX IF NOT EXISTS idx_catalogue_profiles_dataset_time
    ON catalogue_dataset_profiles(dataset_key, profiled_at DESC);
```

Insert schema version 9 in the same transaction.

- [ ] **Step 4: Implement exact profile validation and persistence**

Normalise a profile payload with
`profile.model_dump(mode="json", exclude={"profile_id"}, exclude_none=False)`,
canonical JSON using sorted keys and compact separators, and SHA-256. Derive
`profile_id` from that payload hash and the three source identity inputs, then
construct the persisted `DatasetProfileV1` envelope. Reject a supplied ID that
does not equal the derived ID. Before opening the insert savepoint:

1. load the named validated snapshot through `CatalogueRepository`;
2. prove it is the portal state's current `last_valid_observation_id`, the
   newest complete observation itself is valid, and the portal is not degraded;
3. prove the portal/source dataset pair exists in it;
4. prove every evidence item names that same pair;
5. call `require_exact_safe_structure()` for each complete canonical evidence
   item, including its statement, source value, source URL, and `raw_record`;
6. reject source URLs containing query strings or fragments; and
7. enforce the structured anonymous-public access evidence rule above.

Persist the exact canonical profile JSON. Re-import of the same content is
idempotent; the same ID with different content fails closed.
When multiple immutable profiles exist for one dataset/observation, the current
profile is the total maximum `(profiled_at, profile_id)` using aware UTC time
and binary profile-ID order. Every queue, default read, and decision helper
uses this one function; equal timestamps are deterministic.

- [ ] **Step 5: Add the local-only import command**

```text
python -m app.catalogue_cli profile-import PROFILE.json
    [--db-path PATH] [--snapshot-dir PATH]
```

Read one UTF-8 JSON document, validate it as `DatasetProfileImportV1`, import it, and
print only the stable profile ID. The input may omit `profile_id`; if supplied,
it is verified. Do not add a FastAPI write route.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_curation.py backend/tests/test_catalogue_repository.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/catalogue_curation_models.py backend/app/catalogue_curation_store.py backend/app/catalogue_cli.py backend/app/db.py backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/db.py", "backend/app/catalogue_curation_models.py", "backend/app/catalogue_curation_store.py", "backend/app/catalogue_cli.py", "backend/tests/test_catalogue_curation.py", "backend/tests/fixtures/catalogue/profile-v1.json")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 1 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 1 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add evidence-led catalogue profiles"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 1 commit"
```

### Task 2: Record versioned dataset decisions

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/catalogue_curation_models.py`
- Modify: `backend/app/catalogue_curation_store.py`
- Modify: `backend/app/catalogue_cli.py`
- Modify: `backend/tests/test_catalogue_curation.py`
- Create: `backend/tests/fixtures/catalogue/decision-v1.json`

**Interfaces:**
- Produces migration 10 and:

```python
class DatasetDecisionDraftV1(BaseModel):
    schema_version: Literal[1] = 1
    decision_id: str | None = None
    portal_id: str
    source_dataset_id: str
    observation_id: str
    profile_id: str | None = None
    reviewer: str | None = None
    decision: Literal[
        "use_now",
        "use_later",
        "context_only",
        "archive_only",
        "duplicate",
        "unusable",
        "access_blocked",
        "unknown",
    ]
    access_state: Literal[
        "public",
        "registered",
        "restricted",
        "unreachable",
        "unknown",
    ]
    licence_state: Literal["permitted", "restricted", "unknown"]
    review_status: Literal["proposed", "reviewed"]
    rationale: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    unresolved_questions: list[str] = Field(default_factory=list)
    decided_at: datetime
    reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    supersedes_decision_id: str | None = None


class DatasetDecisionV1(DatasetDecisionDraftV1):
    decision_id: str
    profile_id: str


class DatasetDecisionReviewTemplateV1(BaseModel):
    schema_version: Literal[1] = 1
    portal_id: str
    source_dataset_id: str
    observation_id: str
    profile_id: None = None
    decision_id: None = None
    decision: DatasetDecisionDraftV1 | None = None


def decision_id(
    portal_id: str,
    source_dataset_id: str,
    observation_id: str,
    profile_id: str,
    content_hash: str,
) -> str: ...


def record_dataset_decision(
    conn: sqlite3.Connection,
    decision: DatasetDecisionDraftV1,
) -> str: ...


def latest_dataset_decision(
    conn: sqlite3.Connection,
    dataset_key: str,
    *,
    reviewed_only: bool = False,
) -> DatasetDecisionV1 | None: ...
```

- [ ] **Step 1: Write failing decision invariants**

```python
@pytest.mark.parametrize("value", ["unknown", "access_blocked"])
def test_reviewed_uncertain_decision_requires_question_and_review_date(
    value: str,
    seeded_profile: DatasetProfileV1,
) -> None:
    decision = valid_decision(
        decision=value,
        review_status="reviewed",
        unresolved_questions=[],
        next_review_at=None,
    )
    with pytest.raises(ValueError):
        record_dataset_decision(CONN, decision)


def test_decision_evidence_must_belong_to_named_profile(
    seeded_profile: DatasetProfileV1,
) -> None:
    decision = valid_decision(evidence_ids=["evidence-from-another-dataset"])
    with pytest.raises(ValueError, match="profile evidence"):
        record_dataset_decision(CONN, decision)


def test_permitted_licence_requires_structured_redistribution_evidence(
    seeded_profile: DatasetProfileV1,
) -> None:
    decision = valid_decision(
        licence_state="permitted",
        evidence_ids=["non-licence-evidence"],
    )
    with pytest.raises(ValueError, match="licence evidence"):
        record_dataset_decision(CONN, decision)


def test_decision_cannot_upgrade_profile_access_or_licence(
    seeded_restricted_profile: DatasetProfileV1,
) -> None:
    decision = valid_decision(
        profile_id=seeded_restricted_profile.profile_id,
        access_state="public",
        licence_state="permitted",
    )
    with pytest.raises(ValueError, match="profile access"):
        record_dataset_decision(CONN, decision)


def test_new_review_supersedes_exactly_one_current_review(
    seeded_reviewed_decision: DatasetDecisionV1,
) -> None:
    before = decision_row_bytes(seeded_reviewed_decision.decision_id)
    replacement = replacement_decision(
        supersedes_decision_id=seeded_reviewed_decision.decision_id
    )
    record_dataset_decision(CONN, replacement)
    assert decision_row_bytes(seeded_reviewed_decision.decision_id) == before
    assert latest_dataset_decision(
        CONN,
        replacement_dataset_key,
        reviewed_only=True,
    ) == replacement
```

Also test canonical decision-ID derivation excluding only `decision_id`,
supplied-ID mismatch rejection, immutable revisions, aware timestamps,
`next_review_at > decided_at`,
same dataset/observation/profile identity, proposed decisions not replacing a
reviewed decision, reviewed status requiring non-empty local reviewer and
`reviewed_at`, proposed status requiring both to be null, explicit
access/licence state, one-successor enforcement, immutable predecessor bytes and
hash, supersession cycles rejected, profile/decision access and licence
consistency, and transactional rollback.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_curation.py -k "decision or migration_ten" -v
```

Expected: decision contract, persistence, and migration 10 are absent.

- [ ] **Step 3: Append migration 10**

```sql
CREATE TABLE IF NOT EXISTS catalogue_dataset_decisions (
    decision_id            TEXT PRIMARY KEY,
    dataset_key            TEXT NOT NULL,
    observation_id         TEXT NOT NULL,
    profile_id             TEXT NOT NULL,
    decision_value         TEXT NOT NULL,
    review_status          TEXT NOT NULL,
    decision_json          TEXT NOT NULL,
    content_hash           TEXT NOT NULL,
    decided_at             TEXT NOT NULL,
    next_review_at         TEXT,
    supersedes_decision_id TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (dataset_key, observation_id, content_hash),
    FOREIGN KEY (dataset_key) REFERENCES catalogue_datasets(dataset_key),
    FOREIGN KEY (observation_id)
        REFERENCES catalogue_observations(observation_id),
    FOREIGN KEY (profile_id)
        REFERENCES catalogue_dataset_profiles(profile_id),
    FOREIGN KEY (supersedes_decision_id)
        REFERENCES catalogue_dataset_decisions(decision_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalogue_decision_successor
    ON catalogue_dataset_decisions(supersedes_decision_id)
    WHERE supersedes_decision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_catalogue_decisions_dataset_time
    ON catalogue_dataset_decisions(dataset_key, decided_at DESC);
```

Insert schema version 10 in the same transaction. Never update a predecessor.
To record a replacement, prove the predecessor is the current reviewed leaf for
the same dataset and insert one successor in a savepoint. The unique successor
index prevents branching. Inside the same `BEGIN IMMEDIATE` transaction, reject
a new reviewed row without `supersedes_decision_id` when a reviewed leaf already
exists. Derive `superseded` only in read/API projections when a successor
exists, so historical JSON, columns, and hashes remain immutable.

- [ ] **Step 4: Implement decision validation and CLI**

```text
python -m app.catalogue_cli decision-record DECISION.json [--db-path PATH]
```

Validate the named profile, observation, dataset, and evidence IDs from the
database. Accept `DatasetDecisionDraftV1`, canonicalize it with `decision_id`
excluded, derive the ID from dataset/observation/profile identity plus that
content hash, construct the required `DatasetDecisionV1`, and reject a
different supplied ID. A reviewed `unknown` or `access_blocked` decision requires at least
one unresolved question and a future `next_review_at`; every reviewed decision
requires `reviewed_at` and reviewer. Print only the decision ID. Reviewer and
profiler are persisted in local audit records but omitted from public API
models and exports.

A decision may preserve or tighten the profile's access/licence conclusion but
must never upgrade it. `access_state="public"` requires the named profile's
`access_state` to be `public` and cited same-dataset access evidence whose
structured `access_result` is exactly `anonymous_public`.
`licence_state="permitted"` requires profile
`licence_state="confirmed_open"` in addition to the structured licence evidence
below. Unknown, registered, restricted, unreachable, metadata-only, not-stated,
or conflicting profile states cannot be promoted by decision prose.

A `licence_state="permitted"` decision must cite at least one evidence item
whose `dimension` is `licence`, `metadata_redistribution` is `permitted`, and
whose structured `licence_identifier` and `attribution` are non-empty. Reject
free-text-only, cross-dataset, restricted, unknown, or mismatched evidence.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_curation.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app/catalogue_curation_models.py backend/app/catalogue_curation_store.py backend/app/catalogue_cli.py backend/app/db.py backend/tests/test_catalogue_curation.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/db.py", "backend/app/catalogue_curation_models.py", "backend/app/catalogue_curation_store.py", "backend/app/catalogue_cli.py", "backend/tests/test_catalogue_curation.py", "backend/tests/fixtures/catalogue/decision-v1.json")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 2 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 2 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: record catalogue dataset decisions"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 2 commit"
```

### Task 3: Compute and expose the review queue

**Files:**
- Create: `backend/app/catalogue_review.py`
- Modify: `backend/app/catalogue_cli.py`
- Modify: `backend/app/catalogue_api_models.py`
- Modify: `backend/app/catalogue_routes.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/catalogue/ReviewQueue.tsx`
- Create: `frontend/src/components/catalogue/ReviewQueue.test.tsx`
- Modify: `frontend/src/components/catalogue/CatalogueObservatory.tsx`
- Create: `backend/tests/test_catalogue_review.py`
- Modify: `backend/tests/test_catalogue_api.py`
- Modify: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces:

```python
ReviewState = Literal[
    "unreviewed",
    "proposed",
    "reviewed",
    "blocked",
    "overdue",
]


class DatasetReviewItemV1(BaseModel):
    dataset_ref: str
    portal_id: str
    source_dataset_id: str
    title: str | None
    observation_id: str
    profile_id: str | None
    decision: str | None
    state: ReviewState
    reasons: list[str]
    next_review_at: datetime | None


def build_review_queue(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    *,
    evaluated_at: datetime,
) -> tuple[DatasetReviewItemV1, ...]: ...


class PhaseOneGateReportV1(BaseModel):
    evaluated_at: datetime
    expected_portal_ids: list[str]
    portal_states: list[PortalState]
    review_items: list[DatasetReviewItemV1]
    findings: list[str]
    ready: bool


def validate_phase_one_exit(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    *,
    evaluated_at: datetime,
) -> PhaseOneGateReportV1: ...


def write_review_batch(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    evaluated_at: datetime,
) -> Path: ...


def verify_review_batch(
    repository: CatalogueRepository,
    batch_dir: Path,
    *,
    require_finalized: bool = False,
) -> None: ...


def finalize_review_batch(
    repository: CatalogueRepository,
    batch_dir: Path,
    output_dir: Path,
) -> Path: ...


def import_finalized_review_batch(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    batch_dir: Path,
) -> tuple[int, int]: ...
```

Routes:

```text
GET /api/v1/catalogue/datasets/{dataset_ref}/profiles
GET /api/v1/catalogue/datasets/{dataset_ref}/decisions
GET /api/v1/catalogue/reviews
```

- [ ] **Step 1: Write failing state-table and API tests**

```python
@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("no_profile", "unreviewed"),
        ("profile_no_decision", "proposed"),
        ("current_review", "reviewed"),
        ("access_blocked", "blocked"),
        ("past_review_date", "overdue"),
        ("new_observation_after_review", "overdue"),
    ],
)
def test_review_queue_state_table(
    fixture_name: str,
    expected: str,
    review_repository: CatalogueRepository,
) -> None:
    item = build_review_queue(
        review_repository,
        CONN,
        evaluated_at=EVALUATED_AT,
    )[0]
    assert item.state == expected


@pytest.mark.parametrize(
    "fixture_name",
    [
        "empty_registry",
        "six_portals_only",
        "never_attempted_portal",
        "overdue_refresh",
        "corrupt_newest_complete_with_older_fallback",
        "no_valid_complete_snapshot",
    ],
)
def test_phase_one_gate_rejects_incomplete_or_degraded_portal_state(
    fixture_name: str,
    gate_repository: CatalogueRepository,
) -> None:
    report = validate_phase_one_exit(
        gate_repository,
        CONN,
        evaluated_at=EVALUATED_AT,
    )
    assert report.ready is False
    assert report.findings


def test_review_routes_are_get_only(client) -> None:
    for path in (
        "/api/v1/catalogue/reviews",
        f"/api/v1/catalogue/datasets/{DATASET_REF}/profiles",
        f"/api/v1/catalogue/datasets/{DATASET_REF}/decisions",
    ):
        assert client.post(path, json={}).status_code == 405
```

Add tests for stable priority/order, seven-portal filtering, pagination,
profile/decision history, absent dataset 404, public-field allowlists, and
empty/unavailable snapshot states. Test that `review-batch-export` fixes all
seven observation IDs and counts, creates exactly one template pair per
dataset, leaves every decision unreviewed, and writes no source raw record.
Test that `review-batch-finalize` derives each profile ID from the final
canonical profile bytes, stamps that exact ID into only its matching decision,
rejects a supplied/mismatched ID or cross-dataset pair, preserves every reviewed
field byte-for-byte except the previously null derived `profile_id` and
`decision_id`, writes a new immutable output directory rather than editing
reviewer input, and records hashes for every finalized file. Finalization must
also reject a baseline observation that is no longer the current valid
non-degraded portal observation.
Test that `import_finalized_review_batch()` re-verifies every hash and current
non-degraded observation, imports every profile and decision in one
`BEGIN IMMEDIATE` transaction, is whole-batch idempotent, and rolls back all
rows when the final pair fails.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_review.py backend/tests/test_catalogue_api.py -k "review or profile or decision" -v
```

Expected: queue and read routes are absent.

- [ ] **Step 3: Implement the deterministic queue**

Evaluate every dataset in each validated last-complete snapshot. State
precedence is:

1. `overdue` when a reviewed decision's `next_review_at <= evaluated_at`, its
   observation is no longer current, or its profile is no longer current;
2. `blocked` for a current reviewed `access_blocked` or `unknown` decision;
3. `unreviewed` when no current-observation profile exists;
4. `proposed` when a profile exists but no current reviewed decision exists;
5. `reviewed` otherwise.

Sort by state priority `overdue`, `blocked`, `unreviewed`, `proposed`,
`reviewed`, then `portal_id`, `source_dataset_id`. Reasons use stable public
phrases and never raw exception text.

“Current profile” always means the result of the Task 1
`latest_dataset_profile()` total order for the exact current observation; no
query or queue implements its own ordering.

`validate_phase_one_exit()` first requires portal states for exactly
`CATALOGUE_PORTAL_IDS`. It fails on a missing/extra portal, never-attempted or
operationally overdue refresh, unavailable last-valid snapshot, invalid newest
complete snapshot/degraded fallback, or missing valid complete observation. It
also fails when a complete portal snapshot reports zero datasets, because that
cannot demonstrate catalogue integration. It then fails on every `overdue`,
`unreviewed`, or `proposed` item and any
`blocked` item without a future `next_review_at`. An empty queue is ready only
when the gate has already failed with explicit portal findings.

The local command:

```text
python -m app.catalogue_cli review-batch-export OUTPUT_DIR
    --evaluated-at ISO-8601 [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli review-batch-verify OUTPUT_DIR
    [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli review-batch-finalize INPUT_DIR OUTPUT_DIR
    [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli review-batch-import FINALIZED_DIR
    [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli review-gate
    --evaluated-at ISO-8601 [--db-path PATH] [--snapshot-dir PATH]
```

`review-batch-export` writes an ignored baseline with exact portal observation
IDs/counts and one `DatasetProfileReviewTemplateV1` plus one
`DatasetDecisionReviewTemplateV1` per dataset. The frozen identity fields are
populated; `profile`, `decision`, `profile_id`, and `decision_id` are exactly
`null`. Empty evidence, rationale, timestamps, reviewer, and state values are
not synthesized into otherwise-valid import models. It never marks a record
reviewed or invents missing evidence. `review-gate` prints the stable
`PhaseOneGateReportV1` and exits 1 while any finding remains;
it exits 0 only when
every dataset in all seven last-complete snapshots is reviewed or is an
evidence-backed blocker with a future review time.

After human review, `review-batch-finalize` requires every template's `profile`
to be a complete `DatasetProfileImportV1` and every `decision` to be a complete
`DatasetDecisionDraftV1`; no nullable review-template field may remain.
It treats each completed import as authoritative, canonicalizes it using the
same function as `profile-import`, derives its final `profile_id`, and writes a
new finalized profile plus the matching decision with that exact ID. It changes
no evidence, status, rationale, reviewer, or timestamp.

```python
class ReviewBatchManifestEntryV1(BaseModel):
    portal_id: str
    source_dataset_id: str
    observation_id: str
    reviewed_profile_input_path: str
    reviewed_profile_input_sha256: str
    reviewed_decision_input_path: str
    reviewed_decision_input_sha256: str
    finalized_profile_path: str
    finalized_profile_sha256: str
    finalized_decision_path: str
    finalized_decision_sha256: str
    profile_id: str
    decision_id: str


class ReviewBatchManifestV1(BaseModel):
    schema_version: Literal[1] = 1
    baseline_path: Literal["baseline.json"]
    baseline_sha256: str
    entries: list[ReviewBatchManifestEntryV1]
```

Entries are sorted by `(portal_id, source_dataset_id, observation_id)` and all
paths are unique canonical forward-slash relative paths beneath the finalized
directory. Finalization copies the exact reviewed profile-template and
decision-template input bytes beneath `inputs/` before writing the derived
canonical finalized records; the two `reviewed_*_input_path` fields name those
byte-exact copies and their hashes cover all copied bytes. `manifest.json` is
UTF-8 canonical JSON with sorted keys, compact separators, and exactly one
terminal LF. It contains no self-hash. Verification parses
`ReviewBatchManifestV1`, reserializes it and requires exact byte equality, then
opens and hashes the baseline and every referenced input/output file beneath
the finalized directory. The review-manifest SHA-256 used later is the SHA-256
of these complete canonical `manifest.json` bytes, computed by the export
command after internal verification; it is not an internally trusted
self-declared value.

The manifest therefore binds the source baseline hash, every input/output hash,
dataset identity, observation ID, final profile ID, and decision ID.
Finalization fails atomically on missing,
extra, duplicate, mismatched, already-inconsistent files, a changed current
observation, or a degraded portal. The finalized directory contains an exact
byte copy of the reviewed `baseline.json` plus `manifest.json`; the latter
binds the baseline hash and every finalized profile/decision ID and file hash.
`review-batch-import` opens one `BEGIN IMMEDIATE` transaction, then re-verifies
that finalized directory and requires every baseline observation to remain the
current valid non-degraded observation inside the lock. It imports the entire
profile/decision set before commit using the same derivation functions as the
single-record commands; any failure rolls back the whole batch.

`evaluated_at` is an aware UTC gate clock, not a historical selector. Reject it
when it predates any refresh attempt, observation, profile, or decision used by
the report. The report names the exact current evidence IDs it evaluated.

- [ ] **Step 4: Add safe read projections and frontend**

Expose paginated GET routes with the Phase 1 `Page[T]` contract. Profiles omit
raw evidence, source values, and profiler identity; decisions omit reviewer
identity. Extend:

```typescript
export type CatalogueTab =
  | "coverage"
  | "datasets"
  | "reviews"
  | "changes";

export async function fetchCatalogueReviews(
  filters: CatalogueReviewFilters,
): Promise<Page<DatasetReviewItem>>;
```

`ReviewQueue` shows state, textual reasons, decision, and next review time.
Keyboard tab behavior must continue to work with four tabs.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_review.py backend/tests/test_catalogue_api.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm test -- src/lib/api.test.ts src/components/catalogue/ReviewQueue.test.tsx
  if ($LASTEXITCODE -ne 0) { throw "Review queue frontend tests failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
} finally {
  Pop-Location
}
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/catalogue_review.py", "backend/app/catalogue_cli.py", "backend/app/catalogue_api_models.py", "backend/app/catalogue_routes.py", "frontend/src/lib/types.ts", "frontend/src/lib/api.ts", "frontend/src/components/catalogue/ReviewQueue.tsx", "frontend/src/components/catalogue/ReviewQueue.test.tsx", "frontend/src/components/catalogue/CatalogueObservatory.tsx", "backend/tests/test_catalogue_review.py", "backend/tests/test_catalogue_api.py", "frontend/src/lib/api.test.ts")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 3 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 3 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add catalogue review queue"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 3 commit"
```

### Task 4: Add fine-grained snapshot and profile diffs

**Files:**
- Create: `backend/app/catalogue_diff.py`
- Modify: `backend/app/catalogue_repository.py`
- Modify: `backend/app/catalogue_api_models.py`
- Modify: `backend/app/catalogue_routes.py`
- Modify: `backend/app/catalogue_cli.py`
- Create: `backend/tests/test_catalogue_diff.py`
- Modify: `backend/tests/test_catalogue_repository.py`
- Modify: `backend/tests/test_catalogue_api.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/catalogue/ChangeReview.tsx`
- Create: `frontend/src/components/catalogue/ChangeReview.test.tsx`
- Modify: `frontend/src/components/catalogue/CatalogueObservatory.tsx`

**Interfaces:**
- Produces:

```python
DiffKind = Literal[
    "dataset_added",
    "dataset_removed",
    "dataset_metadata_changed",
    "resource_added",
    "resource_removed",
    "resource_metadata_changed",
    "access_changed",
    "licence_changed",
    "schema_changed",
    "evidence_changed",
]


class CatalogueChangeV1(BaseModel):
    change_id: str
    portal_id: str
    dataset_ref: str
    entity_kind: Literal["dataset", "resource", "schema_field", "evidence"]
    entity_id: str
    before_observation_id: str | None
    after_observation_id: str | None
    before_profile_id: str | None
    after_profile_id: str | None
    kind: DiffKind
    field: str | None
    before: str | int | bool | list[str] | None
    after: str | int | bool | list[str] | None


def diff_catalogue_observations(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    *,
    portal_id: str,
    before_observation_id: str,
    after_observation_id: str,
    before_profile_id: str | None = None,
    after_profile_id: str | None = None,
) -> tuple[CatalogueChangeV1, ...]: ...
```

Route:

```text
GET /api/v1/catalogue/diffs?portal_id=...&before=...&after=...
    [&before_profile=...&after_profile=...]
```

- [ ] **Step 1: Write failing semantic diff tests**

```python
def test_reordered_metadata_and_schema_are_not_changes() -> None:
    changes = diff_fixture("same-content-different-order")
    assert changes == ()


@pytest.mark.parametrize(
    "fixture_name,kind",
    [
        ("licence", "licence_changed"),
        ("access", "access_changed"),
        ("resource_add", "resource_added"),
        ("schema", "schema_changed"),
        ("evidence", "evidence_changed"),
    ],
)
def test_diff_classifies_material_change(
    fixture_name: str,
    kind: str,
) -> None:
    assert {item.kind for item in diff_fixture(fixture_name)} == {kind}


def test_change_ids_do_not_collide_for_two_fields_of_the_same_kind() -> None:
    changes = diff_fixture("two-metadata-fields")
    assert len(changes) == 2
    assert len({item.change_id for item in changes}) == 2


@pytest.mark.parametrize(
    "fixture_name",
    ["two-resources-same-field", "two-evidence-items-same-field"],
)
def test_change_ids_bind_the_exact_changed_entity(fixture_name: str) -> None:
    changes = diff_fixture(fixture_name)
    assert len(changes) == 2
    assert len({(item.entity_kind, item.entity_id) for item in changes}) == 2
    assert len({item.change_id for item in changes}) == 2


def test_explicit_profile_diff_does_not_drift_after_new_import() -> None:
    before = diff_fixture(
        "profile-change",
        before_profile_id=PROFILE_A,
        after_profile_id=PROFILE_B,
    )
    import_profile(NEWER_PROFILE_C)
    after = diff_fixture(
        "profile-change",
        before_profile_id=PROFILE_A,
        after_profile_id=PROFILE_B,
    )
    assert after == before
```

Also test same-portal and complete-snapshot requirements, absent profiles,
stable change IDs/order, URL query/fragment stripping, raw-record exclusion,
pagination, and GET-only API behavior. Reject one-sided, cross-dataset,
cross-observation, or unknown profile-ID pairs.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_diff.py backend/tests/test_catalogue_api.py -k "diff or change" -v
```

Expected: semantic diff module and API are absent.

- [ ] **Step 3: Implement canonical semantic comparison**

Compare immutable snapshot projections keyed by source IDs. Compare sorted
sets for tags/themes and keyed schema fields. Never diff `raw_record`,
snapshot/local paths, request metadata, or raw errors. Render URL values as
scheme/host/path only. Compute `change_id` as SHA-256 of the canonical public
portal, dataset, `entity_kind`, `entity_id`, before/after observation IDs,
explicit before/after profile IDs, kind, field, and canonical safe before/after
values. Resource IDs, schema-field names, and evidence IDs are the entity IDs;
dataset-level metadata uses the canonical dataset reference. This makes
same-field changes in two sub-entities distinct without incorporating private
or volatile data.

Load both IDs only through
`CatalogueRepository.load_complete_observation(portal_id, observation_id)`;
do not duplicate snapshot validation or accept partial/failed/cross-portal
observations. Add repository tests for arbitrary valid, corrupt, wrong-portal,
partial, failed, and unknown observation IDs.

Snapshot/resource comparison needs no profile IDs and sets both profile fields
to `None`. Access, licence, curated schema, or profile-evidence comparison is
performed only when the caller supplies both exact immutable profile IDs and
each is proven to match its named dataset/observation. Never resolve a
profile-backed diff through an implicit “latest” lookup.

The CLI command:

```text
python -m app.catalogue_cli diff-reviewed PORTAL BEFORE AFTER
    [--before-profile ID --after-profile ID]
    [--db-path PATH] [--snapshot-dir PATH]
```

prints stable JSON from the same function used by the API.

- [ ] **Step 4: Build the Changes tab**

Add typed `fetchCatalogueDiff()` and `ChangeReview`. The user selects a portal
and two available complete observations. Profile-backed comparison additionally
requires two explicit profile revisions selected from those observations.
Render change kind, dataset, entity, field, exact profile IDs when present, and
safe before/after values. Empty, unavailable, and invalid comparison states are
visible text.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/test_catalogue_diff.py backend/tests/test_catalogue_api.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm test -- src/components/catalogue/ChangeReview.test.tsx src/lib/api.test.ts
  if ($LASTEXITCODE -ne 0) { throw "Change review frontend tests failed" }
  npm run lint
  if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
} finally {
  Pop-Location
}
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/catalogue_diff.py", "backend/app/catalogue_repository.py", "backend/app/catalogue_api_models.py", "backend/app/catalogue_routes.py", "backend/app/catalogue_cli.py", "backend/tests/test_catalogue_diff.py", "backend/tests/test_catalogue_repository.py", "backend/tests/test_catalogue_api.py", "frontend/src/lib/types.ts", "frontend/src/lib/api.ts", "frontend/src/components/catalogue/ChangeReview.tsx", "frontend/src/components/catalogue/ChangeReview.test.tsx", "frontend/src/components/catalogue/CatalogueObservatory.tsx")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 4 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 4 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add catalogue change review"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 4 commit"
```

### Task 5: Produce licence-aware reproducible public exports

**Files:**
- Create: `backend/app/catalogue_export.py`
- Modify: `backend/app/catalogue_cli.py`
- Modify: `.gitignore`
- Create: `backend/tests/test_catalogue_export.py`
- Modify: `README.md`
- Modify: `docs/public-data-sources.md`
- Modify: `docs/data-model.md`

**Interfaces:**
- Produces:

```python
ExportDisposition = Literal[
    "metadata_row",
    "aggregate_only",
    "excluded",
]


class CatalogueExportManifestV1(BaseModel):
    schema_version: Literal[1] = 1
    export_id: str
    evaluated_at: datetime
    code_version: str
    baseline_sha256: str
    review_manifest_sha256: str
    observation_ids: dict[str, str]
    decision_ids: list[str]
    files: dict[str, str]
    row_count: int
    aggregate_only_count: int
    excluded_count: int
    exclusions: dict[str, int]


def build_public_catalogue_export(
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    review_manifest_path: Path,
    evaluated_at: datetime,
    code_version: str,
) -> CatalogueExportManifestV1: ...


def reproduce_public_catalogue_export(
    manifest_path: Path,
    repository: CatalogueRepository,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    code_version: str,
) -> CatalogueExportManifestV1: ...


def verify_public_catalogue_export(
    manifest_path: Path,
    output_dir: Path,
) -> None: ...


def resolve_catalogue_code_version(repo_root: Path) -> str: ...
```

- [ ] **Step 1: Write failing export-policy tests**

```python
def test_known_permissive_metadata_is_exported(tmp_path: Path) -> None:
    manifest = export_fixture(tmp_path, "cc-by-public-reviewed")
    rows = read_csv(tmp_path / "datasets.csv")
    assert rows[0]["licence_identifier"] == "CC-BY-4.0"
    assert manifest.row_count == 1


@pytest.mark.parametrize(
    ("fixture_name", "expected_disposition"),
    [
        ("unknown-licence", "aggregate_only"),
        ("restricted-access", "aggregate_only"),
        ("unusable-decision", "excluded"),
        ("unreviewed", "excluded"),
    ],
)
def test_export_fails_closed_without_redistribution_evidence(
    tmp_path: Path,
    fixture_name: str,
    expected_disposition: str,
) -> None:
    manifest = export_fixture(tmp_path, fixture_name)
    assert disposition_for(manifest, fixture_name) == expected_disposition
    assert fixture_source_id(fixture_name) not in (
        tmp_path / "datasets.csv"
    ).read_text("utf-8")
```

Also test sorted UTF-8 CSV, LF line endings, fixed columns, stable JSON,
query/fragment stripping, no raw/local/reviewer fields, SHA-256 file entries,
same-input byte identity, tampered manifest rejection, ignored output paths,
catalogue-code change rejection, and reproduction from exact
observation/decision IDs. Test `verify_public_catalogue_export()` against a
byte change, missing file, extra manifest-named file, hash mismatch, and count
or identity mismatch. Test that build fails when the baseline hash, seven
portal IDs, observation map, finalized decision IDs, or current reviewed rows
differ, including a refresh between review-gate and export.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_catalogue_export.py -v
```

Expected: export policy, manifest, and reproduction functions are absent.

- [ ] **Step 3: Implement the fail-closed export policy**

Include one dataset metadata row only when:

1. the dataset belongs to a validated complete observation named by the
   manifest;
2. its current decision is reviewed and is one of `use_now`, `use_later`,
   `context_only`, or `archive_only`;
3. the reviewed decision records `access_state="public"`; and
4. the named profile also records `access_state="public"` with cited
   same-dataset access evidence whose structured `access_result` is exactly
   `anonymous_public`; and
5. the reviewed decision records `licence_state="permitted"`, the named profile
   records `licence_state="confirmed_open"`, and both cite the
   structured same-dataset licence evidence required by Task 2, including
   metadata-redistribution permission, licence identifier, and attribution.

Unknown/restricted licence or access contributes only to aggregate counts.
`duplicate`, `unusable`, `access_blocked`, `unknown`, proposed, superseded, and
unreviewed datasets are excluded. Never infer compatibility from a title or
portal.

Write:

```text
datasets.csv
coverage.json
manifest.json
```

to a temporary sibling directory, fsync, then atomically rename. Load the
finalized review batch's `manifest.json`, validate and canonical-byte-check it,
verify every hash it declares including its linked `baseline.json` hash and
exact seven-portal observation map, then compute the SHA-256 of the complete
manifest bytes and select only the finalized decision IDs named by that review
manifest.
Never substitute a newly current observation or decision. The export manifest
fixes both `baseline_sha256` and `review_manifest_sha256`, `evaluated_at`,
observation IDs, decision IDs, file hashes, counts, exclusion reasons, and a
catalogue-code SHA-256 over
canonical relative paths and bytes for the repository, curation, diff, export,
and API-model modules.
Reproduction loads only those exact IDs and fails if any evidence, output, or
code hash differs. Documentation-only commits do not invalidate it.
`evaluated_at` must be aware UTC and at or after every included observation,
profile, and decision timestamp; it does not request a historical view.

Serialize `coverage.json` and `manifest.json` as UTF-8 canonical JSON with
sorted keys, compact separators, and exactly one terminal LF. `files` names
and hashes only `datasets.csv` and `coverage.json`; it excludes
`manifest.json` to avoid a circular hash. After those data-file hashes are
known, derive `export_id` as SHA-256 of the canonical manifest payload
excluding only `export_id`, then serialize the final manifest. Tests assert
this exact formula and byte sequence.

- [ ] **Step 4: Add local CLI commands and ignores**

```text
python -m app.catalogue_cli export-public OUTPUT_DIR
    --evaluated-at ISO-8601
    --review-manifest FINALIZED_MANIFEST.json
    [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli reproduce-export MANIFEST OUTPUT_DIR
    [--db-path PATH] [--snapshot-dir PATH]

python -m app.catalogue_cli verify-export MANIFEST OUTPUT_DIR
```

Add `/data/exports/catalogue/` and `/data/curation/catalogue/` to `.gitignore`.
CLI output is the export ID and public file hashes only. Both commands call
`resolve_catalogue_code_version()`; reproduction rejects a different
catalogue-code hash. `verify-export` performs no database access: it requires
the output manifest to be byte-identical to `MANIFEST`, rejects missing or
unexpected files, recalculates every named hash, and checks the manifest
identities and counts before returning zero.

- [ ] **Step 5: Document and run GREEN**

Document the profile/decision/review/diff/export distinction, licence gate,
aggregate-only behavior, commands, ignored paths, and manifest reproduction.

```powershell
python -m pytest backend/tests/test_catalogue_export.py backend/tests/test_catalogue_curation.py backend/tests/test_catalogue_diff.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check backend/app backend/tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py README.md
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py docs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskFiles = @("backend/app/catalogue_export.py", "backend/app/catalogue_cli.py", ".gitignore", "backend/tests/test_catalogue_export.py", "README.md", "docs/public-data-sources.md", "docs/data-model.md")
git add -- $taskFiles
if ($LASTEXITCODE -ne 0) { throw "Task 5 staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged Task 5 change remains" }
Assert-TaskCommitScope $taskFiles
git commit -m "feat: add reproducible catalogue exports"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Assert-CleanGitState "Task 5 commit"
```

### Task 6: Populate the exact seven-portal reviewed evidence set

**Files:**
- Create ignored local evidence:
  `data/curation/catalogue/<evaluated-at>/baseline.json`
- Create ignored local evidence:
  `data/curation/catalogue/<evaluated-at>/profiles/*.json`
- Create ignored local evidence:
  `data/curation/catalogue/<evaluated-at>/decisions/*.json`
- Create ignored finalized evidence:
  `data/curation/catalogue/<evaluated-at>/finalized/`
- Create ignored reproducible export evidence:
  `data/exports/catalogue/<evaluated-at>/`
- Modify ignored local database:
  `data/cache/catalogue/registry.sqlite3`
- Orchestrator modify after acceptance: `memory/CURRENT.md`
- Orchestrator modify after acceptance: `project-plan/backlog.md`

**Interfaces:**
- Consumes: the Task 1–5 commands and anonymous GET-only public catalogues.
- Produces: one frozen, reviewed local baseline covering every dataset in the
  exact valid complete observation for all seven portals.

- [ ] **Step 1: Refresh all seven portal catalogues read-only**

```powershell
$catalogueDb = "data/cache/catalogue/registry.sqlite3"
$snapshotDir = "data/snapshots/catalogues"
$reviewDir = "data/curation/catalogue"
$env:PYTHONPATH = "backend"
python -m app.catalogue_cli sync `
  --portal all `
  --db-path $catalogueDb `
  --output-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$evaluatedAt = (Get-Date).ToUniversalTime().ToString("o")
```

Expected: every `CATALOGUE_PORTAL_IDS` member has a current successful complete
attempt and a validated non-empty snapshot. A public access, rate, schema, or
availability failure is recorded and stops this Phase 1 gate; authentication or
account issues are handed to the user without browser or login actions.

- [ ] **Step 2: Freeze the exact review batch**

```powershell
$batchDir = Join-Path $reviewDir ($evaluatedAt -replace "[:.]", "-")
python -m app.catalogue_cli review-batch-export $batchDir `
  --evaluated-at $evaluatedAt `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

`baseline.json` records exactly seven portal IDs, observation IDs, content
hashes, dataset/resource counts, and template counts. Verify:

```powershell
python -m app.catalogue_cli review-batch-verify $batchDir `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: one `DatasetProfileReviewTemplateV1` and one
`DatasetDecisionReviewTemplateV1` for every frozen dataset. Only their frozen
identity fields are populated; `profile`, `decision`, `profile_id`, and
`decision_id` are null, so none is valid as a completed import or marked
reviewed.

- [ ] **Step 3: Review each portal batch against public evidence**

Assign disjoint portal batches to bounded Sol-medium evidence reviewers. Each
reviewer reads only the frozen catalogue snapshot and generally available
public metadata/documentation. For every dataset:

1. complete `DatasetProfileImportV1` with structured evidence and explicit
   unknowns;
   any public-access conclusion must use
   `access_result="anonymous_public"`;
2. choose a decision supported by cited same-dataset evidence;
3. use `access_blocked` or `unknown` when evidence is insufficient;
4. give every blocker an unresolved question and future review date;
5. set `review_status="reviewed"`, reviewer, and reviewed time only after the
   evidence has actually been checked; and
6. leave derived profile/decision IDs null; finalization stamps them from the
   reviewed canonical bytes; and
7. never probe a resource through a generic fetcher or infer licence,
   eligibility, geography, cadence, price, or analytical role.

The orchestrator samples each portal batch, resolves conflicting evidence, and
rejects templates whose observation ID no longer matches `baseline.json`.

- [ ] **Step 4: Finalize, verify, and import every reviewed pair**

```powershell
$finalDir = Join-Path $batchDir "finalized"
python -m app.catalogue_cli review-batch-finalize $batchDir $finalDir `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.catalogue_cli review-batch-verify $finalDir `
  --finalized `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.catalogue_cli review-batch-import $finalDir `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: imported profile and reviewed-decision counts equal the sum of the
seven frozen dataset counts. Every decision's profile ID equals the ID printed
in the finalized batch manifest, and every decision ID matches its canonical
final bytes. Duplicate identical whole-batch import is idempotent; any identity,
evidence, licence, timestamp, or content mismatch rolls back the whole batch.

- [ ] **Step 5: Close the real evidence gate**

```powershell
$evaluatedAt = (Get-Date).ToUniversalTime().ToString("o")
python -m app.catalogue_cli review-gate `
  --evaluated-at $evaluatedAt `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: `ready=true`, exactly seven healthy non-degraded portal states, and
no overdue, unreviewed, proposed, or invalid-blocker item. Record the local
baseline path, hashes, counts, evaluation time, and gate output.

Generate and reproduce the public-safe export from this actual curated
baseline:

```powershell
$exportDir = Join-Path "data/exports/catalogue" `
  ($evaluatedAt -replace "[:.]", "-")
$reproDir = "$exportDir-reproduced"
$reviewManifest = Join-Path $finalDir "manifest.json"
python -m app.catalogue_cli export-public $exportDir `
  --evaluated-at $evaluatedAt `
  --review-manifest $reviewManifest `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.catalogue_cli reproduce-export `
  (Join-Path $exportDir "manifest.json") $reproDir `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.catalogue_cli verify-export `
  (Join-Path $exportDir "manifest.json") $reproDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

The verifier compares every manifest-named file byte-for-byte and requires
identical hashes, row/aggregate/exclusion counts, exact seven observation IDs,
and exact imported decision IDs. Record the baseline path, finalized manifest
hash, export manifest/hash/count evidence, and gate output in
`memory/CURRENT.md` and the remaining evidence questions in
`project-plan/backlog.md`. These ignored records and the registry/snapshots are
never staged.

Verify no generated evidence became tracked:

```powershell
$trackedGenerated = git ls-files -- data/cache data/snapshots data/curation data/exports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedGenerated) { throw "Generated evidence is tracked" }
```

### Task 7: Close Phase 1 at an exact reviewed head

**Files:**
- Inspect: every Task 1–5 diff and commit plus Task 6 local evidence.
- Modify: no production file unless a finding is returned to the same owner.

**Interfaces:**
- Consumes: accepted Phase 0, WP2.1, observatory API/frontend, and Tasks 1–6.
- Produces: independently accepted Phase 1 head and reproducible evidence.

- [ ] **Step 1: Run full deterministic gates**

```powershell
$baseTemp = Join-Path $env:LOCALAPPDATA "Temp\flexcompass-catalogue-pytest"
$catalogueDb = "data/cache/catalogue/registry.sqlite3"
$snapshotDir = "data/snapshots/catalogues"
$env:PYTHONPATH = "backend"
$evaluatedAt = (Get-Date).ToUniversalTime().ToString("o")
python -m app.catalogue_cli review-gate `
  --evaluated-at $evaluatedAt `
  --db-path $catalogueDb `
  --snapshot-dir $snapshotDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q -p no:cacheprovider --basetemp $baseTemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check . --no-cache
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
if ($status) { throw "Phase 1 tracked worktree is not clean" }
```

Expected: all gates pass and tracked state is clean.
The review gate must report zero overdue, unreviewed, or proposed datasets and
zero blockers without a future review time.

- [ ] **Step 2: Verify the public boundary from a clean worktree**

Create one explicit temporary Git worktree below
`$env:LOCALAPPDATA\Temp\flexcompass-catalogue-boundary`, run:

```powershell
python scripts/check_public_boundary.py .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: pass. Remove only that verified temporary worktree through Git.

- [ ] **Step 3: Obtain independent Sol-high review**

The reviewer must verify:

```text
Profiles and decisions are immutable and observation-specific.
Unsafe evidence fails atomically without mutation.
Every last-complete dataset is reviewed or has an evidence-backed blocker and
a future review time.
The gate evidence contains exactly seven healthy non-degraded portal states,
non-empty snapshots, frozen observation IDs, and matching profile/decision
counts.
Public curation/diff routes are GET-only and response-safe.
Diffs are semantic, stable, and exclude raw records.
Unknown/restricted licence and access never produce dataset export rows.
Exports reproduce byte-identically from exact evidence IDs.
No generated database, snapshot, cache, or export is tracked.
```

Expected: PASS with no remaining Critical, Important, or Minor finding.

- [ ] **Step 4: Record the accepted head**

```powershell
$acceptedHead = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve accepted catalogue head" }
$branchStatus = git status --short --branch
if ($LASTEXITCODE -ne 0) { throw "Unable to read accepted catalogue status" }
Assert-CleanGitState "Accepted catalogue head"
$acceptedHead
$branchStatus
```

The orchestrator records the exact accepted head, verification counts, and next
source-plan gate in `memory/CURRENT.md`.
