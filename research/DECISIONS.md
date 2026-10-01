# Research and selection — updated 2026-10-01

## Review coverage

GitHub: inspected README and recursive file-tree inventories for all **28 owned repositories**. Read graph/verifier implementation files in `agent-company` and graph code in `Multi_agent_ticketing_system`. This is not a claim that every line of every repository was audited. Raw private README/source material stays in the ignored `research/private/` directory.

Hugging Face: inspected the account's **20 assets: 10 models, 3 datasets, 7 Spaces**. Models are predominantly sentiment/complaint classifiers, including the seven complaint BERT variants and movie-review BERT; two BargainAI models are private. The three legal-rag-index datasets are retrieval artifacts rather than code-repair ground truth. Spaces include credit risk, job applications, customer support, legal RAG, complaints and bargaining.

## Reuse decisions

| Existing work | Useful learning | Decision |
| --- | --- | --- |
| agent-company | Typed routing, retry budgets and separate verifier; current verifier relies partly on confidence/evidence IDs | Reuse architectural ideas, replace verification with real tests and integrity checks |
| Multi_agent_ticketing_system | Classification, escalation and graph organization | Retain explicit failure routes; do not reuse unrelated classifier labels |
| recallai | API configuration, request lifecycle and rate-limit patterns | Independent API and bounded job queue; no voice/emotion dependencies |
| niryat-ai | Source provenance and application/API structure | Keep explicit dataset provenance; no export-domain data in code repair |
| claude-contract-agent | Existing Kubernetes incident simulation | Avoid duplicating the simulated maintenance/incident direction |
| complaint BERT / BargainAI / legal indexes | Domain-specific trained assets | Not suitable for code-edit generation or executable verification |

No source code or private model weights from those repositories were copied into this app. It is self-contained and does not import sibling project runtimes.

## Why this enterprise problem

GitLab's July 2026 dependency-remediation announcement describes repairs to code broken by dependency upgrades. That is direct evidence that enterprise tooling addresses this problem. It also means the category is competitive; this project is not presented as a novel invention. The value hypothesis is auditable, private/local-model repair with reproducible evidence for smaller engineering teams.

Source: [GitLab — When a version bump breaks your build, GitLab fixes it](https://about.gitlab.com/blog/dependency-scanning-auto-remediation/).

## Data selection

[DepBench paper](https://arxiv.org/abs/2608.30300) describes 203 real-world dependency-upgrade tasks. The [available Hugging Face snapshot](https://huggingface.co/datasets/Depbench/build_from_source) contains 201 tasks after licensing exclusions. These numbers refer to different artifacts and are not interchangeable.

Pinned snapshot: `3eef955c222baa310ef039153755ec9d7cdb03f3`. Metadata downloaded for the full snapshot; task inputs downloaded for 10 pip cases and one npm case. Four npm cases are now prepared and executable: v8r/js-yaml, hexo-uglify/Terser, get-jwks/lru-cache and hexo-yam/SVGO. The dataset viewer failed; repository files remained downloadable.

First case: `chris48s__v8r__22`, js-yaml 3.14.x → 4.0.0, MIT-licensed upstream, base commit `febc231dc747a4743322ea5eb7d91ca4dc81177d`. Dataset setup specifies this base checkout. No later commits, repair PR diff or reference solution were inspected. Canonical test additions were used in the development harness, so this evaluation is not held out. Execution now uses offline, non-root Linux Docker with a common pinned Node 18 image and must not be described as an official benchmark score.

Dataset licensing is per upstream repository; `license: other` is not blanket commercial permission. Source repositories and benchmark tests are downloaded on demand. Public package manifests/lockfiles and upstream license notices are committed under bootstrap for reproducible setup.

## Original pilot model selection

[Ollama Qwen3 4B](https://ollama.com/library/qwen3:4b) provides a local Apache-2.0 model package small enough to run on this host. Installed quantization is Q4_K_M, approximately 2.5 GB. No training was needed for the first case. The pilot uses bounded structured edits and actual test feedback. Earlier unrestricted multi-edit responses included nonexistent API calls; policy rejected them. Restricting this milestone to one atomic edit yielded a verified repair. That result does not establish general code-repair capability.

LangGraph persistence and approval design follow [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence).

## Current model qualification

The default is [Qwen3 4B](https://ollama.com/library/qwen3:4b), Apache-2.0, Q4_K_M (~2.5 GB). Thinking is disabled for bounded JSON proposals. Qwen2.5-Coder 1.5B and 7B Q3_K_M were tried during development but failed the repair cases; those failures are retained in reports/history. Model size is not treated as evidence of repair quality. No training or reference solutions are used. The 8K context includes numbered source ranges, installed API differences and bounded test feedback. On this constrained development Mac, explicitly configured serial scheduling suspends the dedicated worker VM during inference. Production should provision separate model and executor hosts. See VALIDATION.md for measured qualification.


## Hosted provider update — 2026-10-02

At the user's request, the final evaluation switches to Gemini using an existing local credential. The model-list endpoint advertised Gemini 2.5 Pro, but generation returned 404 (unavailable to new users); the provider-recommended `gemini-3.1-pro-preview` successfully generated structured JSON. Native Gemini and Anthropic adapters are implemented. Anthropic has protocol tests but no live credential was available. See [Google structured output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output) and [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). Earlier local-model findings above are historical. No automatic failover or training is performed. Final measured repair results belong in VALIDATION.md.


### Test-contract correction

Original Terser tests called a newly asynchronous API synchronously, SVGO tests asserted obsolete direct-library behavior, and the first LRU runner omitted `tsd`. These were evaluation setup defects, not evidence that a safe source repair was impossible. The final fixtures include operator-reviewed canonical test migrations (baseline and upgraded for Terser; upgraded only for SVGO/LRU), Hexo 5.2.0 as the Terser integration-test dependency, and isolated LRU type checking. The repair model still cannot edit tests. All four cases are development validation, not hidden-test benchmark results. Approved exports include the explicit test migrations and diff manifests against checksum-verified pristine bases.
