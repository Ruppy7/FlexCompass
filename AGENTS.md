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

- The primary agent acts as project manager, orchestrator, and senior architect.
  Material implementation, research, and independent review should be delegated
  through Orca-managed worktrees and coordinated through the Orca bus.
- Keep one implementation owner per worktree. Use a different worker for
  independent review when a change is material or high risk.
- Every worker inherits this file's Git identity, public-data, read-only portal,
  provenance, and engineering rules. Task briefs must repeat the rules that are
  most relevant to the assignment.
- Worker routing and evaluation records are maintained locally under
  `project-plan/delegation/`. Append an evaluation after every reviewed worker
  attempt, including partial or failed attempts; do not select models by
  sentiment alone once observed evidence exists.
- The local worker roster is operator-controlled. Do not add a model, provider,
  or delegation channel without explicit approval.
