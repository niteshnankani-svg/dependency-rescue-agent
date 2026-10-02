"""Shared test harness: an isolated data root with every fixture prepared, and HTTP mocking for provider adapters."""
import contextlib
import json
import shutil
import tempfile
from pathlib import Path
import httpx
from rescue import config, model
from . import fixtures


class Sandbox:
    """Temp data root laid out like data/external, with config.DATA and the case registry pointed at it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix='rescue-eval-'))
        self._saved = None

    def __enter__(self):
        import os
        for fixture in fixtures.FIXTURES:
            fixtures.build_templates(fixture, self.root / 'data')
        (self.root / 'cases.json').write_text(json.dumps([f.case() for f in fixtures.FIXTURES]))
        self._saved = (config.DATA, os.environ.get('RESCUE_CASES_FILE'))
        config.DATA = (self.root / 'data').resolve()
        os.environ['RESCUE_CASES_FILE'] = str(self.root / 'cases.json')
        return self

    def __exit__(self, *exc):
        import os
        config.DATA = self._saved[0]
        if self._saved[1] is None:
            os.environ.pop('RESCUE_CASES_FILE', None)
        else:
            os.environ['RESCUE_CASES_FILE'] = self._saved[1]
        shutil.rmtree(self.root, ignore_errors=True)

    @property
    def data(self):
        return self.root / 'data'

    def case(self, fixture_id):
        return config.get_case(fixture_id)

    def workspace(self, fixture_id, name='ws', phase='upgraded'):
        target = self.root / 'work' / f'{fixture_id}-{name}'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.data / 'templates' / fixture_id / phase, target, symlinks=True)
        return target


_REAL_CLIENT = httpx.Client  # captured at import so nested mocks never wrap each other


class Provider:
    """Records every request the agent makes and answers via a handler(request) -> httpx.Response."""

    def __init__(self, handler):
        self.requests = []
        self.handler = handler

    def __enter__(self):
        def respond(request):
            self.requests.append(request)
            return self.handler(request)
        self._original = model.httpx.Client  # model.httpx is the global httpx module
        model.httpx.Client = lambda **kwargs: _REAL_CLIENT(transport=httpx.MockTransport(respond))
        return self

    def __exit__(self, *exc):
        model.httpx.Client = self._original

    def body(self, index=-1):
        return json.loads(self.requests[index].content)


def wire_edits(workspace, edits):
    """Convert exact old/new edits into the half-open numbered-range wire format the model must return."""
    wire = []
    for edit in edits:
        text = (Path(workspace) / edit['path']).read_text()
        start = text.index(edit['old'])
        first = text.count('\n', 0, start) + 1
        wire.append({'path': edit['path'], 'start_line': first, 'end_line': first + edit['old'].count('\n'), 'new': edit['new']})
    return wire


def provider_response(provider, content):
    """Minimal successful response body for each provider adapter."""
    text = content if isinstance(content, str) else json.dumps(content)
    if provider == 'ollama':
        return {'message': {'content': text}, 'prompt_eval_count': 11, 'eval_count': 7, 'done_reason': 'stop', 'total_duration': 2_000_000_000}
    if provider == 'gemini':
        return {'candidates': [{'content': {'parts': [{'text': 'hidden', 'thought': True}, {'text': text}]}, 'finishReason': 'STOP'}], 'usageMetadata': {'promptTokenCount': 11, 'candidatesTokenCount': 7, 'thoughtsTokenCount': 3}}
    if provider == 'anthropic':
        return {'content': [{'type': 'text', 'text': text}], 'usage': {'input_tokens': 11, 'output_tokens': 7}, 'stop_reason': 'end_turn'}
    if provider == 'chat-completions':
        return {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 7}}
    raise ValueError(provider)


@contextlib.contextmanager
def noop():
    yield
