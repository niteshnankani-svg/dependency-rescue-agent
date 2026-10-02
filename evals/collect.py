"""Turn live run states (runtime/<run_id>/state.json) into judge/RAGAS records.

State files are produced by scripts/evaluate.py. They contain the diagnosis, edits,
API evidence and sources the repair model saw, which committed reports do not.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def window(source, old, pad=6):
    lines = source.splitlines()
    first = old.splitlines()[0] if old.strip() else ''
    at = next((i for i, l in enumerate(lines) if first and first in l), 0)
    lo, hi = max(0, at - pad), min(len(lines), at + len(old.splitlines()) + pad)
    return '\n'.join(f'{i + 1}: {lines[i]}' for i in range(lo, hi))


def record_from_state(state):
    repair = state.get('repair') or {}
    if not repair.get('edits'):
        return None
    case = state['case_id']
    contexts = [json.dumps(e) for e in state.get('api_evidence', [])]
    for edit in repair['edits']:
        contexts.append(f"source {edit['path']}:\n" + window(state['sources'][edit['path']], edit['old']))
    failures = [{'title': f['title'], 'message': f['message'][:800]} for f in (state.get('broken') or {}).get('failures', [])[:5]]
    patch = '\n'.join(f"--- {e['path']}\n- " + e['old'].rstrip().replace('\n', '\n- ') + '\n+ ' + e['new'].rstrip().replace('\n', '\n+ ') for e in repair['edits'])
    return {'id': f"{case}:{state['run_id'][:8]}", 'case_id': case, 'task': f"Repair source incompatibilities for {case} after a dependency upgrade.",
            'failures': failures, 'contexts': contexts + [json.dumps(f) for f in failures], 'diagnosis': repair['diagnosis'], 'patch': patch,
            'outcome_verified': bool((state.get('verification') or {}).get('ok'))}


def collect(runtime=ROOT / 'runtime'):
    records = []
    for path in sorted(Path(runtime).glob('*/state.json')):
        record = record_from_state(json.loads(path.read_text()))
        if record:
            records.append(record)
    return records
