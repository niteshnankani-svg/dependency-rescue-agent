# Repair workspace frontend

The frontend is served by FastAPI at `/`. It uses plain HTML, CSS and JavaScript with no external CDN, third-party analytics, or frontend build step. It shares the API's origin and HttpOnly session cookie. Model credentials remain on the server.

## Run locally

```sh
.venv/bin/python scripts/with_env.py .venv/bin/python -m uvicorn rescue.api:app --host 127.0.0.1 --port 8093
```

Open `http://127.0.0.1:8093/`. Docker builds include the static files automatically.

## Files and behavior

- `rescue/static/index.html`: accessible workspace layout, workflow selector, search/filter controls, evidence tabs and review dialog.
- `rescue/static/style.css`: responsive desktop/tablet/mobile layout, focus indicators, reduced-motion support and patch colors.
- `rescue/static/app.js`: live API data, status counters for the latest returned runs (maximum 100), selected-run evidence, audit history, review and cancellation requests, complete patch copying/download.

The page polls while visible. Failed requests display errors, and readiness distinguishes unavailable models/workers. Run selection guards against stale responses. Repeated unchanged results do not rebuild the patch DOM. The patch preview is limited to 1,500 lines to keep large lockfiles responsive; copying and approved downloading retain the complete patch.

Approval, rejection and cancellation use a confirmation dialog bound to the selected run and evidence digest. Dismissing it performs no mutation. All server authorization and evidence checks remain in force. The UI does not automatically approve, merge, deploy, or publish a repair.

## Browser verification — 2026-10-02

Verified against the running API and real Gemini repair records:

- Workflow loading, readiness, live counts and selected-run test results.
- Repository search and status filtering, including an empty result.
- Changes tab, colored patch preview and explicit truncation notice.
- Audit history loaded for the selected run.
- Review dialog dismissal using both Go back and Escape; original pending review remained unchanged.
- Mobile layout at 390 × 844: document width 390, no horizontal page overflow.
- Keyboard-operable tabs and semantic labels implemented; no browser console errors during the exercised flows.
- Existing backend suite: 56 tests passed; JavaScript syntax check passed.

No new paid repair was launched during frontend verification. Approval/export behavior is also covered by the existing backend validation documented in `VALIDATION.md`.
