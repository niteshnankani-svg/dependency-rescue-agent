# Public showcase

`npm run build` bundles Motion locally and publishes `rescue/static/showcase.html`
as the static Vercel entry point. The authenticated local workspace remains
`rescue/static/index.html`; its API, authentication, and worker behavior are unchanged.

The public walkthrough is a manually curated replay of the local HTTPX validation
in `reports/python-validation.json`. It never starts a repair or represents the
fixture as an upstream repository repair. The patch is formatted for readability.
The recorded run is awaiting approval. No approval or merge is simulated.

The showcase uses original CSS perspective graphics and the installed Motion
library. It includes a motion toggle, honors reduced-motion preference, pauses
ambient loops when hidden, and stops replay when the tab is hidden. All scripts
and styles are local assets, preserving the deployment's strict CSP.

Deploy only `dist/` to the existing Vercel project; never upload runtime data,
credentials, or the repository root. Live repair execution still requires a
separately hosted API, persistent state, and isolated worker.

Validation: frontend session tests (3 passed), successful production bundle,
manual desktop/mobile layout inspection, recorded-stage navigation, replay
play/pause, motion toggle, and browser console checks.
