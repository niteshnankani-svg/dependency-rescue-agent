# Deployment

## Supported topology

Deploy the API and its persistent runtime volume on one host, and the execution controller on a **separate dedicated disposable Linux VM**. Put the model on a separate service when possible. The API must never receive the Docker socket. The controller requires that socket to create restricted test containers; it consequently controls its own worker host. Do not share that host with production databases, customer secrets, cloud instance credentials or unrelated workloads.

Use one API process and its built-in queue worker. This release does not claim multi-tenant isolation, multi-replica coordination or high availability. Back up the runtime volume. A small hosted API service can be used with an external executor; a platform that forbids a Docker daemon cannot host the executor itself.

## Prepare images and data

On a trusted setup machine with Docker, Python 3.12+ and network access:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python scripts/prepare_linux.py
.venv/bin/pytest -q
docker build --target api -t dependency-rescue:local .
docker build --target executor -t dependency-rescue-executor:local .
```

The app images intentionally contain no benchmark repositories, dependencies, model weights or credentials. Copy the prepared `data/external` directory to both API and worker hosts, preserving the relative paths specified by `cases.json`. Custom case registration requires rebuilding both images with the same updated registry. Restrict data mounts to read-only. Pull every registered case's digest-pinned Node image on the worker before starting service; the runtime runner uses `--pull=never`.

The committed `bootstrap/` lockfiles recreate these historical development cases. Setup allows npm registry access but disables lifecycle scripts. If a future customer case requires compilation scripts, review and build it in a separate controlled setup environment; do not remove this restriction globally.

## Configure access and transport

Generate private deployment configuration; the script prints the filename, not tokens:

```sh
.venv/bin/python scripts/init_env.py \
  --domain repair.example.com \
  --executor-url https://executor.example.com \
  --model-provider gemini \
  --model gemini-3.1-pro-preview \
  --model-url https://generativelanguage.googleapis.com/v1beta \
  --data-root /srv/rescue/data \
  --workspace-root /srv/rescue/executions
```

Replace example hosts with your own DNS and paths. Set `GEMINI_API_KEY` in the private generated file. For Anthropic use provider `anthropic`, model `claude-sonnet-4-6`, URL `https://api.anthropic.com/v1`, and `ANTHROPIC_API_KEY`. Use HTTPS for hosted model transport. Store the generated file securely and distribute only the execution token to the worker. The API uses two separate service keys for operator and reviewer. The UI accepts an organization access token. Alternatively configure `RESCUE_OIDC_ISSUER`, `RESCUE_OIDC_AUDIENCE` and `RESCUE_OIDC_JWKS_URL`; map `roles` to viewer/operator/reviewer. Only RS256 access tokens with issuer, audience, expiry, issuance time and subject are accepted. This is token verification, not a hosted OAuth login/redirect flow.

Production startup refuses local execution, missing identities, weak executor tokens or implicit allowed hosts. Production cookies require HTTPS. Preserve authorization headers through your reverse proxy. Restrict worker ingress to the API host in addition to its bearer token. Keep cloud instance-metadata access disabled on the worker VM.

## Start worker and API

Worker host:

```sh
mkdir -p /srv/rescue/executions
# Set worker RESCUE_DOMAIN=executor.example.com and RESCUE_UPSTREAM=executor:8094.
docker compose --env-file .env.worker -f compose.executor.yaml -f compose.tls.yaml up -d --build
```

The workspace path must be identical on the host and inside the controller container: Docker bind mounts are resolved by the host daemon. Set the worker env file's prepared-data path, workspace path, executor token, domain and upstream. The controller's Docker socket must point to this worker's daemon only.

API host:

```sh
docker compose --env-file .env.production -f compose.yaml -f compose.tls.yaml up -d --build
```

Caddy obtains certificates when real DNS points to the host and ports 80/443 are reachable. Certificate issuance has not been exercised against a customer domain in this repository. If using an existing HTTPS ingress, omit `compose.tls.yaml` and route to the loopback service ports instead. `RESCUE_PRIVATE_EXECUTOR=1` permits HTTP only for an explicitly isolated private test/service network; use HTTPS between normal production hosts.

Check `/healthz` for liveness and `/readyz` for prepared cases, configured model availability and worker health. Confirm operator cannot approve and reviewer cannot execute. The default queue limit is three jobs; the executor handles one at a time. Model requests default to a 180-second timeout; set `RESCUE_MODEL_TIMEOUT=300` for slower CPU inference (maximum 600 seconds). Test calls have separate limits. Tests use each case's bounded timeout. Cancellation interrupts local Docker execution promptly; a remote test/model call may finish before the graph observes cancellation.

## GitHub draft PR delivery

Delivery is disabled unless explicitly configured. Install your GitHub App on allowed customer repositories with repository contents and pull-request write permissions. Mount its private PEM key read-only into the API and set `RESCUE_GITHUB_APP_ID`, `RESCUE_GITHUB_INSTALLATION_ID`, `RESCUE_GITHUB_PRIVATE_KEY_FILE`, and `RESCUE_GITHUB_ALLOWED_REPOS` (comma-separated owner/name values). Add these environment variables and the key mount through a private Compose override; never bake the key into an image.

After approval/export, a reviewer calls `POST /api/runs/{id}/publish`. The current repository default branch must still equal the registered base commit. Existing matching delivery is reused; unrelated branches are never overwritten. Only a draft PR is created. Historical benchmark bases usually fail the current-default-branch check, deliberately preventing accidental upstream publication. The GitHub adapter has mocked integration tests; no real customer App delivery was performed.

## Operations and recovery

Stop accepting jobs, let active work finish, then stop the API worker before taking a filesystem-consistent backup:

```sh
RESCUE_RUNTIME=/path/to/runtime .venv/bin/python scripts/backup.py /secure/backups/rescue-2026-09-16
```

SQLite uses its online backup API; the default also copies workspaces and exported patches. Keep checkpoints private because they contain source code. The backup excludes credentials. Restore both databases, run directories and patches together, restore credentials separately, and use the same case registry/prepared-data revision. Restart one API process: stale running leases become eligible for recovery. Without workspaces, old approvals cannot safely export. Retain cancelled/failed work only as long as your source-retention policy requires; never delete an active or pending-review workspace.

`sh scripts/ci.sh` runs application checks. `scripts/smoke_containers.py` exercises production API authentication, the separate controller, protected Docker access and a real baseline test request using temporary local containers. It generates no external writes. `scripts/isolation_probe.py` tests the configured runner's restrictions. These are local validation tools, not substitutes for an organization-specific security review, load testing or deployment monitoring.

## Optional Docker model service

On a separately provisioned model host, `docker compose -f compose.model.yaml up -d` starts pinned Ollama and pulls the configured code model into a persistent volume. The model port is loopback-only; use an authenticated private proxy or private network transport to reach it from the API. The overlay configuration is validated, but this model container has not been runtime-qualified on this low-memory Mac; earlier evaluations used native Ollama; final hosted evaluation details are in VALIDATION.md. Provision at least 16 GB RAM for model/worker operation or keep them on separate hosts. Model weights are downloaded at setup, never committed.
