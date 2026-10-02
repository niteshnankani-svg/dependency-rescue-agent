"""Eval-the-evals: inject deliberate faults into the agent and require the suites to notice.

An evaluation that cannot fail proves nothing. Each mutation weakens one real defence (the same defects a careless
refactor could introduce); the named suite must report at least one failed check. The mutation score is killed / total.
"""
import contextlib
from unittest import mock
from langgraph.graph import END
from rescue import graph as g, guards, model, security
from rescue.model import ProviderError
from . import judge as J
from . import suite_judge, suite_protocol, suite_safety, suite_workflow
from .core import Recorder, rate


def _approve_everything(s):
    return {'approved': True, 'status': 'approved', 'events': [{'node': 'approval', 'detail': 'mutant'}]}


def _leaky_status(response):
    if not response.is_success:
        raise ProviderError('Provider HTTP %d: %s' % (response.status_code, response.text))


MUTATIONS = [
    ('injection_screen_disabled', suite_safety.run, lambda: [mock.patch.object(security, 'screen_evidence', lambda *a, **k: None)], 'evidence_screen:'),
    ('credential_detector_disabled', suite_safety.run, lambda: [mock.patch.object(security, 'secret_present', lambda text: False), mock.patch.object(g, 'source_preflight', lambda *a, **k: [])], 'secret'),
    ('capability_check_disabled', suite_safety.run, lambda: [mock.patch.object(guards, 'check_new_capabilities', lambda *a, **k: None), mock.patch.object(security, 'check_new_capabilities', lambda *a, **k: None)], 'capability'),
    ('edit_guard_accepts_anything', suite_safety.run, lambda: [mock.patch.object(guards, 'apply_repair', lambda root, repair, globs=None: [])], 'guard:'),
    ('binding_normaliser_removed', suite_safety.run, lambda: [mock.patch.object(guards, 'normalize_bindings', lambda root, repair, globs=None: (repair, []))], 'binding:'),
    ('provider_error_leaks_body', suite_protocol.run, lambda: [mock.patch.object(model, 'provider_status', _leaky_status)], 'provider_error'),
    ('model_output_not_screened', suite_protocol.run, lambda: [mock.patch.object(model, 'screen_output', lambda text: None)], 'contract:output'),
    ('evidence_not_screened_before_model_call', suite_protocol.run, lambda: [mock.patch.object(model, 'screen_evidence', lambda *a, **k: None)], 'preflight:'),
    ('failed_verification_always_proceeds', suite_workflow.run, lambda: [mock.patch.object(g, 'route_verification', lambda s: 'evidence')], 'workflow'),
    ('approval_ignores_reviewer_decision', suite_workflow.run, lambda: [mock.patch.object(g, 'approval', _approve_everything)], 'rejection'),
    ('integrity_digest_constant', suite_workflow.run, lambda: [mock.patch.object(g, 'protected_digest', lambda *a, **k: 'x'), mock.patch.object(g, 'environment_digest', lambda *a, **k: 'x')], 'tamper'),
    ('export_skips_staleness_checks', suite_workflow.run, lambda: [mock.patch.object(g, 'digest_files', lambda *a, **k: 'x'), mock.patch.object(g, 'protected_digest', lambda *a, **k: 'x'), mock.patch.object(g, 'environment_digest', lambda *a, **k: 'x')], 'after_review'),
    ('retry_budget_ignored', suite_workflow.run, lambda: [mock.patch.object(g, 'route_verification', lambda s: END if s['verification'].get('infrastructure_error') else 'evidence' if s['verification']['ok'] else 'diagnose')], 'budget'),
    ('judge_always_passes', suite_judge.run, lambda: [mock.patch.object(J, 'verdict_from', lambda *a, **k: 'pass')], 'judge_rules'),
    ('judge_ignores_failing_tests', suite_judge.run, lambda: [mock.patch.object(J, 'verdict_from', lambda scores, critical, ok, _real=J.verdict_from: _real(scores, critical, True))], 'judge_rules'),
]


def run():
    rec = Recorder('mutations')
    killed = 0
    for name, suite, patches, hint in MUTATIONS:
        with rec.guard(f'mutation:{name}', tags=['mutation']):
            with contextlib.ExitStack() as stack:
                for patch in patches():
                    stack.enter_context(patch)
                try:
                    result = suite()
                except Exception as exc:  # noqa: BLE001 - a crash under mutation also counts as detection
                    failed = [f'crash: {type(exc).__name__}']
                else:
                    failed = [c.id for c in result.failed]
            detected = bool(failed)
            killed += detected
            rec.check(f'mutation:{name}', detected, f'SURVIVED: suite {suite.__module__.split(".")[-1]} did not notice this fault', tags=['mutation'], failing_checks=failed[:5])
    rec.metric('mutations', len(MUTATIONS))
    rec.metric('mutation_score', rate(killed, len(MUTATIONS)))
    rec.check('gate:mutation_score_is_100pct', killed == len(MUTATIONS), f'{len(MUTATIONS) - killed} injected faults went undetected', tags=['gate'])
    return rec.result
