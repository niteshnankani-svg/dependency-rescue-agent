"""Fixed Python profile: PyPI wheels only, immutable packages, offline pytest."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
import tempfile
import time
import uuid
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from .execution import docker_prefix

IMAGE='python:3.11-slim@sha256:bab1b7ef4b450c81002278d035eff85ebe394ae94df904f7a3ba14f7e16e487b'
PACKAGES='.rescue-python-packages'
RESERVED={PACKAGES,'.rescue-python-versions.json','.rescue-python-lock.json','.rescue-requirements.txt','.rescue-wheels','.rescue-original-lock.txt'}


def requirements(text):
    dependencies={};lines=[]
    for line in text.splitlines():
        line=line.split(' #',1)[0].strip()
        if not line or line.startswith('#'):continue
        try:r=Requirement(line)
        except Exception:raise ValueError('Use PyPI requirement specifications. URLs, pip options, editable installs and include files are unsupported.') from None
        if r.url:raise ValueError('Direct URL dependencies require an operator profile')
        name=canonicalize_name(r.name)
        if name in dependencies:raise ValueError('Duplicate Python requirement: '+name)
        if name=='pytest' and r.specifier and not r.specifier.contains('8.3.5'):raise ValueError('This profile requires pytest 8.3.5')
        dependencies[name]=str(r.specifier) or 'unconstrained';lines.append(str(r))
    if not dependencies or len(dependencies)>100:raise ValueError('Python profile requires 1–100 direct dependencies')
    return dependencies,lines


def manifest(text,path):
    if path.endswith('pyproject.toml'):
        document=tomllib.loads(text);project=document.get('project',{})
        if project.get('requires-python') and not SpecifierSet(project['requires-python']).contains('3.11.17'):raise ValueError('Project requires a different Python version; this profile uses Python 3.11.17')
        if 'dependencies' in project.get('dynamic',[]):raise ValueError('Dynamic Python dependencies need an operator profile')
        text='\n'.join(project.get('dependencies',[]))
    return requirements(text)


def pin(lines,versions,dependency=None,target=None):
    result=[]
    for line in lines:
        r=Requirement(line);name=canonicalize_name(r.name)
        if name not in versions: # A marker can exclude a package on Python 3.11/Linux.
            if name==dependency:raise ValueError('Selected dependency is not installed on Python 3.11/Linux')
            result.append(line);continue
        version=target if name==dependency else versions[name]
        result.append(r.name+('['+','.join(sorted(r.extras))+']' if r.extras else '')+'=='+version+('; '+str(r.marker) if r.marker else ''))
    return result


def setup(root,case,lines):
    if any((root/name).exists() for name in RESERVED):raise ValueError('Repository contains reserved Python runner files')
    (root/'.rescue-requirements.txt').write_text('\n'.join([line for line in lines if canonicalize_name(Requirement(line).name)!='pytest']+['pytest==8.3.5'])+'\n')
    wheels=root/'.rescue-wheels';wheels.mkdir();(wheels/'.tmp').mkdir()
    # Only the requirements file and wheel output are exposed during networked resolution.
    common=[*docker_prefix(),'run','--rm','--pull=never','--read-only','--user',f'{os.getuid()}:{os.getgid()}','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128','--memory=768m','--cpus=1','--ulimit','fsize=536870912:536870912','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777','--env','HOME=/tmp','--env','PIP_CONFIG_FILE=/dev/null']
    download=['--env','TMPDIR=/wheels/.tmp','--mount',f'type=bind,src={root / ".rescue-requirements.txt"},dst=/requirements.txt,readonly','--mount',f'type=bind,src={wheels},dst=/wheels',case.image,'python','-I','-m','pip','--isolated','download','--only-binary=:all:','--no-cache-dir','--index-url','https://pypi.org/simple','--dest','/wheels','-r','/requirements.txt']
    _run(common,download,wheels,1_500_000_000)
    shutil.rmtree(wheels/'.tmp')
    files=sorted(wheels.glob('*.whl'))
    if not files or len(files)>500 or sum(p.stat().st_size for p in files)>1_500_000_000:raise ValueError('Python wheel environment exceeds size limit')
    wheel_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    installed=root/PACKAGES;installed.mkdir();(installed/'.tmp').mkdir()
    install=['--env','TMPDIR=/packages/.tmp','--network=none','--mount',f'type=bind,src={wheels},dst=/wheels,readonly','--mount',f'type=bind,src={installed},dst=/packages',case.image,'python','-I','-m','pip','--isolated','install','--no-index','--no-deps','--no-compile','--target','/packages',*['/wheels/'+p.name for p in files]]
    _run(common,install,installed,3_000_000_000)
    shutil.rmtree(installed/'.tmp')
    shutil.rmtree(wheels)
    for p in installed.rglob('*'):
        if p.is_symlink():raise ValueError('Installed Python package contains a symlink')
    versions={}
    for p in installed.glob('*.dist-info/METADATA'):
        text=p.read_text();name=re.search(r'^Name: (.+)$',text,re.M);version=re.search(r'^Version: (.+)$',text,re.M)
        if name and version:versions[canonicalize_name(name[1])]=version[1]
    (root/'.rescue-python-versions.json').write_text(json.dumps(versions,sort_keys=True))
    original_lock=root/'rescue-python.lock.json'
    (root/'.rescue-original-lock.txt').write_text(original_lock.read_text() if original_lock.exists() else '')
    (root/'rescue-python.lock.json').write_text(json.dumps({'image':case.image,'wheels':wheel_hashes,'versions':versions},sort_keys=True))
    return versions


def _run(common,command,storage=None,limit=1_500_000_000):
    name='rescue-python-setup-'+uuid.uuid4().hex
    try:
        with tempfile.TemporaryFile(mode='w+') as output:
            process=subprocess.Popen([*common,'--name',name,*command],stdout=output,stderr=subprocess.STDOUT)
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic()-started>300 or os.fstat(output.fileno()).st_size>1_000_000:
                        raise ValueError('Python dependency setup exceeded its time/output limit')
                    size=0
                    if storage:
                        for path in storage.rglob('*'):
                            try:
                                if path.is_file():size+=path.stat().st_size
                            except FileNotFoundError:pass
                    if size>limit:
                        raise ValueError('Python dependency setup exceeded its disk budget')
                    time.sleep(.5)
                output.seek(0);message=output.read(1_000_000)
                if process.returncode:
                    missing=re.search(r'No matching distribution found for ([A-Za-z0-9_.\[\],<>=! -]+)',message)
                    if missing:raise ValueError('No compatible published wheel for '+missing[1].strip()+'. This profile requires Python 3.11/Linux wheels and does not run source builds.')
                    if 'No space left on device' in message:raise ValueError('Python installer ran out of scratch storage; free disk space or use a dedicated worker with a larger package budget')
                    if 'ResolutionImpossible' in message:raise ValueError('Python dependency constraints conflict. Resolve the original requirements before preparing an upgrade.')
                    raise ValueError('Python wheel setup failed. Check Python 3.11 compatibility, PyPI availability and dependency constraints. Source builds are disabled; no repository code or credentials were used.')
            finally:
                if process.poll() is None:
                    subprocess.run([*docker_prefix(),'rm','-f',name],capture_output=True,timeout=20)
                    process.terminate();process.wait(timeout=20)
    finally:subprocess.run([*docker_prefix(),'rm','-f',name],capture_output=True,timeout=20)


# The wrapper and invocation are operator owned; repository input never becomes a command.
TEST_CODE="""import subprocess,xml.etree.ElementTree as E,json,sys
p=subprocess.run(['python','-m','pytest','-c','/dev/null','-p','no:cacheprovider','--junitxml=/tmp/rescue-report.xml','--rootdir=/app','/app'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
 root=E.parse('/tmp/rescue-report.xml').getroot();cases=list(root.iter('testcase'));fail=[];passes=0
 for case in cases:
  errors=[x for x in case if x.tag in ('failure','error','skipped')]
  if errors:
   fail.append({'fullTitle':case.get('classname','')+'.'+case.get('name',''),'err':{'message':(errors[0].text or errors[0].get('message','Skipped test'))[:5000]}})
  else:passes+=1
 print(json.dumps({'stats':{'tests':len(cases),'passes':passes},'failures':fail}))
except Exception:print(p.stdout[-7000:])
sys.exit(p.returncode)
"""
