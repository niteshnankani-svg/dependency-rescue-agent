# Third-party materials

The application code is new. Downloaded repositories, package archives, model weights and private review files are excluded from Git.

- **DepBench/build_from_source:** benchmark metadata and task setup retrieved from Hugging Face revision `3eef955c222baa310ef039153755ec9d7cdb03f3`. Licensing is per upstream task. Do not treat the dataset's `other` label as blanket redistribution permission. Reference solutions were not downloaded.
- **chris48s/v8r:** pinned base `febc231dc747a4743322ea5eb7d91ca4dc81177d`; MIT. The locally downloaded checkout contains the upstream LICENSE. Prepared patch artifacts contain changes to this project and should remain associated with that license.
- **Qwen3 4B:** Apache-2.0 model package served locally through Ollama. No weights are committed.
- **Node 18.20.8:** official archive plus official SHA-256 checksums. Used only to reproduce a historical development case; not proposed as a current production runtime.
- **Python dependencies:** exact installed versions appear in requirements.lock; their licenses remain with their distributions.

No private GitHub source reviewed during project selection is redistributed in this repository.
