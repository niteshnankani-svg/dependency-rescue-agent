"""Evidence audit: independently re-derive the invariants every recorded live run must satisfy, and cross-check the
published qualification table against the stored run reports. Needs no network, Docker or model.

This evaluates the *recorded evidence* (reports/*-evaluation.json). It cannot prove the runs happened, but it catches
reports that contradict the agent's own rules and documentation that drifted from the measurements.
"""
import json
import re
from pathlib import Path
from rescue.config import ROOT
from rescue.security import secret_present
from .core import Recorder

TERMINAL_OK = {'awaiting_approval', 'approved', 'completed'}
NODE_ORDER = ['intake', 'baseline', 'upgrade', 'reproduce', 'investigate', 'diagnose', 'normalize', 'apply', 'verify', 'evidence']


def load_reports(root=ROOT / 'reports'):
    return {p.name: json.loads(p.read_text()) for p in sorted(root.glob('*-evaluation.json'))}


def audit_run(rec, name, report, case):
    p = f'audit:{name}'
    status = report.get('status')
    rec.check(f'{p}:status_is_known', status in TERMINAL_OK | {'blocked', 'needs_engineer', 'rejected'}, status, tags=['audit'])
    if status in TERMINAL_OK:
        base, broken, ver = report['baseline'], report['broken'], report['verification']
        rec.check(f'{p}:baseline_passed_before_upgrade', base['ok'] and base['tests'] > 0 and base['passes'] == base['tests'], base, tags=['audit'])
        rec.check(f'{p}:regression_reproduced', not broken['ok'] and broken['failures'] and not broken['timed_out'] and not broken.get('infrastructure_error'), 'upgrade did not demonstrably break tests', tags=['audit'])
        rec.check(f'{p}:repair_passes_all_tests', ver['ok'] and ver['passes'] == ver['tests'] == base['tests'], f"{ver['passes']}/{ver['tests']} vs baseline {base['tests']}", tags=['audit'])
        rec.check(f'{p}:integrity_intact', ver.get('integrity_ok') is True, ver.get('integrity_ok'), tags=['audit'])
        rec.check(f'{p}:upgraded_version_exact', case is not None and ver.get('dependency_version') == case['target_version'], f"{ver.get('dependency_version')} vs {case and case['target_version']}", tags=['audit'])
        extras = ver.get('additional_checks', [])
        rec.check(f'{p}:additional_checks_passed', all(c['ok'] and not c['timed_out'] and not c.get('infrastructure_error') for c in extras), extras, tags=['audit'])
        rec.check(f'{p}:isolation_recorded', all('no network' in (r.get('isolation') or '') for r in (base, broken, ver)), 'a phase lacks recorded offline isolation', tags=['audit', 'isolation'])
    attempts, calls = report.get('attempts'), report.get('model_calls', [])
    max_attempts = (case or {}).get('max_attempts', 3)
    rec.check(f'{p}:within_attempt_budget', isinstance(attempts, int) and 1 <= attempts <= max_attempts, f'attempts={attempts} budget={max_attempts}', tags=['audit'])
    rec.check(f'{p}:one_model_call_per_attempt', len(calls) == attempts, f'{len(calls)} calls for {attempts} attempts', tags=['audit'])
    if status in TERMINAL_OK:
        rec.check(f'{p}:final_proposal_schema_valid', bool(calls) and calls[-1].get('valid') is True, calls[-1:] , tags=['audit'])
    rec.check(f'{p}:model_identified', all(c.get('provider') and c.get('model') for c in calls), 'call without provider/model', tags=['audit'])
    rec.check(f'{p}:reference_solution_not_accessed', report.get('reference_solution_accessed') is False, report.get('reference_solution_accessed'), tags=['audit', 'contamination'])
    nodes = [e['node'] for e in report.get('events', [])]
    if status in TERMINAL_OK:
        positions = [nodes.index(n) if n in nodes else -1 for n in NODE_ORDER]
        rec.check(f'{p}:trace_follows_graph_order', all(i >= 0 for i in positions) and positions == sorted(positions), nodes, tags=['audit'])
    rec.check(f'{p}:no_credentials_in_report', not secret_present(json.dumps(report)), 'credential-like text in stored report', tags=['audit', 'secrets'])
    rec.check(f'{p}:no_absolute_host_paths', str(ROOT) not in json.dumps(report) and '/Users/' not in json.dumps(report), 'host path leaked', tags=['audit', 'secrets'])
    rec.check(f'{p}:held_out_status_not_overclaimed', 'not held out' in str(report.get('independent_verifier', '')) or 'not yet run' in str(report.get('independent_verifier', '')) or 'held out' not in str(report.get('independent_verifier', '')), report.get('independent_verifier'), tags=['audit', 'honesty'])


def claims_vs_reports(rec, reports, cases):
    text = (ROOT / 'VALIDATION.md').read_text()
    rows = [line for line in text.splitlines() if re.match(r'^\|\s*(?!Dependency|---)', line) and '→' in line]
    rec.check('claims:validation_table_present', len(rows) >= 1, 'no qualification table in VALIDATION.md', tags=['audit', 'claims'])
    by_dep = {c['dependency'].lower(): c for c in cases}
    for row in rows:
        cells = [c.strip() for c in row.strip('|').split('|')]
        dep = next((d for d in by_dep if d in cells[0].lower()), None)
        if not dep:
            rec.check(f'claims:{cells[0][:30]}:maps_to_case', False, cells[0], tags=['audit', 'claims'])
            continue
        report = reports.get(f"{by_dep[dep]['id']}-evaluation.json")
        if not report:
            rec.check(f"claims:{by_dep[dep]['id']}:report_exists", False, 'no stored report', tags=['audit', 'claims'])
            continue
        m = lambda s: re.match(r'(\d+)/(\d+)', s)
        base, broken, fixed = m(cells[1]), m(cells[2]), m(cells[3])
        cid = by_dep[dep]['id']
        if base:
            rec.check(f'claims:{cid}:baseline_matches', (int(base[1]), int(base[2])) == (report['baseline']['passes'], report['baseline']['tests']), f"doc {base[0]} vs report {report['baseline']['passes']}/{report['baseline']['tests']}", tags=['audit', 'claims'])
        if broken:
            rec.check(f'claims:{cid}:broken_matches', (int(broken[1]), int(broken[2])) == (report['broken']['passes'], report['broken']['tests']), f"doc {broken[0]} vs report {report['broken']['passes']}/{report['broken']['tests']}", tags=['audit', 'claims'])
        if fixed:
            rec.check(f'claims:{cid}:repaired_matches', (int(fixed[1]), int(fixed[2])) == (report['verification']['passes'], report['verification']['tests']), f"doc {fixed[0]} vs report", tags=['audit', 'claims'])
        attempts = re.search(r'\d+', cells[4]) if len(cells) > 4 else None
        if attempts:
            rec.check(f'claims:{cid}:attempts_match', int(attempts[0]) == report['attempts'], f"doc {attempts[0]} vs report {report['attempts']}", tags=['audit', 'claims'])
    qualification = ROOT / 'reports/artifact-qualification.json'
    if qualification.exists():
        for item in json.loads(qualification.read_text()):
            rec.check(f"claims:{item['case_id']}:patch_applies_to_pristine_source", item.get('patch_applies_to_pristine_base') and item.get('patched_files_equal_verified_files') and item.get('additional_checks_passed'), item, tags=['audit', 'claims'])
            report = reports.get(f"{item['case_id']}-evaluation.json")
            rec.check(f"claims:{item['case_id']}:qualification_matches_run", report is not None and report['run_id'] == item['run_id'], f"qualification run {item['run_id']} vs report {report and report['run_id']}", tags=['audit', 'claims'])


def run():
    rec = Recorder('audit')
    reports = load_reports()
    if not reports:
        rec.skip('audit:reports', 'no reports/*-evaluation.json in this checkout')
        return rec.result
    cases = json.loads((ROOT / 'cases.json').read_text())
    by_id = {c['id']: c for c in cases}
    for name, report in reports.items():
        with rec.guard(f'audit:{name}', tags=['audit']):
            audit_run(rec, name, report, by_id.get(report.get('case_id')))
    with rec.guard('claims', tags=['audit']):
        claims_vs_reports(rec, reports, cases)
    rec.metric('runs_audited', len(reports))
    rec.metric('runs_awaiting_review_or_done', sum(1 for r in reports.values() if r.get('status') in TERMINAL_OK))
    return rec.result
