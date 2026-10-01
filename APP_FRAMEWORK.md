# Application framework

## User workflow

An operator selects a registered repository/upgrade and starts a repair. The desk displays baseline, broken and repaired test counts alongside a graph trace and proposed diff. A reviewer checks the evidence and approves export or rejects it. Approval binds the actual diff, verification result, installed dependency tree and case definition. Optional delivery opens a draft PR; it never merges or deploys the change.

## Components

| File | Responsibility |
| --- | --- |
| `rescue/api.py` | HTTP API, durable SQLite queue, leases, cancellation, approval, audit trail |
| `rescue/static/` | Repair desk, repository selector, run history, evidence and review UI |
| `rescue/auth.py` | Operator/reviewer/viewer roles, service keys, fixed-issuer RS256 OIDC verification |
| `rescue/config.py`, `cases.json` | Operator-owned repository revisions, source allowlists, dependency versions, test commands and budgets |
| `rescue/graph.py` | Durable LangGraph workflow and approval interrupt |
| `rescue/providers.py` | Gemini, Anthropic, Ollama and compatible-provider configuration; environment-only credentials |
| `rescue/model.py` | Bounded source retrieval, installed dependency API evidence, structured model requests |
| `rescue/guards.py` | Credential-pattern preflight, allowed source edits, exact anchors, dangerous-edit checks and integrity hashes |
| `rescue/execution.py` | Offline Docker runner, time/output/resource bounds, reporter parsing, remote worker client |
| `rescue/executor_api.py` | Authenticated execution service on a dedicated worker VM |
| `rescue/delivery.py` | Optional allowlisted GitHub App draft PR delivery with stale-base refusal |
| `rescue/resources.py` | Explicit development-only Mac scheduling; dedicated worker suspended during local model inference |
| `rescue/readiness.py` | Model, prepared-data and executor readiness |
| `scripts/prepare_linux.py` | Checksum-verified sources and lockfile-based Linux setup |
| `scripts/register_case.py` | Customer case registration from reviewed prepared snapshots |
| `scripts/backup.py` | Online SQLite backup plus artifacts and optional workspaces |

## Runtime boundaries

The API persists checkpoints, queue and audit records under `RESCUE_RUNTIME`. It sends only source snapshots and a registered case ID to the execution service. The execution service supplies its own registered tests and dependencies, rejecting unexpected paths or missing files. It launches a read-only, non-root, network-disabled test container and returns a bounded result. The API has no Docker socket; only the dedicated worker controller does.

Use one API process with its built-in worker. Job leases recover interrupted work after restart. Graph nodes repeat safe preparation/testing rather than treating interrupted execution as success. The queue allows three active/queued jobs; the executor runs one test job at a time. This is bounded concurrency, not horizontal scaling or a high-availability guarantee.

## Customer onboarding

Prepare baseline and upgraded snapshots in a controlled environment, with lifecycle scripts disabled and reviewed test commands. Confirm the original tests pass and the upgrade fails. Register a JSON case through `scripts/register_case.py`; deploy the same registry and snapshots to API and worker. Untrusted callers cannot provide commands, repository URLs, filesystem paths or dependency versions through the public run API.

Source credential detection is heuristic and does not replace repository secret scanning. Model text and package documentation are untrusted inputs. Source edits must still satisfy executable tests and human review. Passing tests cannot prove absence of every semantic regression or malicious behavior.

## Test contracts and export

Operator-approved version-specific test migrations are stored in `bootstrap/<case>/test-migration.patch`; models cannot change them. They are protected during verification and included in exported patches. Original source manifests are preserved in `bootstrap/<case>/base` so exports apply to the pinned upstream revision, including any required test dependencies. `scripts/qualify_artifacts.py` checks patch application and byte equality against verified files. Additional registered commands such as `tsd` must pass as well as the runtime test suite.
