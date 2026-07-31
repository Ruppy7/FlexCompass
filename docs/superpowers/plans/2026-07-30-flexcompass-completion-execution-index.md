# FlexCompass Completion Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a usable local FlexCompass research application with real
public-data workflows, transparent catalogue integration across all seven
approved portals, reproducible analysis, and a separately gated public
publication route.

**Architecture:** Delivery is split into independently reviewable plans whose
order follows the approved evidence chain: product truth, catalogue
observability, one complete SSEN outage vertical, source-specific expansion,
analysis, and release. Shared database, API, and frontend files are changed
sequentially across material branches so accepted work is integrated before a
later plan freezes its interfaces.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLite, httpx, pytest, Ruff,
Node.js 18+, Next.js 15, React 18, strict TypeScript, Vitest, Testing Library.

## Global Constraints

- Use only public Great Britain electricity-network and flexibility-market
  sources available to any user under their terms.
- Portal egress is GET-only. Never bid, dispatch, control assets, change
  accounts, or call a portal write endpoint. Public application routes never
  change stored state; explicitly labelled POST computations may analyse a
  supplied synthetic payload without persistence or portal access.
- Preserve `source_dataset_id`, source resource identity, exact safe
  `raw_record`, and immutable snapshot/evidence reference for every derived
  canonical portal record.
- Unknown prices, eligibility, dates, record counts, cadence, geography,
  lifecycle, and causal effects remain unknown.
- Generated databases, downloaded records, snapshots, caches, intermediate
  reports, and generated analyses remain untracked.
- Authentication, token, MFA, account-selection, and browser-session issues
  stop for user resolution. Agents do not operate login or account flows.
- Every Git and GitHub action uses local identity `ruppy7`,
  `71883711+Ruppy7@users.noreply.github.com`, and remote owner `Ruppy7`.
- Immediately before every `git add`, `git commit`, merge, push, or other Git
  write in this programme, run:

```powershell
$gitName = git config --local --get user.name
$gitEmail = git config --local --get user.email
$gitRemote = git remote get-url origin
if (
  $gitName -ne "ruppy7" -or
  $gitEmail -ne "71883711+Ruppy7@users.noreply.github.com" -or
  $gitRemote -notmatch "^https://github\.com/Ruppy7/FlexCompass(\.git)?$"
) {
  throw "FlexCompass Git identity or remote owner is not ruppy7"
}
```

  Stop for the user on any mismatch. This gate is repeated at each task write;
  an earlier task’s result is not reusable authorization.
- Immediately before any GitHub remote write (`push`, PR create/update/merge,
  release create/upload), run `gh api user --jq .login` and require the exact
  value `ruppy7`. On missing/failed auth or any other value, stop and return to
  the user. Never run `gh auth login`, `gh auth switch`, use a browser/device
  flow, or choose an account autonomously.
- Production implementation uses one `gpt-5.6-sol` owner per material task and
  a different `gpt-5.6-sol` reviewer. The orchestrator independently inspects
  the exact diff and runs final gates.
- Behavioural changes use RED–GREEN TDD and frequent task-scoped commits.
- Python uses type hints and PEP 8. TypeScript stays strict and React components
  remain functional.
- Do not generalise a source parser before its public schema, licence,
  attribution, access, provenance, and analytical role are verified.
- Sites is not an assumed runtime. It is evaluated only after public-safe,
  read-only aggregate outputs exist.

---

## Plan set and execution order

| Order | Plan | Programme coverage | Entry gate | Exit evidence |
|---|---|---|---|---|
| 0 | This execution index and approved design | Programme governance | Written specification approved | Plans reviewed, committed, and local continuity synchronized |
| 1 | `2026-07-30-phase-0-product-truth-safety.md` | WP0.1–WP0.5 | Plan review PASS | No default path turns synthetic, empty, stale, or unknown evidence into a verified fact |
| 2 | `2026-07-30-ssen-hv-foundation-completion.md` | WP2.1 | Phase 0 merged; existing SSEN Tasks 1–2 accepted | Real SSEN source sync, canonical query API, provenance, rejects, and final gates accepted |
| 3 | `2026-07-30-catalogue-observatory-api-frontend.md` | WP1.2–WP1.3 | Phase 0 and WP2.1 merged so database/API contracts are current | Seven real catalogue registries are exposed through a read-only API and usable frontend |
| 4 | `2026-07-30-catalogue-curation-exports.md` | WP1.4–WP1.5 | Catalogue API contracts accepted | Versioned reviewed decisions, blockers, refresh state, drift/licence/schema evidence, and public-safe exports accepted |
| 5 | `2026-07-30-ssen-outage-explorer-analysis.md` | WP2.2–WP2.4 | WP2.1 and all of Phase 1 accepted; shared API/frontend hotspots are free | A new user can bootstrap exact published SSEN source evidence, explore real events, and reproduce the curated investigation |
| 6 | One reviewed source plan per dataset family | Phase 3 and Phase 4 | Source manifest passes the evidence gate below | Accepted canonical source under the shared collector contract |
| 7 | One reviewed analysis plan per research question | Phase 5 | Required canonical sources and crosswalks accepted | Reproducible `AnalysisRun` with uncertainty and interpretation limits |
| 8 | Release and publication plan | Phase 6 | Catalogue and outage MVPs accepted | Verified local release plus a Sites decision and any approved public companion |

## Shared-file sequencing

The following files are integration hotspots:

- `backend/app/db.py`
- `backend/app/routes.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `frontend/src/app/page.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/package.json`

Only one unmerged production branch may own a material change to an integration
hotspot. A later plan is revalidated against current `main` after its
predecessor merges. Read-only research and planning may proceed in parallel.

## Task 1: Integrate the approved design and plan set

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-flexcompass-completion-programme-design.md`
- Create: `docs/superpowers/plans/2026-07-30-flexcompass-completion-execution-index.md`
- Create: `docs/superpowers/plans/2026-07-30-phase-0-product-truth-safety.md`
- Create: `docs/superpowers/plans/2026-07-30-ssen-hv-foundation-completion.md`
- Create: `docs/superpowers/plans/2026-07-30-catalogue-observatory-api-frontend.md`
- Create: `docs/superpowers/plans/2026-07-30-catalogue-curation-exports.md`
- Create: `docs/superpowers/plans/2026-07-30-ssen-outage-explorer-analysis.md`

**Interfaces:**
- Consumes: approved design commit `519daf3`.
- Produces: one reviewed, versioned plan set with exact plan dependencies and
  no production-code change.

- [ ] **Step 1: Confirm plan-file completeness**

Run:

```powershell
$required = @(
  "docs/superpowers/plans/2026-07-30-flexcompass-completion-execution-index.md",
  "docs/superpowers/plans/2026-07-30-phase-0-product-truth-safety.md",
  "docs/superpowers/plans/2026-07-30-ssen-hv-foundation-completion.md",
  "docs/superpowers/plans/2026-07-30-catalogue-observatory-api-frontend.md",
  "docs/superpowers/plans/2026-07-30-catalogue-curation-exports.md",
  "docs/superpowers/plans/2026-07-30-ssen-outage-explorer-analysis.md"
)
$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Missing plan files: $($missing -join ', ')" }
```

Expected: no output and exit code 0.

- [ ] **Step 2: Scan for plan failures**

Run:

```powershell
$patterns = @(
  ("T" + "BD"),
  ("T" + "ODO"),
  ("implement " + "later"),
  ("fill in " + "details"),
  ("appropriate error " + "handling"),
  ("write tests for " + "the above"),
  ("similar to " + "Task")
) -join "|"
$hits = Select-String -Path "docs/superpowers/plans/*.md" -Pattern $patterns -CaseSensitive:$false
if ($hits) { $hits; exit 1 }
```

Expected: no output and exit code 0.

- [ ] **Step 3: Verify public boundaries and diff hygiene**

Run:

```powershell
python scripts/check_public_boundary.py docs/superpowers
if ($LASTEXITCODE -ne 0) { throw "Public-boundary scan failed" }
git diff --check
if ($LASTEXITCODE -ne 0) { throw "Plan diff check failed" }
$status = @(git status --short)
if ($LASTEXITCODE -ne 0) { throw "Unable to read plan status" }
$status
```

Expected: the boundary scan and diff check pass; status lists only the approved
specification and plan files.

- [ ] **Step 4: Obtain independent plan review**

Review criteria:

```text
No Critical, Important, or Minor finding remains.
Every immediate plan maps each approved requirement to a task.
Every production task names exact files, interfaces, RED evidence, GREEN
evidence, verification commands, and a commit.
Later source and analysis plans are gated by evidence rather than guessed
schemas or placeholder code.
```

Expected: independent `gpt-5.6-sol` high PASS on the exact plan head.

- [ ] **Step 5: Commit the plan set**

```powershell
$planFiles = @(
  "docs/superpowers/specs/2026-07-30-flexcompass-completion-programme-design.md"
  "docs/superpowers/plans/2026-07-30-flexcompass-completion-execution-index.md"
  "docs/superpowers/plans/2026-07-30-phase-0-product-truth-safety.md"
  "docs/superpowers/plans/2026-07-30-catalogue-observatory-api-frontend.md"
  "docs/superpowers/plans/2026-07-30-catalogue-curation-exports.md"
  "docs/superpowers/plans/2026-07-30-ssen-hv-foundation-completion.md"
  "docs/superpowers/plans/2026-07-30-ssen-outage-explorer-analysis.md"
)
git add -- $planFiles
if ($LASTEXITCODE -ne 0) { throw "Plan staging failed" }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw "Unstaged plan change remains" }
$untracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate untracked files" }
if ($untracked) { throw "Unexpected untracked file: $($untracked -join ', ')" }
$staged = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate staged files" }
$delta = @(Compare-Object ($planFiles | Sort-Object) ($staged | Sort-Object))
if ($delta) { throw "Staged paths differ from exact plan scope: $delta" }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged plan diff check failed" }
git commit -m "docs: plan FlexCompass completion programme"
if ($LASTEXITCODE -ne 0) { throw "Plan commit failed" }
$status = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Unable to read post-commit status" }
if ($status) { throw "Plan commit is not clean: $($status -join ', ')" }
```

Expected: one local documentation commit under the verified `ruppy7` identity.

## Task 2: Execute each immediate plan through its own gate

**Files:**
- Read: the five detailed plan files listed in Task 1.
- Modify: only the files named by the currently active task.

**Interfaces:**
- Consumes: an exact reviewed plan and accepted predecessor head.
- Produces: one independently accepted task commit or an explicit recorded
  blocker; no task is silently skipped.

- [ ] **Step 1: Revalidate the active plan against current `main`**

```powershell
$status = git status --porcelain
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($status) { throw "Implementation worktree is not clean" }
git status --short --branch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: the chosen implementation worktree is clean and its base matches the
head recorded in `memory/CURRENT.md`.

- [ ] **Step 2: Dispatch one bounded implementation task**

Task brief must contain:

```text
Exact task number and plan file.
Exact file boundary and interfaces.
Required RED and GREEN commands.
Public/read-only, provenance, credential, and ruppy7 constraints.
Prohibition on memory/project-plan edits.
Expected commit and report.
```

Expected: one `gpt-5.6-sol` owner; no competing owner for the same change
stream.

- [ ] **Step 3: Run specification and quality review**

Review order:

```text
1. Specification compliance against the exact task.
2. Code quality, security, provenance, and regression review.
3. Same-owner rework for accepted findings.
4. Exact-head re-review.
```

Expected: a different Sol reviewer returns PASS with no remaining finding.

- [ ] **Step 4: Run orchestrator final gates**

```powershell
python -m pytest -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$trackedGenerated = git ls-files -- data/cache data/snapshots data/curation data/exports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedGenerated) { throw "Generated evidence is tracked" }
$status = git status --porcelain
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($status) { throw "Reviewed task head is not clean" }
```

For frontend tasks also run:

```powershell
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
  npm test -- --run
  if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
  Pop-Location
}
```

Expected: all applicable gates pass on the reviewed exact head and the tracked
worktree is clean.

- [ ] **Step 5: Integrate only after the task gate closes**

Integration requirements:

```text
Verified ruppy7 identity and Ruppy7 remote.
Approved exact head.
No unresolved findings.
No untracked generated or private artifacts.
Normal merge or reviewed pull request; no history rewrite.
Post-merge verification on the resulting main head.
```

Expected: the next plan starts only after the integration result is recorded in
`memory/CURRENT.md`.

## Task 3: Create a source-specific plan only after its evidence gate

**Files:**
- Create: `docs/superpowers/specs/YYYY-MM-DD-<source>-design.md`
- Create: `docs/superpowers/plans/YYYY-MM-DD-<source>-implementation.md`
- Modify: `docs/public-data-sources.md`

**Interfaces:**
- Consumes: Tier 1 catalogue evidence and a reviewed Tier 2 dataset decision.
- Produces: an approved Tier 3 source contract and executable plan; it does not
  produce analytical data before approval.

- [ ] **Step 1: Prove the source gate**

Required evidence:

```text
Stable portal, dataset, and resource identifiers.
Public read path and access mode.
Licence, attribution, and redistribution treatment.
Observed raw schema and time/geography semantics.
Request pacing, pagination or download contract.
Snapshot, raw_record, reject, and drift policy.
Named analytical role and explicit non-uses.
```

Expected: missing evidence becomes a reviewed `unknown` or `access_blocked`
decision with a next review time; no parser is guessed.

- [ ] **Step 2: Design and approve the source contract**

Expected design sections:

```text
Source identity and evidence.
Canonical mapping with nullable unknowns.
Collector and redirect boundaries.
Snapshot and provenance chain.
Reject and quality semantics.
Read-only API and product use.
Testing, attribution, and public boundary.
```

Expected: the user approves the written source specification before its
implementation plan is created.

- [ ] **Step 3: Write and review the source plan**

Expected: exact files, signatures, fixtures, RED/GREEN commands, task commits,
review gates, and no placeholder or inferred schema.

## Task 4: Gate Phase 5 analysis and Phase 6 publication

**Files:**
- Create: one design and one plan per approved analysis.
- Create: `docs/superpowers/plans/YYYY-MM-DD-local-release-and-publication.md`

**Interfaces:**
- Consumes: accepted Tier 3 sources, evidence-bearing crosswalks, and
  reproducible export contracts.
- Produces: accepted Tier 4 workflows and a deployment decision.

- [ ] **Step 1: Prove an analysis is supportable**

Required evidence:

```text
Named research question.
Accepted canonical inputs and exclusions.
Time and geography alignment.
Coverage and ambiguity treatment.
Non-causal or directional interpretation.
Reproducible AnalysisRun and naive baseline where prediction is proposed.
```

Expected: analyses without adequate inputs remain explicit unsupported
questions; they are not replaced by synthetic results.

- [ ] **Step 2: Prove the local release**

Required commands:

```powershell
python -m pytest -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_public_boundary.py .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
  npm test -- --run
  if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }
  npx tsc --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally {
  Pop-Location
}
$trackedGenerated = git ls-files -- data/cache data/snapshots data/curation data/exports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($trackedGenerated) { throw "Generated evidence is tracked" }
$status = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Unable to read release worktree status" }
if ($status) { throw "Release worktree is not clean: $($status -join ', ')" }
```

Expected: clean-install, migration, startup, health, immutable SSEN evidence
bootstrap plus offline reproduction, catalogue workflow, export reproduction,
and public-boundary evidence all pass.

- [ ] **Step 3: Decide Sites viability from evidence**

Decision record must cover:

```text
Runtime support.
Writable-state and refresh requirements.
Environment-variable and credential handling.
Licence and attribution.
Security and mutation surfaces.
Operational ownership and rollback.
```

Expected: use Sites only for a supported public-safe read-only route. Otherwise
retain the full local application and publish, at most, a static companion from
reviewed aggregate exports.
