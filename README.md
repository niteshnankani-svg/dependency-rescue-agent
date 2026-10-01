# Dependency Rescue

A LangGraph application that repairs source incompatibilities introduced by dependency upgrades. It proves the original tests pass, reproduces the breakage, proposes bounded source edits, tests them in offline Linux containers, and pauses for a reviewer before exporting a patch. An optional GitHub App can create a draft PR in an explicitly allowed repository.

The enterprise problem is the engineering work left after an upgrade bot opens a dependency PR that breaks tests. This app handles the repair and review workflow; it does not discover every vulnerability or promise every upgrade can be repaired.

## What is implemented

- Thirteen-node repair graph with three-attempt budgets, persistent checkpoints, human approval and stale-evidence checks.
- FastAPI, responsive repair desk, multi-case registry, durable queue, cancellation, audit records and idempotency.
- Separate execution service; tests run without network, host credentials, writable source or elevated capabilities.
- Role-scoped service keys or RS256 OIDC access tokens; operator and reviewer permissions.
- Pinned Docker images, API and worker Compose files, optional Caddy HTTPS front door, backup and smoke-test scripts.
- Four real JavaScript dependency-upgrade cases from pinned upstream repositories and DepBench metadata. Customer cases are added as operator-reviewed snapshots.

See [VALIDATION.md](VALIDATION.md) for measured qualification. See [APP_FRAMEWORK.md](APP_FRAMEWORK.md), [AGENT_FRAMEWORK.md](AGENT_FRAMEWORK.md), [DEPLOYMENT.md](DEPLOYMENT.md), and [research/DECISIONS.md](research/DECISIONS.md). Measured outcomes and limitations are in [reports](reports); a passing development case is not a general benchmark score.

## Model configuration

Create an ignored `.env` file with mode `600`, then set `RESCUE_MODEL_PROVIDER=gemini`, `RESCUE_MODEL=gemini-3.1-pro-preview`, `GEMINI_API_KEY`, and `RESCUE_RUNNER=docker`. For Anthropic set provider `anthropic`, model `claude-sonnet-4-6`, and `ANTHROPIC_API_KEY`. The provider URL defaults automatically; remove any old Ollama URL and `RESCUE_SERIAL_COLIMA` when switching to a hosted provider. Only retrieved source, package documentation and failure excerpts are sent to the selected provider; tests and host credentials are excluded.

Use `scripts/with_env.py` before API or evaluation commands to load this file without shell evaluation. Production Compose accepts either provider key. Ollama remains optional (`RESCUE_MODEL_PROVIDER=ollama`, `RESCUE_MODEL=qwen3:4b`). No automatic provider fallback spends another account’s credits.

## Local setup

Requires Python 3.12+, Docker with a Linux daemon, Git, and a Gemini, Anthropic, Ollama or compatible model API. Allow at least 16 GB available RAM and 20 GB free disk for comfortable local model/worker operation; a remote model avoids competing for local memory. The service runs on Python 3.12; Node 18 is confined to historical benchmark containers.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python scripts/prepare_linux.py
.venv/bin/python scripts/with_env.py .venv/bin/python -m uvicorn rescue.api:app --host 127.0.0.1 --port 8093
```

On a named Docker context, also set `RESCUE_DOCKER_CONTEXT`. Setup fetches checksum-verified upstream archives, installs committed lockfiles with package lifecycle scripts disabled, and refuses to overwrite prepared snapshots. It requires network access; subsequent test execution has no network. It never fetches reference repair solutions. All four cases are development fixtures using canonical test migrations where required by the upgraded API. Terser includes the canonical Hexo integration test; LRU also requires tsd. The model cannot edit these tests. Operator-supplied test migrations are included in the reviewed export. These cases are not an independent holdout.

Open <http://127.0.0.1:8093>. The loopback development UI receives a local HttpOnly cookie. Direct clients can use the private token in `runtime/.api-token`. Production disables automatic local login: follow the deployment guide for separate hosts, HTTPS and organization credentials.

```sh
.venv/bin/pytest -q
.venv/bin/python scripts/with_env.py .venv/bin/python scripts/evaluate.py
.venv/bin/python scripts/isolation_probe.py
```

## Frontend

The responsive repair workspace includes live service readiness, recent-run totals, repository search, status filters, an execution timeline, a colored patch viewer, audit history, and explicit review dialogs. See [FRONTEND.md](FRONTEND.md) for setup and browser validation. It is included in the API image and requires no separate frontend build.

## API

| Endpoint | Behavior |
| --- | --- |
| `POST /api/session` | Exchange an authorized bearer token for a secure production cookie |
| `GET /api/cases` | List registered cases and preparation status |
| `POST /api/runs` | Operator queues a case with an idempotency key |
| `GET /api/runs/{id}` | Trace, test evidence, model diagnosis and proposed diff |
| `POST /api/runs/{id}/cancel` | Operator requests cancellation |
| `POST /api/runs/{id}/decision` | Reviewer approves/rejects the exact evidence digest |
| `GET /api/runs/{id}/patch` | Download an approved patch |
| `POST /api/runs/{id}/publish` | Reviewer creates/reuses an optional allowlisted draft PR |
| `GET /api/runs/{id}/audit` | Read submission, cancellation, review and delivery records |
| `GET /healthz`, `GET /readyz` | Liveness and dependency readiness |

This is a single-organization, single-API-process deployment. It is not a multi-tenant arbitrary-code platform. Docker shares its worker host kernel; deploy the executor on a disposable dedicated VM. Cloud deployment, real organization SSO and customer GitHub App credentials must be configured by the deploying organization. No external repository was modified during evaluation.

For a constrained development Mac with a dedicated `rescue` Colima profile, set `RESCUE_SERIAL_COLIMA=rescue` and `RESCUE_DOCKER_CONTEXT=colima-rescue` on the API. The scheduler stops only that explicitly selected worker during local inference and restores it before verification. This option refuses production; deploy model and worker separately there. Historical `scripts/setup_case.py` and `scripts/summarize_validation.py` describe the original pilot; use the Linux setup and evaluation commands above for this release.
