"""Minimal check recorder, environment isolation and report writers shared by all suites."""
import contextlib
import json
import os
import time
import traceback
from dataclasses import dataclass, field, asdict

# Provider and credential variables that must never leak into offline suites.
MODEL_ENV = ['RESCUE_MODEL_PROVIDER', 'RESCUE_MODEL', 'RESCUE_MODEL_URL', 'RESCUE_MODEL_API_KEY', 'RESCUE_MODEL_THINKING',
             'RESCUE_MODEL_TIMEOUT', 'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'ANTHROPIC_API_KEY', 'RESCUE_ENV', 'RESCUE_SERIAL_COLIMA']


@contextlib.contextmanager
def env(**values):
    """Temporarily set (str) or delete (None) environment variables."""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def clean_model_env(**extra):
    """Environment override that removes every model credential, then applies `extra`."""
    return env(**{**{k: None for k in MODEL_ENV}, **extra})


@dataclass
class Check:
    suite: str
    id: str
    passed: bool
    detail: str = ''
    tags: list = field(default_factory=list)
    skipped: bool = False
    xfail: str = ''   # known defect: failure is reported but does not gate; an unexpected pass does
    data: dict = field(default_factory=dict)


@dataclass
class SuiteResult:
    name: str
    checks: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    skipped: str = ''
    seconds: float = 0.0

    @property
    def failed(self):
        return [c for c in self.checks if not c.skipped and ((not c.passed and not c.xfail) or (c.passed and c.xfail))]

    @property
    def passed(self):
        return [c for c in self.checks if c.passed and not c.skipped and not c.xfail]

    @property
    def known_defects(self):
        return [c for c in self.checks if c.xfail and not c.passed]


class Recorder:
    """Collects checks for one suite. Unexpected exceptions become failed checks, never crashes."""

    def __init__(self, suite):
        self.result = SuiteResult(suite)

    def check(self, id, condition, detail='', tags=None, xfail='', **data):
        self.result.checks.append(Check(self.result.name, id, bool(condition), ('xpass: remove xfail' if xfail else '') if condition else str(detail), tags or [], xfail=xfail, data=data))
        return bool(condition)

    def info(self, id, tags=None, **data):
        """Informational measurement: always recorded as passed, never gates the run."""
        self.result.checks.append(Check(self.result.name, id, True, '', tags or [], data={'informational': True, **data}))

    def skip(self, id, reason, tags=None):
        self.result.checks.append(Check(self.result.name, id, False, reason, tags or [], skipped=True))

    @contextlib.contextmanager
    def guard(self, id, tags=None):
        """Turn an unexpected exception inside the block into one failed check."""
        try:
            yield
        except Exception as exc:  # noqa: BLE001 - an eval must report, not crash
            self.check(id, False, f'unexpected {type(exc).__name__}: {str(exc)[:300]}', tags, traceback=traceback.format_exc()[-1500:])

    def metric(self, name, value):
        self.result.metrics[name] = value


def timed(fn, *args, **kwargs):
    start = time.monotonic()
    result = fn(*args, **kwargs)
    result.seconds = round(time.monotonic() - start, 2)
    return result


def rate(num, den):
    return round(num / den, 4) if den else None


def wilson_upper(k, n, z=1.96):
    """Upper bound of the 95% Wilson interval for k events in n trials. 0/28 is not 'zero risk'; it is <= ~12%."""
    if not n:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return round(min(1.0, (centre + margin) / (1 + z * z / n)), 4)


def confusion(rows):
    """rows: (expected_positive, predicted_positive). Returns precision/recall/FPR."""
    tp = sum(1 for e, p in rows if e and p)
    fp = sum(1 for e, p in rows if not e and p)
    fn = sum(1 for e, p in rows if e and not p)
    tn = sum(1 for e, p in rows if not e and not p)
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': rate(tp, tp + fp), 'recall': rate(tp, tp + fn), 'false_positive_rate': rate(fp, fp + tn)}


def load(name):
    with open(os.path.join(os.path.dirname(__file__), 'datasets', name)) as handle:
        return json.load(handle)
