"""Evaluator setup; fetches pinned verifier inputs, never reference solutions."""
import json
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'research/depbench-manifest.json').read_text())
folder = 'chris48s__v8r__22'
dest = root / 'data/external/depbench' / folder / 'tests'
dest.mkdir(exist_ok=True)
with httpx.Client(timeout=45, follow_redirects=True) as client:
    for name in ['test.patch', 'test.sh', 'test_state.py']:
        url = f"https://huggingface.co/datasets/{manifest['repo']}/resolve/{manifest['revision']}/dataset/tasks/{folder}/tests/{name}"
        r = client.get(url)
        r.raise_for_status()
        (dest / name).write_text(r.text)
print('Pinned verifier saved outside agent context. No solution downloaded.')
