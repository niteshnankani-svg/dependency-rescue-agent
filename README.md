# Dependency Rescue

A LangGraph repair desk for dependency upgrades that break application behavior. It reproduces the regression, asks a local model for a guarded source edit, verifies the change, and pauses for review before exporting a patch.

**Status: working local pilot, not production-qualified.** One real DepBench development case is enabled. Arbitrary repositories, vulnerability discovery, hosted workers and automatic PR creation are not implemented. The UI labels this scope explicitly.

## Measured result

On the pinned `chris48s/v8r` case: **20/20 baseline → 17/20 after upgrade → 20/20 after Qwen repair**. `js-yaml` stayed at `4.0.0`; tests and manifests passed integrity checks. Earlier model proposals were rejected by the edit guard. This is an adapted macOS development evaluation, not a held-out DepBench score. The reference solution was never downloaded or supplied to the model.

See [validation evidence](reports/validation.json), [app framework](APP_FRAMEWORK.md), [agent framework](AGENT_FRAMEWORK.md), and [research decisions](research/DECISIONS.md).

## Run locally

Supported validation host: Apple Silicon macOS, Python 3.12+, Node/npm for dependency installation, Git, and Ollama. Node 18 is downloaded only for the historical benchmark runner; it is not the production service runtime.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
ollama pull qwen3:4b
.venv/bin/python scripts/setup_case.py
.venv/bin/python -m uvicorn rescue.api:app --host 127.0.0.1 --port 8093
```

Open http://127.0.0.1:8093. Run the case, inspect its evidence and approve or reject export. Approval does not merge or deploy anything. Offline test execution requires the macOS sandbox; unsupported hosts fail closed.

For CLI validation: `.venv/bin/python scripts/run_case.py`. For application tests: `.venv/bin/pytest -q`. The benchmark's Linux verifier is deliberately excluded from application test discovery.

## API

The local browser receives a same-site HttpOnly session cookie. Direct API clients use the token in `runtime/.api-token` as `Authorization: Bearer <token>`. Keep the service bound to loopback. No token is committed to Git.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/cases` | List enabled, prepared development cases |
| `POST /api/runs` | Queue a run with `case_id` and `idempotency_key` |
| `GET /api/runs/{id}` | Read graph trace, test evidence and proposed diff |
| `POST /api/runs/{id}/decision` | Approve/reject the exact `evidence_digest` |
| `GET /api/runs/{id}/patch` | Download an approved patch |
| `GET /healthz` | Liveness and qualification status |

SQLite persists both checkpoints and jobs. Run **one API process and one worker**; multi-process workers are not qualified. A maximum of three active/queued requests bounds local load.

## Before cloud deployment

The original goal includes production deployment. This milestone does **not** meet that gate yet. A Dockerfile alone would not supply safe execution of customer code. [DEPLOYMENT.md](DEPLOYMENT.md) lists the concrete remaining worker, evaluation, identity and operational requirements. The current local runner is a controlled development harness, not a multi-tenant isolation boundary.

Private GitHub review material, downloaded benchmark repositories, model weights, credentials and runtime checkpoints are excluded from the repository. Third-party benchmark code retains its upstream license.
