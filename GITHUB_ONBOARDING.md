# GitHub repository onboarding

The local application can now inspect and import repositories beyond the four development fixtures. This is a single-organization, operator-controlled first release, not multi-tenant GitHub OAuth onboarding.

## Use it

1. Open the local app and select **Load connected repositories**. Enter `owner/repository`; the first 100 accessible repositories are suggested. A branch or commit is optional.
2. Leave **Inspect through GitHub MCP** checked for authenticated access. Inspection calls GitHub's official remote MCP `get_file_contents` tool in read-only mode, pinned to the resolved commit. GitHub REST provides canonical manifests and the commit archive.
3. Choose a direct dependency and an exact target version. **Prepare isolated environments** downloads the pinned archive, validates it, and installs baseline/upgraded dependencies in disposable Docker containers with lifecycle scripts disabled.
4. When preparation finishes, the new workflow is selected. **Run repair** invokes the existing LangGraph baseline/reproduction/repair/verification/review flow. A failing baseline blocks repair; inspection alone is not proof the test suite passes.
5. Review the exact evidence and approve export. Existing GitHub App draft-PR delivery still requires an administrator repository allowlist and a matching base-branch commit. Imports never automatically publish, merge, or approve.

## Connection

Credentials stay on the server. Priority: configured GitHub App installation, `RESCUE_GITHUB_READ_TOKEN`, then explicitly enabled local `gh` authentication (`RESCUE_GITHUB_LOCAL_CLI=1`, development only). The current Mac uses its existing signed-in GitHub CLI. No credentials are stored in browser storage or passed to the model or test container.

GitHub App settings use the existing `RESCUE_GITHUB_APP_ID`, `RESCUE_GITHUB_PRIVATE_KEY_FILE`, and `RESCUE_GITHUB_INSTALLATION_ID`. Grant repository contents read access for inspection; add contents and pull-request write access only for the separate approved draft-PR delivery feature. Production repository access also requires `RESCUE_GITHUB_ALLOWED_REPOS`. App installation and organization approval must be performed by an authorized GitHub administrator. The app does not create GitHub Apps or silently request wider permissions.

Official MCP endpoint: https://api.githubcopilot.com/mcp/ . Only `get_file_contents` is exposed through `X-MCP-Tools`, with `X-MCP-Readonly: true`. The endpoint and tool cannot be supplied by repository content or a model. Repository metadata and source download use https://api.github.com; redirects are restricted to HTTPS codeload.github.com and never forwarded the API token.

## Current compatibility and deployment limits

- npm projects with a committed package-lock.json and registry dependencies. No workspaces, git/file dependencies, private registries, npm overrides, or lifecycle-script builds.
- Test scripts must directly invoke Mocha or Jest with supported arguments. Shell chains/custom runners/custom reporters require an operator profile and receive an explicit refusal.
- Imported source edits are limited to JS/TS in src/ or lib/, plus root index.js/index.ts. Tests and manifests remain protected from model edits. Native dependencies or tests requiring network/services may not work.
- Imports currently use the existing pinned Node 18 worker image. Newer Node requirements need an additional qualified runner profile; this compatibility path is not a recommended general-purpose production runtime.
- Preparation is limited to one import at a time, with bounded archives and install timeouts. Source archives reject symlinks, special files, .env files, .npmrc and vendored node_modules. Package downloads must use the HTTPS npm registry with integrity hashes. Docker setup has network access but receives no GitHub or model credentials; test execution is offline.
- Dynamic definitions are private files in data/external/imports/registry.json. Inspections are stored under runtime/onboarding/ and bound to their operator. Neither is committed or uploaded to Vercel. Interrupted preparation is marked failed on API restart and requires a fresh inspection.
- **Automatic preparation is enabled only on the local Docker runner.** Remote production execution requires a snapshot distribution/registration service before onboarding can be enabled. The existing Vercel deployment is still frontend-only and disables onboarding there. It does not offer functioning hosted repairs.

## Validation

Run `.venv/bin/python -m pytest -q`, `node --test frontend/session.test.cjs`, and `npm run build`. Security coverage includes traversal, archive links/devices, non-registry downloads, shell test scripts, ownership, production allowlisting, and unauthenticated API calls. Live GitHub MCP access was verified against a pinned commit of the user's private Dependency Rescue repository; repository listing returned 29 accessible repositories on 2026-10-02.

Live import verification: `sinonjs/nise` at `a03756aeacf42608a720478da5b843ee3c81f18c` was inspected through MCP, downloaded, prepared for `path-to-regexp` 8.3.0, and registered through the dashboard. Run `a993ebb9aa18408fb2ddbbaa04ca77ad` executed 371 original tests (363 passed); missing `FormData`/`FileReader` browser globals caused the baseline to fail. The agent correctly blocked before model repair. This verifies real import/execution and the failure boundary, **not a successful repair qualification for this repository**. No tests were removed or modified to produce a passing result.

## Python repositories and project folders

Leave Project folder empty for the repository root, or enter a relative folder such as `backend` or `frontend`. Paths and manifests are pinned to the inspected Git commit. Patches and GitHub delivery retain that folder prefix.

Python inspection accepts static `requirements.txt` or `[project].dependencies` in `pyproject.toml`. The fixed profile uses Python 3.11 and pytest 8.3.5. It resolves published PyPI wheels only: editable installs, direct URLs, requirements include files, dynamic build dependencies and source builds are refused. Optional pyproject test extras are not automatically installed; include test dependencies in the selected manifest. Environment markers are evaluated for Linux/Python 3.11. Packages excluded by markers cannot be selected for repair.

During resolution the container sees only a requirements file and wheel output. Installation is offline and runs no repository setup/build hooks. The prepared environments record exact installed versions, wheel SHA-256 hashes and the runtime image digest in `rescue-python.lock.json`. Other direct dependencies are held at their resolved baseline versions while upgrading the selected dependency; transitive dependency versions may change and are recorded in the lock evidence.

Tests run with no network, no provider secrets, read-only source/packages, non-root user and resource limits. Pytest configuration and automatic third-party plugin loading are disabled. Repository `conftest.py` remains available for fixtures and is protected from agent edits. Skips and empty test suites do not count as a passing baseline. Existing tests requiring live services, downloads, model artifacts or additional plugins must be made reproducible before an upgrade can be repaired. The importer does not substitute fake tests or silently omit failures.

The same LangGraph workflow handles baseline, upgrade, reproduction, bounded API evidence, source-only repair, integrity checks and human review. Python test files, `conftest.py`, `setup.py`, dependency files and installed packages cannot be edited by the agent. Automatic preparation remains restricted to local Docker; production workers need synchronized immutable snapshots as described above.

`python scripts/with_env.py python scripts/python_smoke.py` creates a clearly labelled development HTTPX regression fixture and runs it to human review. It is validation of the Python path, not an independent customer benchmark; it refuses to overwrite an existing fixture.

Installer scratch uses private disk-backed mounts with a 1.5 GB download budget and a 3 GB installed-package budget, plus a five-minute stage timeout. This accommodates larger published wheels without enlarging the offline test container's writable scratch. Exceeding a budget produces a preparation failure. On a fresh worker, pull the exact Python image referenced by `rescue/python_profile.py` before preparing a Python project.
