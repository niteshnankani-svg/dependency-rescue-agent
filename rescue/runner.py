"""Fail-closed local sandbox. Model output is never a shell command."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def run_tests(root: Path, timeout: int = 60) -> dict:
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').exists():
        raise RuntimeError('No supported isolated runner. Local execution requires macOS Seatbelt; Linux worker not yet qualified.')
    root = root.resolve()
    node = Path(os.getenv('RESCUE_NODE', str(Path(__file__).resolve().parents[1]/'data/external/node-v18.20.8-darwin-arm64/bin/node'))).resolve()
    if not node.is_file():
        raise RuntimeError('Node runtime missing')
    with tempfile.TemporaryDirectory(prefix='rescue-test-') as tmp:
        scratch = Path(tmp).resolve()
        cache = root / 'node_modules/flat-cache/.cache'
        cache.mkdir(parents=True, exist_ok=True)
        read_roots = [str(root), str(scratch), str(node.parent.parent), '/System', '/usr/lib', '/usr/share', '/Library/Apple', '/opt/homebrew', '/private/var/db/dyld']
        rules = '\n'.join(f'(subpath {json.dumps(p)})' for p in read_roots)
        profile = f'''(version 1)
(allow default)
(deny network*)
(deny file-read-data (require-not (require-any {rules} (literal "/") (subpath "/dev"))))
(deny file-write*)
(allow file-write* (literal "/dev/null") (subpath {json.dumps(str(scratch))}) (subpath {json.dumps(str(cache))}))
'''
        command = ['/usr/bin/sandbox-exec', '-p', profile, str(node), 'node_modules/mocha/bin/mocha', 'src/**/*.spec.js', '--reporter', 'json', '--timeout', '5000']
        start = time.monotonic()
        with (scratch / 'output').open('w+') as output:
            proc = subprocess.Popen(command, cwd=root, env={'PATH':str(node.parent), 'HOME':str(scratch), 'TMPDIR':str(scratch), 'V8R_CACHE_NAME':'rescue-test', 'NO_COLOR':'1'}, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            output.seek(0)
            raw = output.read(150_000)
        try:
            payload = json.loads(raw)
            stats = payload['stats']
            failures = [{'title':t['fullTitle'], 'message':t.get('err',{}).get('message',''), 'stack':t.get('err',{}).get('stack','')[:5000]} for t in payload.get('failures',[])]
        except (ValueError, KeyError):
            stats, failures = {}, [{'message':raw[:6000]}]
        return {'exit_code':proc.returncode, 'timed_out':timed_out, 'seconds':round(time.monotonic()-start,2), 'tests':stats.get('tests',0), 'passes':stats.get('passes',0), 'failures':failures, 'ok':proc.returncode==0 and stats.get('tests',0)>0 and not timed_out, 'isolation':'macOS Seatbelt; offline; source read-only', 'node':str(node)}
