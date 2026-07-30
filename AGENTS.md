# FlexCompass Agent Rules

## Mission

Develop FlexCompass as an independent, open-source research toolkit for public
Great Britain electricity-network and flexibility-market data. It is a data
analysis project, not a bidding, dispatch, asset-control, or commercial advice
product.

## Git identity (hard rule)

Two GitHub accounts exist: `rupesh-chand` and `ruppy7`. This is a personal
project, so every commit, remote, push, repository creation, and other Git or
GitHub action for FlexCompass must use `ruppy7`. Never use `rupesh-chand` for
this repository. Before any Git write or remote action, verify the configured
identity and remote owner; stop if they do not belong to `ruppy7`.

## Data boundary

- Use only public sources that any user can access under the source's terms.
- Never add employer data, private specifications, credentials, tunnel details,
  internal schemas, or local database exports.
- Keep generated databases, downloaded records, caches, and reports untracked.
- Preserve `source_dataset_id` and `raw_record` for derived portal records.
- Verify dataset licences and attribution before redistributing source data.
- Portal access is read-only. Never submit bids, dispatch assets, or call a
  write endpoint.

## Engineering

- Verify portal schemas against real public APIs before freezing a normaliser.
- Mark unknown fields as unknown; do not infer prices, eligibility, dates, or
  record counts.
- Scores and forecasts are heuristic and directional. Use language such as
  "worth investigating", "possible fit", "missing evidence", and
  "directional estimate".
- Python uses type hints, PEP 8, and pytest. TypeScript uses strict mode and
  functional React components.
- Add tests for behavioural changes and keep public-source documentation current.

## Orchestration

- The agent in the active Codex chat is the primary orchestrator, project
  manager, and senior architect for that session.
- Delegated work uses Codex-native subagents only. Every subagent must use model
  `gpt-5.6-sol`; select reasoning effort according to the task:
  - `low` for bounded mechanical work, targeted evidence extraction, and small
    documentation or verification tasks;
  - `medium` for normal multi-file implementation, integration, debugging, and
    independent task review;
  - `high` for architecture, security-sensitive or adversarial review, broad
    research synthesis, and final review gates.
- The orchestrator normally does not implement production code. It owns
  discovery, design, planning, decomposition, dispatch, oversight, review,
  verification, decisions, and continuity. Production-code implementation by
  the orchestrator requires explicit user direction.
- Keep one implementation owner for each material task or change stream. Use a
  different Codex subagent for independent review when work is material or high
  risk. The orchestrator independently inspects the diff and runs the final
  verification gates; a subagent report is not completion evidence.
- Every subagent inherits this file's Git identity, public-data, read-only
  portal, provenance, credential, and engineering rules. Task briefs must
  repeat the constraints most relevant to the bounded assignment.
- Orca, Cline, OpenCode, Amp, external provider wrappers, and all other agent
  runtimes are prohibited unless the user explicitly reverses this decision.
- Historical orchestration and delegation material under dated `archive/`
  directories is evidence only. It must not be treated as active instruction,
  invoked, or used to select the current execution path.

## Orchestrator memory and project records

- At the start of every primary-agent session, read `/memory/CURRENT.md` before
  broad discovery or task execution. It is the canonical live handoff: verify
  its stated Git and checkout facts, then continue from its `Next action` section.
  If it is absent or stale, reconstruct and update it before delegating work.
- The primary orchestrator maintains local continuity records under the
  Git-ignored `/memory/` directory. Each memory is a Markdown file and may be
  amended as understanding changes; it is a pointer and context layer, not a
  substitute for verified source evidence.
- Only the primary orchestrator may create, edit, rename, or delete files under
  `/memory/`. Codex subagents must not modify that directory. Relevant context
  must be supplied directly through bounded subagent task briefs.
- At the end of every substantive turn, the primary orchestrator reviews and,
  where the state changed, updates relevant `/memory/` files, `project-plan/`
  documents, decisions, backlog items, and retained task evidence.
- Before a session switch or after every material task gate, update
  `/memory/CURRENT.md` with the public commit, active branch or checkout heads,
  cleanliness, completed reviews, next task and Sol effort route, required
  context files, and any blockers. Never store credentials or runtime-scoped
  handles there.
- `/memory/` and `project-plan/` are local-only. Never stage or commit their
  contents, and do not promote them into public documentation without an
  explicit privacy, evidence, and relevance review.

## Efficiency and continuity

- Start from continuity, not rediscovery. Read `AGENTS.md`, the relevant
  `/memory/` pointers, the active implementation plan, and relevant live
  evidence before broad repository searches. Re-scan only evidence that is
  missing, stale, or needed for the current decision.
- Give each Codex subagent one bounded assignment with explicit acceptance
  criteria, file boundaries, safety constraints, and expected verification.
- Parallelise only genuinely independent read-only work or disjoint change
  streams. Keep production-code ownership singular and re-use the same owner
  for rework while that task remains active.
- Treat subagent identifiers and runtime handles as ephemeral. Preserve durable
  facts, decisions, diffs, verification results, and next actions in the
  orchestrator-owned continuity records instead.
- Batch independent read-only inspections and verification commands where that
  keeps output clear. Avoid repeating a check whose result is already current
  and recorded unless the relevant state changed.
- Close each task gate before opening the next: verify the implementation,
  obtain the required independent verdicts, resolve findings, preserve useful
  reports, and update continuity records. Record these checkpoints immediately
  so session compaction or handoff does not force reconstruction.
