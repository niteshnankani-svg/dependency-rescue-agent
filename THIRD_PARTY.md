# Third-party materials

The application code is new. Downloaded repositories, package archives, model weights and private review files are excluded from Git.

- **DepBench/build_from_source:** benchmark metadata and task setup retrieved from Hugging Face revision `3eef955c222baa310ef039153755ec9d7cdb03f3`. Licensing is per upstream task. Do not treat the dataset's `other` label as blanket redistribution permission. Reference solutions were not downloaded.
- **chris48s/v8r:** pinned base `febc231dc747a4743322ea5eb7d91ca4dc81177d`; MIT. The locally downloaded checkout contains the upstream LICENSE. Prepared patch artifacts contain changes to this project and should remain associated with that license.
- **Qwen3 4B:** Apache-2.0 model package served locally through Ollama. No weights are committed.
- **Node 18.20.8:** official archive plus official SHA-256 checksums. Used only to reproduce a historical development case; not proposed as a current production runtime.
- **Python dependencies:** exact installed versions appear in requirements.lock; their licenses remain with their distributions.

No private GitHub source reviewed during project selection is redistributed in this repository.

## Additional registered cases and bootstrap files

The `bootstrap/` directory redistributes upstream-derived package manifests, canonical test migration patches, and generated npm lockfiles to reconstruct the evaluated dependency trees. It contains no application implementation or reference repair solution. Upstream license notices are retained alongside these files.

- **hexojs/hexo-uglify:** `cca9eb7376b0a2fff9f2e6163957c99c73a55539`, MIT; Terser 4.3.9 → 5.3.0.
- **nearform/get-jwks:** `d3d40dd801bd6600fab7377f1cc4575245ef4bbd`, MIT; lru-cache 8.0.0 → 9.0.0.
- **curbengh/hexo-yam:** `4b4d3cb342dd9c7c0d6ac78fb86b064eb2fde6ff`, MIT; SVGO 2.4.0 → 3.0.0.

Each transitive npm dependency has its own license; lockfiles do not relicense those packages. Linux evaluation uses the digest-pinned official Node 18 image documented in `cases.json`. The Python and Docker CLI image digests are pinned in `Dockerfile`.

Gemini and Anthropic are hosted services; no model weights or API credentials are redistributed. Live final evaluation uses Gemini; Anthropic is validated with protocol tests only.
