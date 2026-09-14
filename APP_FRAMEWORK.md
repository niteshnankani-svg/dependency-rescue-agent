# App framework

## Company problem

Engineering and application-security teams defer dependency upgrades when the new version breaks tests or application APIs. The intended product converts a failed upgrade into an evidence-backed repair proposal. The buyer hypothesis is a platform or application-security team managing many repositories. Market evidence establishes an existing product category, not proven willingness to pay for this particular implementation.

## Delivered user flow

1. Select the qualified development case and queue a repair.
2. Inspect baseline, post-upgrade and post-repair test counts.
3. Follow the persisted graph trace and inspect the model's diagnosis.
4. Review the source and dependency diff bound to an evidence digest.
5. Approve export or reject the proposal. Download the approved patch.

The interface never claims to have fixed a vulnerability: this first dataset case is a compatibility upgrade. Advisory ingestion and exposure prioritization remain future work.

## Components

| Component | File | Responsibility |
| --- | --- | --- |
| Repair desk | `rescue/static/` | Responsive UI; real API state; no mock success counters |
| API and queue | `rescue/api.py` | Session/bearer auth, origin/host checks, idempotent submission, bounded queue, decisions |
| Graph | `rescue/graph.py` | State, regression reproduction, repair loop, verification, durable review and export |
| Model adapter | `rescue/model.py` | Local Ollama structured output; bounded source context and installed API evidence |
| Edit guard | `rescue/guards.py` | Source allowlist, exact anchors, one atomic edit, test/manifest integrity |
| Isolated runner | `rescue/runner.py` | Offline macOS process, read-only source, bounded runtime |
| Data preparation | `scripts/setup_case.py` | Pinned benchmark/base/runtime setup; install scripts disabled |
| Research | `research/` | Inventory summary, dataset provenance, fit and reuse decisions |
| Evidence | `reports/validation.json` | Actual development-run measurements and limitations |

## Data and model

DepBench provides real dependency-upgrade cases. The downloaded snapshot has 201 tasks; only one is enabled in this app. Its repository license is MIT. The model is local Qwen3 4B, quantized through Ollama. No fine-tuning occurred. Your complaint and sentiment classifiers were assessed and rejected for this task because their output labels do not express code-repair operations.

## Production acceptance gates still open

Multi-repository adapters; untouched held-out evaluation; isolated Linux workers; credential separation; OIDC/RBAC; audit retention; real customer trial; dependency-advisory integration; authorized draft-PR delivery. See DEPLOYMENT.md. Adding decorative graph nodes or more models would not satisfy these gates.
