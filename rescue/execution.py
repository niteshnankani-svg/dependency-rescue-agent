"""Disposable Docker execution and authenticated remote worker transport."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import uuid
import httpx
from .guards import source_files,snapshot_digest
from .security import redact_text

MAX_OUTPUT=1_000_000


def docker_prefix():
    return ['docker',*(['--context',os.environ['RESCUE_DOCKER_CONTEXT']] if os.getenv('RESCUE_DOCKER_CONTEXT') else [])]


def parse_result(raw,returncode,elapsed,case,timed_out=False):
    payload=None
    decoder=json.JSONDecoder()
    for match in re.finditer(r'\{',raw):
        try:
            value,_=decoder.raw_decode(raw[match.start():])
            if isinstance(value,dict) and ('stats' in value or 'numTotalTests' in value):
                payload=value;break
        except ValueError:
            pass
    tests=passes=0;failures=[]
    if payload and 'stats' in payload:
        tests=payload['stats'].get('tests',0);passes=payload['stats'].get('passes',0)
        failures=[{'title':t.get('fullTitle',''),'message':t.get('err',{}).get('message',''),'stack':t.get('err',{}).get('stack','')[:5000]} for t in payload.get('failures',[])]
    elif payload:
        tests=payload.get('numTotalTests',0);passes=payload.get('numPassedTests',0)
        for suite in payload.get('testResults',[]):
            for assertion in suite.get('assertionResults',[]):
                if assertion.get('status')=='failed':
                    failures.append({'title':assertion.get('fullName',''),'message':'\n'.join(assertion.get('failureMessages',[]))[:5000]})
            if suite.get('status')=='failed' and not suite.get('assertionResults'):
                failures.append({'message':suite.get('message','')[:5000]})
    if not payload:
        failures=[{'message':raw[-7000:] or 'No test report produced'}]
    failures=[{k:redact_text(v) if isinstance(v,str) else v for k,v in failure.items()} for failure in failures]
    infrastructure=returncode in [125,126,127,137] or (not payload and bool(re.search(r'Failed to initialize: unable to resolve docker endpoint|Cannot connect to the Docker daemon|error during connect:|Error response from daemon:|OCI runtime .*failed',raw)))
    return {'exit_code':returncode,'timed_out':timed_out,'seconds':round(elapsed,2),'tests':tests,'passes':passes,'failures':failures,'ok':returncode==0 and tests>0 and passes==tests and not failures and not timed_out,'infrastructure_error':infrastructure,'isolation':'Docker: no network, read-only source, non-root, no capabilities, CPU/memory/PID limits','image':case.image}


def docker_execute(root,case,args=None,exit_only=False):
    if '@sha256:' not in case.image:
        raise ValueError('Execution image must be pinned by digest')
    root=root.resolve();name='rescue-'+uuid.uuid4().hex
    for path in case.writable_dirs:
        (root/path).mkdir(parents=True,exist_ok=True)
    command=[*docker_prefix(),'run','--rm','--pull=never','--name',name,'--network=none','--read-only','--user','1000:1000','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=96','--memory=768m','--memory-swap=768m','--cpus=1','--ulimit','nofile=256:256','--ulimit','fsize=16777216:16777216','--mount',f'type=bind,src={root},dst=/app,readonly','--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','--workdir','/app','--env','HOME=/tmp','--env','V8R_CACHE_NAME=rescue-test','--env','NO_COLOR=1']
    for path in case.writable_dirs:
        command+=['--tmpfs',f'/app/{path}:rw,nosuid,nodev,noexec,size=16m,mode=1777']
    if case.language=='python':
        command += ['--env','PYTHONPATH=/app/.rescue-python-packages:/app:/app/src','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTEST_DISABLE_PLUGIN_AUTOLOAD=1']
    command += [case.image,'python' if case.language=='python' else 'node',*(args or case.test_args)]
    start=time.monotonic();timed_out=False
    with tempfile.TemporaryFile(mode='w+') as output:
        proc=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while proc.poll() is None:
                if time.monotonic()-start>case.timeout or os.fstat(output.fileno()).st_size>MAX_OUTPUT or (root.parent/'cancel').exists():
                    timed_out=True
                    subprocess.run([*docker_prefix(),'rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait();break
                time.sleep(.1)
            output.seek(0);raw=output.read(MAX_OUTPUT)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            subprocess.run([*docker_prefix(),'rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
    result=parse_result(raw,proc.returncode,time.monotonic()-start,case,timed_out)
    if exit_only:
        result['ok']=proc.returncode==0 and not timed_out
        if result['ok']:result['failures']=[]
    if args is None:
        result['additional_checks']=[]
        for command in case.additional_test_args:
            check=docker_execute(root,case,args=command,exit_only=True)
            result['additional_checks'].append({'command':command,**check})
            if not check['ok']:
                result['ok']=False
                result['failures'].extend(check['failures'])
                result['infrastructure_error'] |= check['infrastructure_error']
                result['timed_out'] |= check['timed_out']
    return result


def remote_execute(root,case,phase):
    url=os.environ['RESCUE_EXECUTOR_URL'].rstrip('/')
    if os.getenv('RESCUE_ENV')=='production' and not url.startswith('https://') and not os.getenv('RESCUE_PRIVATE_EXECUTOR')=='1':
        raise RuntimeError('Remote executor requires TLS or explicitly isolated private network')
    files={str(p.relative_to(root)):p.read_text() for p in source_files(root,case.source_globs)}
    body={'case_id':case.id,'phase':phase,'files':files}
    with httpx.Client(timeout=case.timeout+45,trust_env=False) as client:
        response=client.post(url+'/execute',json=body,headers={'Authorization':'Bearer '+os.environ['RESCUE_EXECUTOR_TOKEN']})
        response.raise_for_status()
        result=response.json()
        if result.get('snapshot_digest')!=snapshot_digest(root) or not result.get('snapshot_unchanged'):
            raise RuntimeError('Executor snapshot differs from the approved local environment')
        return result
