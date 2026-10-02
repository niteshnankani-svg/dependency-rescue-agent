"""Command line entry point: `python -m evals.run`.

Default is the free, deterministic, offline tier (safety, protocol, workflow, audit, mutations, judge machinery).
  --judge        also calibrate the LLM judge on the labelled patch set (needs a judge API key)
  --live         also run the real model on the fixtures, judge the results, and run adversarial injections
  --all          everything above
Exit status: 1 if any gating check fails; 3 if --require-live and a live tier was inconclusive (provider outage/quota,
which is never counted as pass or fail); otherwise 0.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import core, fixtures, judge as J  # noqa: E402
from evals import suite_safety, suite_protocol, suite_workflow, suite_audit, suite_judge, suite_live, suite_mutations  # noqa: E402
from evals.core import SuiteResult, Check  # noqa: E402

OFFLINE = ['safety', 'protocol', 'workflow', 'audit', 'mutations']


def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ''


def build_judge(args):
    try:
        judge = J.Judge(provider=args.judge_provider, model=args.judge_model, trust_env=args.trust_env)
        return judge, ''
    except J.JudgeError as exc:
        return None, str(exc)


def markdown(report):
    out = [f"# Dependency Rescue evaluation report\n", f"- Run: {report['meta']['started']} · commit `{report['meta']['commit'][:12] or 'unknown'}` · Python {report['meta']['python']} · Node {report['meta']['node']}",
           f"- Tiers: {', '.join(report['meta']['tiers'])}", f"- Verdict: **{'PASS' if report['summary']['ok'] else 'FAIL'}**{' (live tier inconclusive)' if any(c['skipped'] and 'inconclusive' in c['tags'] for s in report['suites'] for c in s['detail']) else ''}\n", '## Suites\n',
           '| Suite | Checks | Passed | Failed | Known defects | Skipped | Seconds |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in report['suites']:
        out.append(f"| {s['name']} | {s['checks']} | {s['passed']} | {s['failed']} | {s['known_defects']} | {s['skipped']} | {s['seconds']} |")
    gates = [c for s in report['suites'] for c in s['detail'] if 'gate' in c['tags']]
    if gates:
        out += ['\n## Gates\n', '| Gate | Result | Detail |', '| --- | --- | --- |']
        out += [f"| {c['suite']}:{c['id'].replace('gate:', '')} | {'pass' if c['passed'] else 'FAIL'} | {c['detail'] or ''} |" for c in gates]
    failed = [c for s in report['suites'] for c in s['detail'] if c['failed']]
    inconclusive = [c for s in report['suites'] for c in s['detail'] if c['skipped'] and 'inconclusive' in c['tags']]
    if inconclusive:
        out.append('\n## Inconclusive (provider unavailable; neither pass nor fail)\n')
        out += [f"- `{c['suite']}:{c['id']}`: {c['detail']}" for c in inconclusive[:20]]
    out.append('\n## Failures\n' if failed else '\n## Failures\n\nNone.')
    out += [f"- `{c['suite']}:{c['id']}` {c['detail']}" for c in failed[:60]]
    defects = [c for s in report['suites'] for c in s['detail'] if c.get('xfail') and not c['passed']]
    if defects:
        out.append('\n## Known defects (tracked, non-gating)\n')
        out += [f"- `{c['suite']}:{c['id']}`: {c['xfail']}" for c in defects]
    skipped = [c for s in report['suites'] for c in s['detail'] if c['skipped'] and 'inconclusive' not in c['tags']]
    if skipped:
        out.append('\n## Skipped\n')
        out += [f"- `{c['suite']}:{c['id']}`: {c['detail']}" for c in skipped]
    out.append('\n## Metrics\n')
    for s in report['suites']:
        for name, value in s['metrics'].items():
            out.append(f"- **{s['name']}.{name}**: `{json.dumps(value)}`")
    hard = [c for s in report['suites'] for c in s['detail'] if c['data'].get('informational') and 'hard' in c['tags']]
    if hard:
        out.append('\n## Hard adversarial cases (informational: heuristics are not expected to catch all)\n')
        out += [f"- {'detected' if c['data']['detected'] else 'MISSED'}: `{c['id']}`" for c in hard]
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--suites', default=','.join(OFFLINE + ['judge']), help='comma list from: safety,protocol,workflow,audit,mutations,judge,live')
    ap.add_argument('--judge', action='store_true', help='calibrate the LLM judge live (API key needed)')
    ap.add_argument('--live', action='store_true', help='run the real model on fixtures + adversarial injections, graded by the judge')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--judge-provider', choices=['gemini', 'anthropic', 'chat-completions'])
    ap.add_argument('--judge-model')
    ap.add_argument('--judge-samples', type=int, default=1, help='judge each item N times and take the majority')
    ap.add_argument('--trials', type=int, default=1, help='live runs per fixture')
    ap.add_argument('--min-pass-rate', type=float, default=0.75, help='gate on live completion rate')
    ap.add_argument('--trust-env', action='store_true', help='honour HTTPS_PROXY/SSL_CERT_FILE for live calls (eval-only)')
    ap.add_argument('--out', default=str(ROOT / 'reports/evals'))
    ap.add_argument('--require-live', action='store_true', help='exit 3 if a requested live tier was inconclusive (provider outage/quota)')
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args(argv)

    suites = [s for s in args.suites.split(',') if s]
    if args.all:
        args.judge = args.live = True
    if args.live and 'live' not in suites:
        suites.append('live')
    started = time.monotonic()
    results, tiers = [], []
    judge, judge_problem = (None, '')
    if args.judge or args.live:
        judge, judge_problem = build_judge(args)
    for name in suites:
        print(f'== {name}', flush=True)
        if name == 'safety':
            result = core.timed(suite_safety.run)
        elif name == 'protocol':
            result = core.timed(suite_protocol.run)
        elif name == 'workflow':
            result = core.timed(suite_workflow.run)
        elif name == 'audit':
            result = core.timed(suite_audit.run)
        elif name == 'mutations':
            result = core.timed(suite_mutations.run)
        elif name == 'judge':
            result = core.timed(suite_judge.run, judge if args.judge else None, args.judge_samples)
            if args.judge and not judge:
                result.checks.append(Check('judge', 'judge:live_calibration', False, judge_problem, ['judge'], skipped=True))
        elif name == 'live':
            result = core.timed(suite_live.run, judge, args.trials, args.trust_env, args.judge_samples, args.min_pass_rate)
        else:
            raise SystemExit(f'unknown suite {name}')
        results.append(result)
        print(f'   {len(result.passed)} passed, {len(result.failed)} failed, {len(result.known_defects)} known defects, '
              f'{len([c for c in result.checks if c.skipped])} skipped ({result.seconds}s)', flush=True)
        for c in result.failed[:15]:
            print(f'   FAIL {c.id}: {str(c.detail)[:200]}', flush=True)
    tiers = ['offline'] + (['judge-live'] if args.judge and judge else []) + (['agent-live'] if 'live' in suites else [])
    live_agent = next((r for r in results if r.name == 'live'), None)
    if judge and live_agent and live_agent.metrics.get('live.model'):
        agent = {'provider': live_agent.metrics['live.provider'], 'model': live_agent.metrics['live.model']}
        independent = not J.same_family(agent, {'provider': judge.provider, 'model': judge.model})
        live_agent.metrics['judge.independent_of_agent'] = independent
        if not independent:
            live_agent.metrics['judge.warning'] = 'judge and agent share a provider/model family: expect self-preference bias; prefer a different family'
    meta = {'started': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ'), 'commit': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain')),
            'python': platform.python_version(), 'node': (fixtures.NODE and subprocess.run([fixtures.NODE, '--version'], capture_output=True, text=True).stdout.strip()) or 'missing',
            'tiers': tiers, 'elapsed_seconds': round(time.monotonic() - started, 1), 'judge': f'{judge.provider}:{judge.model}' if judge else None}
    report = {'meta': meta, 'summary': {'ok': not any(r.failed for r in results), 'checks': sum(len(r.checks) for r in results), 'failed': sum(len(r.failed) for r in results)},
              'suites': [{'name': r.name, 'checks': len([c for c in r.checks if not c.skipped]), 'passed': len(r.passed), 'failed': len(r.failed), 'known_defects': len(r.known_defects),
                          'skipped': len([c for c in r.checks if c.skipped]), 'seconds': r.seconds, 'metrics': r.metrics,
                          'detail': [{**{k: v for k, v in c.__dict__.items() if k != 'data'}, 'failed': c in r.failed, 'data': {k: v for k, v in c.data.items() if k != 'traceback'} if c.data.get('informational') or c.data.get('run') or c.data.get('scores') else {}} for c in r.checks]}
                         for r in results]}
    text = json.dumps(report, indent=1, default=str)
    from rescue.security import secret_present
    if secret_present(text):
        raise SystemExit('refusing to write a report that contains credential-like text')
    if not args.no_write:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'latest.json').write_text(text + '\n')
        (out / 'latest.md').write_text(markdown(report))
        print(f'report: {out / "latest.md"}')
    inconclusive = [c for r in results for c in r.checks if c.skipped and 'inconclusive' in c.tags]
    print(f"\n{'PASS' if report['summary']['ok'] else 'FAIL'}: {report['summary']['checks']} checks, {report['summary']['failed']} failed")
    if inconclusive:
        print(f'INCONCLUSIVE: {len(inconclusive)} live check(s) could not be evaluated (provider unavailable); see the report. Not counted as pass or fail.')
    if not report['summary']['ok']:
        return 1
    return 3 if inconclusive and args.require_live else 0


if __name__ == '__main__':
    sys.exit(main())
