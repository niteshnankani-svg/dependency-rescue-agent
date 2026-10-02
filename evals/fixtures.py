"""Synthetic, self-contained dependency-upgrade fixtures with a sandboxed local Node test runner.

Each fixture models one realistic upgrade break (removed default export, sync -> async API, option rename,
multi-file consumer). Tests are identical before and after the upgrade, exactly like a real regression.
Only trusted fixture code is executed, under Node's permission model (read-only, no network, no child processes).
"""
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

NODE = os.getenv('RESCUE_EVAL_NODE') or shutil.which('node') or ''

RUNNER = r"""const tests = [];
const t = (title, fn) => tests.push([title, fn]);
const assert = require('assert');
%TESTS%
(async () => {
  const failures = [];
  let passes = 0;
  for (const [title, fn] of tests) {
    try { await fn(); passes++; }
    catch (e) { failures.push({ title, message: String(e && e.message), stack: String(e && e.stack).split('\n').slice(0, 4).join('\n') }); }
  }
  console.log(JSON.stringify({ tests: tests.length, passes, failures }));
  process.exit(failures.length ? 1 : 0);
})();
"""

CACHE_V1 = "module.exports = class Cache {\n  constructor() { this.m = new Map(); }\n  set(k, v) { this.m.set(k, v); }\n  get(k) { return this.m.get(k); }\n};\n"
CACHE_V2 = "class Cache {\n  constructor() { this.m = new Map(); }\n  set(k, v) { this.m.set(k, v); }\n  get(k) { return this.m.get(k); }\n}\nexports.Cache = Cache;\n"
CACHE_README_V1 = "# widget\n\n```js\nconst Cache = require('widget');\nconst cache = new Cache();\n```\n"
CACHE_README_V2 = "# widget\n\n## 2.0.0 breaking changes\n\n- The default export was removed. Import the named export instead: `const { Cache } = require('widget');`\n\n```js\nconst { Cache } = require('widget');\nconst cache = new Cache();\n```\n"


@dataclass
class Fixture:
    id: str
    summary: str                      # reference description of the upgrade break; shown to the judge only
    sources: dict                     # path -> content (editable source)
    tests: str                        # JS test bodies
    widget_v1: dict                   # path -> content for node_modules/widget at 1.0.0
    widget_v2: dict
    gold: list                        # [{'path','old','new'}] reference repair (never shown to the agent)
    gold_diagnosis: str
    max_edits: int = 3
    extra: dict = field(default_factory=dict)

    def case(self):
        return {'id': self.id, 'repository': f'eval/{self.id}', 'base_commit': 'a' * 40, 'dependency': 'widget', 'old_version': '1.0.0',
                'target_version': '2.0.0', 'template_dir': f'templates/{self.id}', 'source_globs': ['src/*.js'],
                'test_args': ['node', 'test/run.js'], 'max_edits': self.max_edits, 'max_attempts': 3, 'evaluation_role': 'synthetic eval fixture'}


def _widget(version, files):
    manifest = {'name': 'widget', 'version': version, 'main': 'index.js'}
    return {'package.json': json.dumps(manifest), **files}


FIXTURES = [
    Fixture(
        id='rename-export',
        summary="widget 2.0.0 removed the default export; `Cache` is now a named export (`const { Cache } = require('widget')`). Behaviour is otherwise identical.",
        sources={'src/store.js': "const Cache = require('widget');\nconst cache = new Cache();\n\nfunction save(key, value) {\n  cache.set(key, value);\n  return value;\n}\n\nfunction load(key) {\n  return cache.get(key);\n}\n\nmodule.exports = { save, load };\n"},
        tests="const store = () => require('../src/store');\nt('round trip', () => { const { save, load } = store(); save('a', 1); assert.strictEqual(load('a'), 1); });\nt('missing key', () => assert.strictEqual(store().load('zzz'), undefined));\nt('overwrite', () => { const { save, load } = store(); save('k', 1); save('k', 2); assert.strictEqual(load('k'), 2); });\n",
        widget_v1=_widget('1.0.0', {'index.js': CACHE_V1, 'README.md': CACHE_README_V1}),
        widget_v2=_widget('2.0.0', {'index.js': CACHE_V2, 'README.md': CACHE_README_V2}),
        gold=[{'path': 'src/store.js', 'old': "const Cache = require('widget');\n", 'new': "const { Cache } = require('widget');\n"}],
        gold_diagnosis="widget 2.0 removed the default export, so require('widget') is no longer a constructor. Switch to the named export Cache.", max_edits=1),
    Fixture(
        id='async-api',
        summary="widget 2.0.0 made `Reader#read(key)` asynchronous: it now returns a Promise instead of a string. Callers must await it.",
        sources={'src/format.js': "const { Reader } = require('widget');\nconst reader = new Reader();\n\nfunction describe(key) {\n  const value = reader.read(key);\n  return value.toUpperCase();\n}\n\nmodule.exports = { describe };\n"},
        tests="const fmt = () => require('../src/format');\nt('upper', async () => assert.strictEqual(await fmt().describe('a'), 'V:A'));\nt('longer key', async () => assert.strictEqual(await fmt().describe('ab'), 'V:AB'));\n",
        widget_v1=_widget('1.0.0', {'index.js': "class Reader { read(k) { return 'v:' + k; } }\nexports.Reader = Reader;\n", 'README.md': "# widget\n\n`reader.read(key)` returns a string.\n"}),
        widget_v2=_widget('2.0.0', {'index.js': "class Reader { async read(k) { return 'v:' + k; } }\nexports.Reader = Reader;\n", 'README.md': "# widget\n\n## 2.0.0 breaking changes\n\n- `reader.read(key)` is now asynchronous and returns a Promise<string>. Use `await reader.read(key)`.\n"}),
        gold=[{'path': 'src/format.js', 'old': "function describe(key) {\n  const value = reader.read(key);\n  return value.toUpperCase();\n}\n", 'new': "async function describe(key) {\n  const value = await reader.read(key);\n  return value.toUpperCase();\n}\n"}],
        gold_diagnosis="Reader#read became async. The caller treats the Promise as a string. Make describe async and await the read.", max_edits=1),
    Fixture(
        id='option-rename',
        summary="widget 2.0.0 renamed the `level` option of `compress()` to `compressionLevel`. Unknown options are silently ignored, so behaviour changes without an error.",
        sources={'src/pack.js': "const { compress } = require('widget');\n\nfunction pack(text) {\n  return compress(text, { level: 3 });\n}\n\nmodule.exports = { pack };\n"},
        tests="const pack = (s) => require('../src/pack').pack(s);\nt('drops three chars', () => assert.strictEqual(pack('abcdef'), 'abc'));\nt('short input', () => assert.strictEqual(pack('abcd'), 'a'));\n",
        widget_v1=_widget('1.0.0', {'index.js': "exports.compress = (s, { level = 1 } = {}) => s.slice(0, s.length - level);\n", 'README.md': "# widget\n\n`compress(text, { level })` drops `level` trailing characters.\n"}),
        widget_v2=_widget('2.0.0', {'index.js': "exports.compress = (s, { compressionLevel = 1 } = {}) => s.slice(0, s.length - compressionLevel);\n", 'README.md': "# widget\n\n## 2.0.0 breaking changes\n\n- The `level` option of `compress()` was renamed to `compressionLevel`. Unknown options are ignored.\n"}),
        gold=[{'path': 'src/pack.js', 'old': "  return compress(text, { level: 3 });\n", 'new': "  return compress(text, { compressionLevel: 3 });\n"}],
        gold_diagnosis="The level option was renamed compressionLevel in widget 2.0 and unknown options are ignored, so the default level was applied.", max_edits=1),
    Fixture(
        id='multi-site',
        summary="widget 2.0.0 removed the default export; `Cache` is a named export. Two separate source files import the default and both must change.",
        sources={
            'src/store.js': "const Cache = require('widget');\nconst cache = new Cache();\n\nfunction save(key, value) {\n  cache.set(key, value);\n  return value;\n}\n\nmodule.exports = { save, cache };\n",
            'src/audit.js': "const Cache = require('widget');\nconst seen = new Cache();\n\nfunction record(user) {\n  seen.set(user, true);\n  return seen.get(user);\n}\n\nmodule.exports = { record };\n"},
        tests="t('store', () => assert.strictEqual(require('../src/store').save('a', 5), 5));\nt('audit', () => assert.strictEqual(require('../src/audit').record('bob'), true));\n",
        widget_v1=_widget('1.0.0', {'index.js': CACHE_V1, 'README.md': CACHE_README_V1}),
        widget_v2=_widget('2.0.0', {'index.js': CACHE_V2, 'README.md': CACHE_README_V2}),
        gold=[{'path': 'src/store.js', 'old': "const Cache = require('widget');\n", 'new': "const { Cache } = require('widget');\n"},
              {'path': 'src/audit.js', 'old': "const Cache = require('widget');\n", 'new': "const { Cache } = require('widget');\n"}],
        gold_diagnosis="The default export was removed in widget 2.0; both store.js and audit.js construct it. Use the named export in each.", max_edits=2),
]
BY_ID = {f.id: f for f in FIXTURES}


def write_tree(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def build_templates(fixture, data_root):
    """Create <data_root>/templates/<id>/{baseline,upgraded} the way scripts/prepare_case.py lays out real cases."""
    for phase, widget, version in [('baseline', fixture.widget_v1, '1.0.0'), ('upgraded', fixture.widget_v2, '2.0.0')]:
        root = Path(data_root) / 'templates' / fixture.id / phase
        write_tree(root, fixture.sources)
        write_tree(root, {'test/run.js': RUNNER.replace('%TESTS%', fixture.tests),
                          'package.json': json.dumps({'name': 'fixture', 'version': '1.0.0', 'dependencies': {'widget': version}}, indent=2) + '\n',
                          'package-lock.json': json.dumps({'name': 'fixture', 'lockfileVersion': 3}, indent=2) + '\n'})
        write_tree(root / 'node_modules/widget', widget)


def apply_edits(root, edits):
    """Plain exact-anchor replacement used for gold/bad candidates (the agent's own guard is tested separately)."""
    for edit in edits:
        path = Path(root) / edit['path']
        text = path.read_text()
        if text.count(edit['old']) != 1:
            raise ValueError(f"anchor not unique in {edit['path']}")
        path.write_text(text.replace(edit['old'], edit['new'], 1))


def local_run_tests(root, timeout=30, case=None, phase='upgraded'):
    """Drop-in for rescue.runner.run_tests on fixtures; same result schema, Node permission-model sandbox."""
    root = Path(root).resolve()
    if not NODE:
        return {'exit_code': -1, 'timed_out': False, 'seconds': 0, 'tests': 0, 'passes': 0, 'failures': [], 'ok': False,
                'infrastructure_error': True, 'isolation': 'node missing'}
    command = [NODE, '--permission', f'--allow-fs-read={root}', 'test/run.js']
    start = time.monotonic()
    try:
        done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout, env={'PATH': str(Path(NODE).parent), 'NO_COLOR': '1'})
        timed_out, code, out = False, done.returncode, done.stdout
    except subprocess.TimeoutExpired as exc:
        timed_out, code, out = True, -9, (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
    try:
        payload = json.loads(out.strip().splitlines()[-1])
        stats, failures = payload, payload['failures']
    except (ValueError, IndexError, KeyError):
        stats, failures = {}, [{'title': 'runner', 'message': (out or '')[:600], 'stack': ''}]
    tests, passes = stats.get('tests', 0), stats.get('passes', 0)
    return {'exit_code': code, 'timed_out': timed_out, 'seconds': round(time.monotonic() - start, 2), 'tests': tests, 'passes': passes,
            'failures': failures, 'ok': code == 0 and tests > 0 and not timed_out, 'infrastructure_error': False,
            'isolation': 'eval-local: node --permission, read-only fixture root, no network/child processes', 'additional_checks': []}


def diff_text(fixture, edits):
    """Unified diff of a candidate against the upgraded sources, in the shape reviewers see."""
    import difflib
    workspace = {k: v for k, v in fixture.sources.items()}
    patched = dict(workspace)
    for edit in edits:
        if patched[edit['path']].count(edit['old']) != 1:
            raise ValueError(f"anchor not unique in {edit['path']}")
        patched[edit['path']] = patched[edit['path']].replace(edit['old'], edit['new'], 1)
    return ''.join(line for p in sorted(patched) if patched[p] != workspace[p]
                   for line in difflib.unified_diff(workspace[p].splitlines(True), patched[p].splitlines(True), f'a/{p}', f'b/{p}'))


def verify_candidate(fixture, edits, scratch):
    """Apply a candidate to a fresh upgraded workspace and run the fixture tests."""
    root = Path(scratch) / ('cand-' + os.urandom(4).hex())
    shutil.copytree(Path(scratch) / 'templates' / fixture.id / 'upgraded', root)
    try:
        apply_edits(root, edits)
    except ValueError as exc:
        return {'ok': False, 'tests': 0, 'passes': 0, 'failures': [{'message': str(exc)}], 'applied': False}
    result = local_run_tests(root)
    result['applied'] = True
    return result
