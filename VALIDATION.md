# Qualification — 2026-10-02

Dependency Rescue is implemented and locally qualified as a single-organization dependency-repair application. It uses a durable LangGraph workflow, hosted model proposals, isolated tests, explicit human review, and patch export. It has not been deployed to a customer cloud environment.

## Final live Gemini runs

Provider: Gemini, model `gemini-3.1-pro-preview`. No reference repair solutions were accessed. Each candidate was independently rerun after generation and its complete patch applied to a checksum-verified pristine upstream archive. Patched source, manifests and declared test migrations matched the verified files byte for byte.

| Dependency upgrade | Baseline | Broken upgrade | Repaired | Model attempts |
| --- | --- | --- | --- | --- |
| js-yaml 3.14.x → 4.0.0 | 20/20 | 17/20 | 20/20 | 1 |
| Terser 4.3.9 → 5.3.0 | 6/6 | 3/6 | 6/6 | 2 |
| lru-cache 8.0.0 → 9.0.0 | 73/73 + tsd | Runtime startup failures + type failures | 73/73 + tsd | 1 |
| SVGO 2.4.0 → 3.0.0 | 92/92 | 91/92 | 92/92 | 1 |

These are **four development cases, not an independent benchmark score**. Pinned DepBench canonical test migrations are part of the operator-prepared fixtures. Terser's migration makes tests await promises and adds a Hexo integration test. SVGO's upgraded tests use the version-3 plugin/error contract. LRU's upgraded type test uses the named export; `tsd` runs in addition to the runtime suite. The model cannot edit these tests. Original failed local-model and earlier incomplete test-setup results remain in `reports/history/`.

The original Terser setup incorrectly expected synchronous returns from an asynchronous dependency. The original SVGO setup tested outdated direct-library behavior, and the first LRU runner omitted type checks. These setup defects were corrected explicitly rather than counting incomplete checks as passes. All declared test migrations are protected during repair and included in the reviewed export.

Evidence: `reports/*-evaluation.json`, `reports/artifact-qualification.json`. Original four successful candidates remain awaiting user review; the approval smoke test uses its own copy.

## Application and isolation checks

- 56 application tests passed, covering policy, model protocols, persistent workflow behavior, authentication, authorization and GitHub delivery safeguards. `reports/unit-tests.xml`.
- Production API and dedicated executor images built successfully. Container smoke checks passed for unauthenticated refusal, operator/reviewer separation, secure cookies, all registered cases, remote execution, readiness and absence of a Docker socket in the API. `reports/container-smoke.json`.
- Five real isolation probes passed: non-root execution, read-only source, unavailable host credentials/socket, dropped capabilities and no network egress. `reports/isolation.json`.
- A copied candidate passed fresh Linux verification, checkpoint reopen, exact-digest approval and exported-patch readback. `reports/review-smoke.json`.
- Backup SQLite integrity and row-count checks passed; a full cloud disaster-recovery exercise was not performed. `reports/backup-smoke.json`.
- Final live API readiness returned HTTP 200 with four prepared cases, Gemini availability and Docker executor availability. UI shows the Gemini model, runtime results and additional type validation.
- The local credential is excluded from Git and Docker build context; no credential match was found in publishable files.

## Deployment boundaries

Deploy one API process with persistent storage and a separate dedicated disposable worker VM. Docker provides restricted execution but shares its worker host kernel. Customer repository onboarding, cloud networking, DNS/TLS, organization OIDC and GitHub App credentials are deployment-specific. No customer cloud deployment or real customer draft-PR delivery was performed. GitHub delivery has mocked integration coverage and refuses stale repository bases.

Anthropic support is implemented and protocol-tested, but no live Anthropic credential was available. Gemini was live-tested; its initial 2.5 Pro model was rejected by the provider despite appearing in model listings, so the provider-recommended 3.1 Pro preview was used. Availability checks alone do not establish generation access or repair accuracy. Preview model availability may change; configure an available model and rerun qualification before changing providers in production.

Passing these tests does not establish general repair accuracy, multi-tenant isolation, high availability or absence of every semantic regression. Human review remains required; the application never automatically merges or deploys a repair.
