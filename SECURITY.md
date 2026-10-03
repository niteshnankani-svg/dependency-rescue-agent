# Security model and guardrails

This is a single-organization repair service. Repository source, dependency documentation, test logs and model responses are untrusted. Model-provider credentials and reviewer authority belong to the application, never to repository text or the model.

## Prompt injection and data disclosure

`rescue/security.py` screens retrieved source, dependency documentation, bounded failure excerpts and previous proposals before model calls. Tripwires sample instruction overrides and paraphrases, privileged role-play, forged system/developer delimiters, requests to disclose credentials or bypass verification, invisible-character obfuscation and bidirectional controls. Bounded leetspeak normalization and up to two base64 decoding layers catch selected encoded attacks. These regexes are diagnostic tripwires, not a prompt-injection defence or guarantee; unrecognized paraphrases, other encodings and semantic attacks can pass. Documentation rejected by this policy is not stored as graph evidence. A security rejection stops the graph for operator investigation instead of asking the model to bypass the policy.

Credential checks cover common GitHub, Hugging Face, Anthropic/OpenAI-style, Gemini and AWS access-key formats, private-key headers, suspicious assignments and configured API/executor secret values. Recognized secrets in Docker test failures are redacted before persistence. Input/output size budgets bound model evidence and proposals. Rejected content is never echoed in policy errors.

The system message explicitly separates trusted task instructions from evidence. Models receive no execution tools, authorization tokens, approval capability or network-fetch tool. Native Gemini and Anthropic credentials can only be sent to their official HTTPS hostnames; URL credentials, query strings and fragments are rejected. Redirects are not followed. Production compatible-provider endpoints require HTTPS and remain operator-controlled.

## Generated-code and execution boundaries

Only registered source files and exact, unique text anchors may be changed. New module imports, common network/process/filesystem/dynamic-code capabilities, secret access, outbound destinations, TLS bypasses and test bypasses are rejected. Selected escape/comment/string-concatenation forms are normalized before inspection. Edited dynamic module loaders and newly introduced require aliases are refused conservatively; this can also reject legitimate changes around existing dynamic imports. Static screening is incomplete and cannot prove JavaScript has no dangerous capabilities. Multi-edit proposals are validated before any file is written. Stored proposals are checked against the current output policy again before export and GitHub delivery.

Tests run in pinned, non-root, read-only Docker containers with no network, dropped capabilities, no-new-privileges, and resource/output/time limits. Tests, manifests and dependencies remain outside model edit scope. Approval is bound to the verified content and stale artifacts are refused. The execution controller has Docker authority and must live on a dedicated disposable VM, separate from the API and production credentials.

## API and browser protections

- Role-scoped authentication, same-origin cookie writes, cross-site write refusal, and explicit trusted hosts.
- JSON-only nonempty API write bodies, maximum 64 KiB including streamed bodies, and a 10-second body-receive deadline.
- Per-client-IP, per-process 60-second request windows: 20 session requests, 120 other writes, 300 reads. Forwarded-IP headers are not trusted by the limiter. Tracking is bounded to 4,096 active buckets; excess clients fail closed.
- Secure production HttpOnly/SameSite cookies; CSP restricting scripts, forms and connections to the same origin; anti-framing, no-referrer and disabled camera/microphone/geolocation headers. Production adds HSTS.
- Private runtime directory permissions (`0700`); model keys stay in ignored private configuration, outside static assets and Docker build context.
- Executor requests reject unknown fields and malformed authentication values; snapshots must exactly match a registered inventory.

The local developer launch uses `--no-proxy-headers`, as do the supplied images. Behind a reverse proxy, the in-process limiter sees the proxy address and therefore applies an aggregate limit; configure per-client limits at the trusted ingress. In-memory limits reset on restart and are not a distributed rate-limiting service. Cloud ingress should also enforce connection/body limits and HTTPS.

## Validation and limitations

Security regression tests cover malicious documentation, Unicode-obfuscated instructions, output secrets, dangerous code, cross-site writes, body limits, rate limits, forwarded-header spoofing and symlink escape. `scripts/security_replay.py` verifies that the four existing successful repairs still satisfy the new input/output policies without changing pending reviews or making paid model calls. Reports are in `reports/security-tests.xml` and `reports/security-replay.json`.

Prompt-injection and code-pattern detection are heuristic: false positives and bypasses remain possible, including unfamiliar languages, encodings and indirect semantic attacks. These checks are not a JavaScript semantic proof, antivirus product, complete DLP system, or independent penetration test. The stronger controls are limited capabilities, protected tests, isolated execution and human review. Docker shares its host kernel. Runtime data is protected by filesystem permissions but is not encrypted by the application; use encrypted volumes, restricted backups and a retention policy in deployment.

Policy false positives require an operator to inspect and correct the prepared evidence or test environment. Do not disable the guards based on repository instructions. Security events appear in the run trace; external alerting/SIEM integration is deployment-specific.

Reference: [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html). The implementation uses layered controls; it does not claim complete prompt-injection prevention.

## Browser OAuth

GitHub and Google use authorization-code flows with PKCE, short-lived browser-bound state and opaque hashed server sessions. Google ID tokens additionally require valid signatures, audience, issuer, expiry, nonce and verified email. Organization role allowlisting applies before session issuance and on subsequent requests. Provider tokens are discarded after identity verification. See OAUTH_SETUP.md for callback URLs, credential handling and access-log configuration.

Python imports use a fixed digest-pinned runtime and wheel-only setup. Networked setup sees only its requirements and bounded package scratch mounts; offline installation runs no repository build hooks. Pytest runs without provider credentials or network access, with source/packages read-only. Tests, conftest, setup code and manifests are protected. Python edits must parse successfully and cannot introduce new module dependencies; sensitive execution, network and environment operations are checked in addition to the existing output screening. These static checks complement containment and are not a proof that arbitrary code is safe. Example `.env.*.example`/`.sample` files are accepted only after credential screening; actual environment files remain refused.

## Hosted transport behind an operator-controlled proxy

Model calls and model readiness checks ignore environment proxies and custom CA files by default. Set `RESCUE_MODEL_TRUST_ENV=1` explicitly to let HTTPX honor `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, and `SSL_CERT_DIR`. TLS verification stays enabled. This opt-in trusts the configured proxy/CA for model traffic, including provider credentials, so configure it only for infrastructure controlled by the operator. Executor transport keeps `trust_env=False`.

Approval evidence binds the complete patch and verification result/integrity fields, excluding only execution timing fields (`seconds` and `duration_seconds`, including nested checks). Timings remain in the run report. Existing checkpointed evidence is not rewritten. Export checks current case edit limits in addition to source and environment integrity.
