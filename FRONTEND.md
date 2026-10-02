# Repair workspace frontend

The frontend is served by FastAPI at `/`. It uses plain HTML, CSS and JavaScript with no external CDN or third-party analytics. Motion is bundled locally using the locked npm build. It shares the API's origin and HttpOnly session cookie. Model credentials remain on the server.

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

## Vercel frontend — 2026-10-02

Production URL: https://dependency-rescue-ui.vercel.app

The Vercel deployment contains only static frontend assets. It intentionally displays **Backend not connected**, disables run controls and makes no API polling requests. The operational local app remains at http://127.0.0.1:8093. Publishing the interface does not deploy the durable API or Docker executor.

Build and deploy:

```sh
npm ci
npm run build
cd dist
vercel deploy --prod
```

For a fresh machine, link `dist` to the existing `dependency-rescue-ui` project before deploying. Do not deploy the repository root: it contains private runtime data. The build copies only four frontend assets and generates strict security headers. No model keys, history, checkpoints, or organization tokens are included. The bundled Motion license notices are preserved.

The design uses original SVG circuit artwork and a bento-style composition inspired by the 21st.dev gallery (https://21st.dev/community/components), not a downloaded 21st component or paid integration. Motion (https://motion.dev/docs/animate) supplies staggered entrances, flowing graph edges, and a subtle core glow. A keyboard-accessible motion toggle stops continuous animation; reduced-motion preferences disable it by default, and hidden tabs pause it.

Before enabling remote repair operations, deploy the persistent API and worker described in DEPLOYMENT.md. Integrate an authenticated same-origin gateway, validate Origin/Host handling against the existing CSRF policy, and verify secure cookie login, roles, and review actions end-to-end. Do not embed API tokens in client JavaScript or weaken origin checks to make a proxy work.

Verification: 86 backend tests passed after the frontend update; npm reported zero dependency vulnerabilities. Browser checks passed on the published site at desktop and 390px mobile widths, including the motion toggle, disabled repair action, explicit disconnected state, and no console errors during the exercised flows.

### Expired local session recovery

Local development cookies expire after one hour. On an API 401, the client reloads the existing homepage bootstrap in the background and retries the rejected request once only when the server explicitly confirms a loopback development session. Production and non-loopback requests receive no automatic session. Mutation retries preserve the original idempotency key; successful responses and network failures are never replayed. Coverage: `node --test frontend/session.test.cjs` and the Python authentication tests.
