# FlexCompass Completion Programme Design

Date: 2026-07-30
Status: approved written specification

## 1. Purpose

FlexCompass will become a usable, independent, open-source research toolkit for
public Great Britain electricity-network and flexibility-market data. Its
primary audience is a technical energy or data researcher who wants to inspect,
compare, and reproduce findings from difficult public portal data. A secondary
audience can use the read-only interface and exported analyses without operating
the ingestion pipelines.

The completed toolkit must provide real, evidence-backed workflows even where
some portal datasets cannot be deeply ingested. Complete integration therefore
means transparent coverage, decisions, and blockers across all seven portal
catalogues, not indiscriminate copying of every resource.

FlexCompass remains a research toolkit. It does not bid, dispatch, control
assets, determine eligibility, predict guaranteed revenue, or provide
commercial advice.

## 2. Success definition

FlexCompass is complete enough for a stable public release when:

1. NGED, SP Energy Networks, SP Electricity North West, SSEN, UK Power
   Networks, Northern Powergrid, and NESO are visible through one evidence-backed
   catalogue observatory.
2. Every portal has a refresh attempt within its configured review window. A
   successful attempt supplies the current complete snapshot; a failed attempt
   exposes the failed observation and timestamp of the last valid snapshot.
   Every dataset in that last valid complete snapshot has either a reviewed
   ingestion decision or an explicit evidence-backed blocker.
3. At least one end-to-end real-data workflow lets a new user fetch public data,
   query canonical records, inspect provenance, and reproduce a published
   analysis. The first workflow is SSEN historical HV outages.
4. Additional deep-ingestion sources use the same source-contract, snapshot,
   provenance, reject, and reproducibility rules.
5. User-facing outputs distinguish verified facts, publisher claims,
   classifications, assumptions, unknowns, synthetic examples, and directional
   research.
6. A local release starts through documented commands, passes automated release
   gates, and does not require credentials for its default verified workflow.
7. Publicly hosted material, if delivered, contains only licence-reviewed,
   public-safe, read-only exports. The full stateful application remains local
   unless a later hosting gate proves an operationally safe server-side route.

## 3. Product principles

### 3.1 Evidence before breadth

A source is not analytically integrated merely because its metadata or raw
records can be downloaded. A complete analytical path contains:

```text
reviewed public source
    -> immutable local snapshot and fetch manifest
    -> strict source-specific normalisation
    -> canonical record plus rejects and quality flags
    -> read-only query API
    -> provenance-aware workflow
    -> reproducible export or analysis
```

Finishing this chain for a useful source takes priority over adding disconnected
adapters.

### 3.2 Unknown remains unknown

FlexCompass must not infer missing prices, eligibility, dates, record counts,
cadence, lifecycle, geography, asset reality, or causal effects. A missing fact
is represented as missing evidence with a reason and observation time.

### 3.3 Complete catalogue coverage, selective deep ingestion

Every portal receives catalogue-level coverage. Deep ingestion is deliberately
selective and requires a source-specific approval gate. Restricted or unclear
datasets remain visible with their blocker rather than disappearing from the
product.

### 3.4 Provenance is a user feature

Every derived canonical portal record preserves its `source_dataset_id`, source
resource identifier, exact safe `raw_record`, and immutable snapshot/evidence
reference. Observation time, snapshot hash, parser version, and quality status
remain available from analytical output back to source evidence. A reference
supplements `raw_record`; it never replaces it.

### 3.5 Local-first delivery

The default product is a reproducible local research application using Python,
FastAPI, SQLite, and Next.js. Local-first is a deliberate fit for public-data
downloads, ignored snapshots, writable research state, and reproducible
analysis. It is not a temporary excuse for an unusable setup.

### 3.6 Public and read-only boundary

Portal interaction is limited to approved public read paths. FlexCompass never
submits bids, dispatches assets, changes accounts, or calls portal write
endpoints. Credentials, private specifications, employer data, downloaded
records, generated databases, caches, and reports do not enter Git.

## 4. Integration model

Integration is measured in four tiers.

### Tier 1: catalogue integration

The portal is configured through a verified public catalogue API. FlexCompass
can take a complete paginated snapshot, preserve raw metadata, classify
evidence, compare observations, and report partial failures without erasing the
last valid state.

All seven portals must meet Tier 1.

### Tier 2: reviewed dataset decision

Each discovered dataset has a time-stamped decision:

- `use_now`
- `use_later`
- `context_only`
- `archive_only`
- `duplicate`
- `unusable`
- `access_blocked`
- `unknown`

The decision is a versioned record containing portal and source dataset
identity, decision, rationale, evidence references, licence state, access
state, review state (`proposed`, `reviewed`, or `superseded`), review time,
reviewer identifier, unresolved question, and next review time. A dataset meets
Tier 2 only when its current decision is `reviewed`. An `unknown` or
`access_blocked` decision can close review only when it records the explicit
evidence-backed blocker, unresolved question, and next review time.
Comprehensive curation proceeds continuously; it does not block a source that
independently passes the deep-ingestion gate.

### Tier 3: analytical integration

A selected dataset has:

- a reviewed source manifest and licence/attribution record;
- a verified public read contract;
- immutable snapshots and redacted fetch evidence;
- strict source-specific parsing;
- canonical records with `source_dataset_id`, source resource identifier, exact
  safe `raw_record`, and an immutable snapshot/evidence reference;
- explicit rejects and quality flags;
- idempotence, schema-drift, security, and provenance tests;
- read-only API access and reproducible export.

### Tier 4: product integration

Accepted canonical data supports a documented user workflow with source
coverage, limitations, provenance drill-through, uncertainty, and a
reproducible analysis or export.

User-facing analysis may use only Tier 3 sources. Catalogue and access analysis
may use Tier 1 and Tier 2 evidence while clearly identifying those tiers.

## 5. Target architecture

### 5.1 Source governance and contracts

Each selected analytical dataset receives a small, explicit source manifest
that defines:

- portal, dataset, and resource identifiers;
- publisher and attribution;
- licence evidence and redistribution constraints, bound to the exact reviewed
  public evidence URL, observation identity/time, and immutable evidence hash;
- anonymous or registered read mode without credential values;
- expected content type, schema, time interpretation, and geography;
- approved request rate, timeouts, redirect limits, and explicit
  pagination/download byte bounds;
- snapshot and retention policy;
- analytical role and known limitations.

Catalogue discovery can suggest a source. It cannot approve the manifest.

### 5.2 Catalogue intelligence plane

The existing seven-portal registry remains the authoritative metadata plane.
It owns catalogue observations, datasets, resources, evidence,
classifications, reviewed decisions, diffs, and review queues.

The application will expose this registry through read-only, paginated API
routes. The frontend will use those routes instead of legacy seed records.

### 5.3 Dataset collectors

Collectors are source-specific adapters behind shared interfaces. A collector:

1. validates its manifest and output location;
2. performs bounded, read-only requests;
3. refuses unexpected redirects or content;
4. records a redacted fetch manifest;
5. writes an immutable local snapshot;
6. invokes the source parser;
7. commits canonical records, rejects, and the run result atomically.

One generic portal ingester must not guess schemas across unrelated datasets.
Shared HTTP, hashing, redaction, snapshot, and run-state utilities remain
reusable.

### 5.4 Canonical evidence stores

SQLite remains the default state store. Canonical domains remain distinct:

- catalogue observations and reviewed dataset decisions;
- ingestion sources, snapshots, runs, rejects, and quality flags;
- outage events;
- flexibility requirements, tenders, procurement, dispatch, and results;
- network geography and evidence-bearing crosswalks;
- NESO contextual series;
- analysis runs and export manifests.

The application can use one configured database while keeping domain
repositories and migrations explicit. Generated databases remain ignored.
DuckDB or Parquet is introduced only when verified volume or analytical
performance demonstrates a need.

### 5.5 Geospatial resolution

Postcode, DSO, licence area, flexibility zone, substation, GSP, and geometry
resolution form an independent service. Every match reports its method,
evidence source, time validity where relevant, and confidence. Ambiguous or
unmatched records remain available; they are never forced into a geography.

### 5.6 Analysis services

Analysis is implemented as tested library functions over accepted canonical
records. Each analysis exposes:

- filters and parameters;
- input source and snapshot identifiers;
- coverage and excluded records;
- assumptions and unresolved evidence;
- output tables or chart data;
- analysis code version;
- an exportable manifest.

Initial services are catalogue health, historical outage exploration, and
outage data-quality analysis. Flexibility and cross-domain services follow only
after their inputs pass Tier 3.

### 5.7 Read-only application API

The public application API provides versioned, paginated query routes for
catalogue, outage, flexibility, geography, provenance, summaries, comparisons,
and exports. Query routes do not start ingestion.

Sync and administrative commands remain local CLI operations. If an operational
control surface is later required, it runs separately from the public API,
requires explicit local authorization, and is not exposed by default.

### 5.8 User experience

The frontend becomes one coherent research application with:

1. source coverage and portal health;
2. searchable catalogue and reviewed decision evidence;
3. historical outage explorer and provenance detail;
4. flexibility observatory when real sources are accepted;
5. explicit coverage gaps and comparison semantics;
6. reproducible CSV/JSON exports and analysis manifests.

Synthetic portfolio examples remain available only in a clearly separated
demonstration area until real canonical signals and evidence-backed user inputs
support that workflow.

### 5.9 Operations and release

The repository will provide:

- a supported baseline of Python 3.11 or newer and Node.js 18 or newer;
- deterministic environment and database setup;
- one-command or one-script local startup;
- source-specific sync commands;
- health and data-status commands;
- backend, frontend, contract, security, and public-boundary tests;
- CI on supported Python and Node versions;
- release notes and migration checks;
- reproducible public-safe export generation.

### 5.10 Verified starting point

The programme begins from the following verified capability boundary:

| Area | Starting state |
|---|---|
| Seven-portal catalogue | Backend registry, snapshots, classification, diffs, review queue, persistence, CLI, and offline tests are complete |
| Catalogue product workflow | The registry is not exposed through the application API or frontend |
| SSEN HV outages | Source models and strict parser are accepted; persistence exists but has an unresolved nested-encoding redaction invariant; collector, API, frontend, and export remain incomplete |
| Other analytical ingestion | Legacy raw landing modules exist but are not accepted end-to-end canonical sources |
| Portfolio analysis | Heuristic engine exists over synthetic inputs and empty canonical signal seeds; it is demonstration-only |
| Geography | Tested resolution utilities exist but are not connected to a verified product workflow |
| Delivery | Local FastAPI and Next.js shells run separately; CI, frontend tests, one-command release, and hosting configuration do not yet exist |

This table is a capability baseline, not a permanent status dashboard. Live
task and checkout state remains in the local orchestrator handoff.

## 6. Programme structure

The active hierarchy is:

```text
programme
    -> phase
        -> work package
            -> implementation task
                -> RED test, minimal change, GREEN verification, review, commit
```

“Package 1” remains only as the historical name of the completed catalogue
registry foundation. New work uses the work-package identifiers below.

## 7. Phase 0 — Product truth and safety

Goal: ensure the existing application never presents synthetic, empty, legacy,
or unknown data as verified portal evidence.

### WP0.1 Rebaseline the project

- Replace overlapping phase/package language with this programme hierarchy.
- Update current capability, architecture, backlog, source, and status
  documentation.
- Record completed catalogue foundation and active SSEN state accurately.

### WP0.2 Remove unsafe inference

- Remove unknown-to-fact normaliser defaults.
- Add validation boundaries for analytical inputs and regional totals.
- Make unavailable evidence nullable and visible.

### WP0.3 Separate synthetic workflows

- Move synthetic portfolio examples away from the default real-data workflow.
- Label every synthetic input, result, and report.
- Prevent synthetic status text from implying live portal coverage.

### WP0.4 Separate queries from mutations

- Remove browser-triggered portal ingestion and drift mutations from the public
  API.
- Retain explicit local CLI sync commands.
- Harden exception redaction and local CORS defaults.

### WP0.5 Consolidate source configuration

- Make verified seven-portal catalogue configuration authoritative.
- Remove or migrate stale portal endpoints and duplicate configuration.
- Ensure analytical source manifests refer to the same stable portal IDs.

Exit gate: no default screen, route, report, configuration, or model converts
empty, synthetic, stale, or unknown evidence into a current portal fact.

## 8. Phase 1 — Seven-portal catalogue observatory

Goal: turn the completed metadata foundation into the first immediately useful
cross-portal product workflow.

### WP1.1 Registry foundation — complete

The seven-portal adapters, evidence models, SQLite registry, classifications,
snapshots, diffs, review queue, redaction, and offline verification already
exist and are the baseline for this phase.

### WP1.2 Read-only catalogue API

- Add paginated portal, dataset, resource, observation, assessment, evidence,
  diff, and review-state routes.
- Report observation completeness, partial failures, and last valid state.
- Keep raw sensitive request material outside responses.

### WP1.3 Catalogue frontend

- Replace legacy catalogue seeds with the real registry.
- Provide portal coverage, filters, dataset/resource detail, evidence,
  classifications, access/licence state, and observation history.
- Make unknown, restricted, unreachable, archival, and superseded states
  visually distinct.

### WP1.4 Progressive profiling and curation

- Profile datasets where catalogue metadata cannot establish access, licence,
  schema, temporal coverage, or analytical role.
- Add a versioned reviewed dataset-decision record containing portal and source
  dataset identity, decision, rationale, evidence references, licence/access
  state, review state/time/reviewer, unresolved question, and next review time.
- Record reviewed decisions and explicit evidence-backed blockers without
  requiring all datasets to be resolved before approved deep-ingestion work
  begins.
- Preserve ambiguous and conflicting evidence.

### WP1.5 Drift, licence, and public-safe exports

- Report catalogue, resource, access, licence, and schema changes.
- Export reproducible portal coverage and review-state summaries.
- Publish only metadata and aggregate evidence that passes the public boundary.

Exit gate: all seven portals are visibly integrated; each dataset in each
portal’s last valid complete snapshot has a reviewed decision or an explicit
evidence-backed blocker with a next review time; failed current refresh attempts
and last-valid timestamps are visible; the API and UI do not substitute legacy
seed records for the registry.

## 9. Phase 2 — SSEN historical-outage MVP

Goal: deliver the first complete real-data research workflow.

### WP2.1 Complete the SSEN HV foundation

- Retain accepted source models, verified CC BY 4.0 fixtures, strict SEPD/SHEPD
  schemas, fail-closed discovery, and day-first parsing.
- Resolve the outstanding persistence-redaction invariant with a bounded,
  fail-closed sanitizer: at most 64 KiB per persisted string leaf, 512 KiB per
  structured value, and eight percent-decoding/normalisation passes. If a
  budget is exceeded, or another valid percent-decoding transform remains
  after pass eight, redact the entire unsafe diagnostic value. If preserving a
  canonical record would require altering its `raw_record`, reject that record
  instead.
- Test literal signed material; encoded signed targets and keys at one, four,
  eight, and nine layers; malformed percent sequences; ordinary percentages;
  multiline warnings; per-string oversize input; and aggregate-budget
  exhaustion.
- Complete collector, snapshot, atomic persistence, reject, CLI, read-only API,
  attribution, and verification tasks.

### WP2.2 Historical outage explorer

- Filter by licence area, reporting period, voltage, equipment, cause, customer
  impact, quality status, and source snapshot. The NaFIRS extract does not
  provide an event-end timestamp or event duration, so the explorer exposes
  duration as an unsupported evidence gap. It never substitutes the aggregate
  `average_minutes_off_supply` field.
- Provide time trends, cause/equipment breakdowns, impact distributions,
  coverage, reject counts, and data-quality warnings.
- Drill from summaries to event and raw-row provenance.

### WP2.3 Reproducible export

- Export filtered canonical events and summaries as CSV and JSON.
- Generate an analysis manifest containing filters, source/resource IDs,
  snapshot hashes, schema/parser versions, exclusions, and code version.
- Re-run a manifest against the same retained snapshot to reproduce the result.
- Publish the exact licence-reviewed source bytes used by the first
  investigation as a hash-addressed release asset outside Git, and provide a
  GET-only bootstrap command that verifies the bundle before local import. A
  mutable upstream source is not sufficient evidence for new-user
  reproduction.

### WP2.4 First public investigation

- Publish one reproducible SEPD/SHEPD historical-outage investigation.
- Use descriptive, non-causal language.
- State coverage, data-quality limitations, rejected rows, and publisher
  attribution.

Exit gate: a new user can execute the documented local workflow, query real SSEN
events, inspect their source evidence, and reproduce the published result.

## 10. Phase 3 — GB outage coverage

Goal: add comparable outage evidence without erasing differences between
operators or datasets.

### WP3.1 Shared outage collector contract

- Extract reusable download, snapshot, run, reject, provenance, and query
  contracts from the accepted SSEN implementation.
- Keep source-specific parsers and semantics isolated.

### WP3.2 SSEN LV

- Verify source, licence, schema, time, geography, and quality contracts.
- Add LV records without weakening HV invariants.

### WP3.3 Prospective NGED and Northern Powergrid history

- Snapshot verified anonymous live-outage feeds on a documented cadence.
- Report that history begins with FlexCompass observation rather than implying
  publisher-provided retrospective coverage.

### WP3.4 Gated SPEN, ENWL, and UKPN sources

- Add historical sources only after the user has resolved any required public
  account access and dataset-specific terms.
- Authentication issues stop at a user handoff; agents do not inspect browser
  sessions, initiate login, switch accounts, or create alternate access paths.

### WP3.5 Comparison semantics

- Define operator-specific event, incident, interruption, customer, duration,
  planned/unplanned, voltage, and geography meanings.
- Compare only measures whose definitions and coverage support comparison.
- Display unmatched fields and coverage gaps.

Exit gate: every added source passes licence, schema, idempotence, drift,
provenance, and definition-comparability gates.

## 11. Phase 4 — Flexibility and NESO context

Goal: deliver evidence-backed flexibility-market exploration without inferring
commercial outcomes.

### WP4.1 Canonical flexibility activity

Define distinct records for requirements, tenders, procurement, dispatch,
results, and publisher-declared status. Preserve real, test, decoy, cancelled,
and unknown classifications where supplied; never invent them.

### WP4.2 Anonymous DSO sources

Prioritise verified anonymous public sources from SSEN, NGED, Northern
Powergrid, and any accessible SP Electricity North West subset.

### WP4.3 Access-gated DSO sources

Add SPEN, SP Electricity North West, or UKPN datasets requiring generally
available accounts only after the user confirms access and applicable terms.
Credentials remain local and outside prompts, logs, snapshots, and Git.

### WP4.4 NESO context

Add selected DFS, demand, reserve, constraint, and pathway datasets through
source-specific manifests and documented pacing. NESO records provide national
context; they are not DSO outage labels or evidence of local procurement.

### WP4.5 Flexibility observatory

Expose requirements, procurement, dispatch/results, source states, time
coverage, geography evidence, and unmatched records. Do not infer price,
eligibility, asset suitability, or causal effect where publishers do not supply
the evidence.

Exit gate: the observatory uses accepted canonical records, keeps activity types
separate, exposes missing evidence, and supports reproducible exports.

## 12. Phase 5 — Geography and analysis

Goal: build valuable cross-domain research on explicit evidence and
reproducibility.

### WP5.1 Evidence-bearing crosswalks

Create time-aware postcode, licence-area, network-zone, substation, GSP, local
authority, and published flexibility-geography mappings where public evidence
supports them. Preserve method, version, ambiguity, and unmatched state.

### WP5.2 Descriptive outage–flex overlap

Explore temporal and geographic co-occurrence only where source definitions and
crosswalks permit it. Results must distinguish co-occurrence and correlation
from causation.

### WP5.3 Planning context

Add selected DFES, headroom, constraint, reinforcement, or connection evidence
through source-specific gates. Planning publications remain contextual and
retain scenario/version identity.

### WP5.4 Directional procurement research

Attempt forecasting only after a stable historical label, time-aware
train/test split, naive baseline, leakage review, and policy-regime analysis
exist. Results use phrases such as “worth investigating”, “possible fit”,
“missing evidence”, and “directional estimate”.

Exit gate: every analysis has an `AnalysisRun`, reproducible inputs and outputs,
coverage and uncertainty statements, and an appropriate non-causal or
directional interpretation.

## 13. Phase 6 — Delivery and hosting

Goal: make the toolkit reliable to install, operate, verify, and share.

### WP6.1 Unified application

Provide coherent navigation across catalogue, outage, flexibility, geography,
analysis, provenance, data status, and exports. Remove or clearly retire legacy
routes and views after their replacements are verified.

### WP6.2 Local release

- Pin and document supported Python and Node versions.
- Provide deterministic installation, migrations, startup, sync, and health
  checks.
- Supply a small verified public workflow that does not require portal
  credentials.
- Add CI, frontend tests, accessibility checks, backend tests, source-contract
  fixtures, security tests, public-boundary scans, and release verification.

### WP6.3 Sites feasibility gate

Assess ChatGPT Sites after the application can generate reviewed, public-safe
read-only outputs. The gate must confirm supported runtime, writable-state
needs, data refresh, environment variables, licence/attribution, security, and
operational ownership before any deployment.

### WP6.4 Publication route

If stateful FastAPI, SQLite, and sync are unsuitable for Sites, publish a static
read-only companion generated from reproducible aggregate exports. The full
application remains local. A public interactive backend is deferred until its
security and operating model are independently justified.

Exit gate: a new user can start and verify the local product from documented
commands; any public companion is generated from reviewed public-safe evidence
and contains no mutation or credential surface.

## 14. Dependency and delivery order

```text
Phase 0 truth and safety
        |
        +--> Phase 1 catalogue API/UI --> immediate seven-portal value
        |
        +--> source-manifest gate
                    |
                    v
             Phase 2 SSEN outage MVP
                    |
             shared collector contract
                    |
        +-----------+-----------+
        v                       v
Phase 3 GB outages       Phase 4 flexibility/NESO
        +-----------+-----------+
                    v
          Phase 5 geography/analysis
                    |
                    v
          Phase 6 release/hosting
```

Phase 0 closes before public-facing feature expansion. Phase 1 and Phase 2 may
then progress as separate change streams, with one implementation owner per
material task. Phase 2 completes before generalising the outage collector.
Phase 5 depends on accepted canonical inputs from Phases 3 and 4. Local release
engineering begins incrementally in each phase; Phase 6 is the final integration
and publication gate.

The active SSEN branch resumes inside WP2.1. Its unresolved persistence
invariant is the first implementation gate after the written specification and
plans are approved.

## 15. Error handling and uncertainty

FlexCompass distinguishes:

- portal outage or rate limiting;
- authentication rejection;
- resource removal or replacement;
- incomplete pagination;
- unexpected redirect or content type;
- malformed metadata or analytical records;
- licence or attribution uncertainty;
- schema and semantic drift;
- unknown cadence or coverage;
- classification conflict;
- partial analysis coverage.

A failed portal does not erase the last valid observation or prevent unrelated
portals from completing. A failed analytical run commits no partial canonical
state. Rejects retain safe evidence and reason codes. Persisted URLs, errors,
warnings, manifests, and raw payloads pass the same redaction boundary.

API and UI responses report observation time, source coverage, partial status,
and unknowns. They do not return raw exception text or sensitive request
material.

## 16. Security, privacy, and licensing

- All portal calls are read-only and limited to approved public source paths.
- Redirects fail closed unless a source contract safely handles a verified
  download flow.
- Secrets never appear in URLs, prompts, logs, fixtures, snapshots, database
  state, reports, or Git.
- Authentication and account-state problems are handed to the user. Agents do
  not operate login flows or browser sessions.
- Every public export passes licence, attribution, provenance, aggregation, and
  public-boundary review.
- Third-party data is not relicensed by the repository’s MIT licence.
- Generated source data, snapshots, databases, caches, intermediate reports,
  and generated analyses remain untracked. Deliberately curated documentation
  or aggregate analysis artifacts may be committed only after licence,
  attribution, provenance, and public-boundary review.

## 17. Verification and review model

Every behavioural task follows strict RED–GREEN test-driven development:

1. write a failing behavioural or contract test;
2. run it and confirm the expected failure;
3. implement the smallest change that satisfies the test;
4. run focused tests and static checks;
5. run the relevant subsystem suite;
6. obtain independent review;
7. resolve findings with the same implementation owner;
8. run orchestrator-controlled final gates on the exact head;
9. update public documentation and local continuity records.

Material tasks use a `gpt-5.6-sol` implementation owner and a different
`gpt-5.6-sol` reviewer. Reasoning effort is low for bounded mechanical work,
medium for normal implementation and integration, and high for architecture,
security, adversarial review, and final gates.

Release gates include:

- backend unit, integration, contract, idempotence, drift, and security tests;
- Ruff;
- TypeScript strict checking, frontend unit/component tests, accessibility
  checks, and production build;
- GET-only portal-egress, absence of state-changing public application routes,
  and credential-redaction verification; labelled non-persistent POST analysis
  of supplied synthetic payloads remains permitted;
- public-boundary scan;
- migration and clean-install verification;
- reproducible export comparison;
- clean tracked state and reviewed documentation.

Opt-in live source smoke tests supplement but do not replace deterministic
offline fixtures.

## 18. Planning decomposition

This programme is intentionally larger than one implementation plan. After this
specification is approved in written form, implementation planning will be
split into independently testable plans:

1. Phase 0 product truth and safety.
2. Phase 1 catalogue API and frontend.
3. Phase 1 progressive curation and exports.
4. Phase 2 SSEN foundation completion.
5. Phase 2 explorer and reproducible analysis.
6. One source plan per Phase 3 or Phase 4 dataset family.
7. One analysis plan per Phase 5 research question.
8. Phase 6 release engineering and hosting feasibility.

Each plan identifies exact files, interfaces, test cases, commands, expected
failures and passes, review gates, dependencies, and commits. A work package
does not enter implementation until its source evidence and predecessor gates
are current.

## 19. Explicit non-goals

The completion programme does not include:

- mirroring every public portal resource;
- bypassing registration, access controls, rate limits, or portal terms;
- accepting private or employer data;
- dispatch, bidding, subscription, account, or asset-control functions;
- guaranteed eligibility, revenue, reliability, or procurement predictions;
- causal outage claims from simple temporal or geographic overlap;
- forced cross-portal comparability;
- a public stateful deployment before security, licensing, persistence, refresh,
  and operational ownership pass an independent gate.

## 20. Governing decisions

This specification supersedes older active phase/package naming where the two
conflict. The catalogue foundation remains completed historical Package 1.
Existing source-specific accepted work remains valid unless this specification
introduces a stricter safety or product-integration gate.

The default route is:

1. local-first integrated research application;
2. real SSEN historical-outage use case;
3. visible seven-portal catalogue evidence;
4. selective source-by-source expansion;
5. reproducible descriptive and directional analysis;
6. optional static public companion when public-safe exports are viable.
