# Evaluation suite

| Layer | File | Needs |
| --- | --- | --- |
| Application tests | `tests/` | nothing |
| Outcome, process, safety checks over recorded runs | `deterministic.py` | nothing (reads `reports/`) |
| Harness self-tests (metrics can fail) | `tests/test_evals.py` | nothing |
| LLM-as-judge calibration (7 synthetic good/bad repairs) | `calibration.py`, `judge.py` | `GEMINI_API_KEY` |
| LLM-as-judge on real repairs (5 rubric dimensions) | `judge.py`, `collect.py` | key + live run states |
| RAGAS: Faithfulness, ContextPrecision, AspectCritic | `ragas_run.py` | key + live run states |

```sh
uv venv --python 3.12 .venv-eval && uv pip install --python .venv-eval/bin/python -r evals/requirements.txt
.venv-eval/bin/python scripts/with_env.py .venv-eval/bin/python scripts/evaluate.py   # live runs (Docker + key); writes runtime/*/state.json
.venv-eval/bin/python scripts/with_env.py .venv-eval/bin/python evals/run_all.py      # writes reports/eval-suite.json, EVAL_REPORT.md
```

Set `JUDGE_MODEL` (default `gemini-2.5-pro`) to judge with a different model than the generator (`gemini-3.1-pro-preview`) to limit self-preference bias. Sections that cannot run report `skipped` with the reason; `overall` is `INCOMPLETE`, never `PASSED`, until every section ran.
