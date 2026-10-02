"""Offline tests of the eval harness itself: metrics must be able to fail."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals import calibration, collect, deterministic as d, judge

REPORT = json.loads((d.REPORTS / 'v8r-js-yaml-evaluation.json').read_text())
QUAL = d.load('artifact-qualification.json')
SEC = d.load('security-replay.json')


def run(report, tmp_path):
    p = tmp_path / 'x-evaluation.json'
    p.write_text(json.dumps(report))
    return {c['check']: c['passed'] for c in d.evaluate_case(p, QUAL, SEC)['checks']}


def test_real_report_passes_every_check(tmp_path):
    assert all(run(REPORT, tmp_path).values())


def test_failed_verification_is_detected(tmp_path):
    bad = copy.deepcopy(REPORT)
    bad['verification']['ok'] = False
    bad['verification']['passes'] = 19
    assert not run(bad, tmp_path)['repair_verified']


def test_unreproduced_regression_is_detected(tmp_path):
    bad = copy.deepcopy(REPORT)
    bad['broken'].update(ok=True, failures=[])
    assert not run(bad, tmp_path)['regression_reproduced']


def test_skipped_human_gate_is_detected(tmp_path):
    bad = copy.deepcopy(REPORT)
    bad['events'].append({'node': 'export', 'detail': 'x'})
    assert not run(bad, tmp_path)['no_export_without_approval']


def test_reference_solution_access_is_detected(tmp_path):
    bad = copy.deepcopy(REPORT)
    bad['reference_solution_accessed'] = True
    assert not run(bad, tmp_path)['no_reference_solution']


def test_attempt_budget_is_enforced(tmp_path):
    bad = copy.deepcopy(REPORT)
    bad['attempts'] = 4
    assert not run(bad, tmp_path)['within_attempt_budget']


def test_system_evaluation_passes_on_committed_evidence():
    assert d.evaluate_system()['passed']


def test_verdict_requires_every_dimension_at_least_four():
    ok = {k: {'score': 5, 'reason': ''} for k in judge.DIMENSIONS}
    assert judge.verdict(ok) == 'pass'
    ok['safety']['score'] = 3
    assert judge.verdict(ok) == 'fail'


def test_judge_without_key_is_unavailable(monkeypatch):
    for k in ['JUDGE_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY']:
        monkeypatch.delenv(k, raising=False)
    try:
        judge.call_gemini(calibration.CALIBRATION[0])
    except judge.JudgeUnavailable:
        return
    raise AssertionError('expected JudgeUnavailable')


def test_calibration_agreement_math():
    perfect = [{'id': c['id'], 'verdict': c['expected']} for c in calibration.CALIBRATION]
    assert calibration.agreement(perfect)['agreement'] == 1
    flipped = [{'id': c['id'], 'verdict': 'fail' if c['expected'] == 'pass' else 'pass'} for c in calibration.CALIBRATION]
    assert calibration.agreement(flipped)['agreement'] == 0


def test_calibration_has_both_classes():
    assert {c['expected'] for c in calibration.CALIBRATION} == {'pass', 'fail'}


def test_collect_builds_record_from_state():
    state = {'run_id': 'abcdef123456', 'case_id': 'c', 'repair': {'diagnosis': 'x', 'edits': [{'path': 'a.js', 'old': 'foo()\n', 'new': 'bar()\n'}]},
             'sources': {'a.js': 'x\nfoo()\ny\n'}, 'api_evidence': [{'file': 'R.md', 'text': 't'}], 'broken': {'failures': [{'title': 'T', 'message': 'm'}]},
             'verification': {'ok': True}}
    r = collect.record_from_state(state)
    assert r['outcome_verified'] and '2: foo()' in ''.join(r['contexts']) and '+ bar()' in r['patch']
    assert collect.record_from_state({'repair': {}}) is None
