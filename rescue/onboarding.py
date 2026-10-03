"""Bounded npm onboarding into immutable, dynamically registered repair cases."""
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import uuid
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel,ConfigDict,Field
from .config import Case,DATA,RUNTIME
from .github_connection import GitHub,MissingFile
from .execution import docker_prefix
from .guards import source_preflight
from . import python_profile
from .security import secret_present

LOCK=threading.Lock()
MAX_ARCHIVE=30_000_000
MAX_SOURCE=100_000_000
IMPORTS=RUNTIME/'remote-imports' if os.getenv('RESCUE_CLOUD_IMPORTS')=='1' else DATA/'imports'


class Inspect(BaseModel):
    model_config=ConfigDict(extra='forbid')
    repository:str=Field(pattern=r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$',max_length=200)
    ref:str=Field(default='',max_length=150,pattern=r'^[A-Za-z0-9_./-]*$')
    use_mcp:bool=True
    project_dir:str=Field(default='',max_length=150,pattern=r'^(?:[A-Za-z0-9_-][A-Za-z0-9_./-]*)?$')


class Prepare(BaseModel):
    model_config=ConfigDict(extra='forbid')
    inspection_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    dependency:str=Field(pattern=r'^(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+$',max_length=200)
    target_version:str=Field(pattern=r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$',max_length=100)


def folder():
    path=RUNTIME/'onboarding';path.mkdir(exist_ok=True,mode=0o700);return path


def save(value):
    path=folder()/(value['id']+'.json');temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value));temp.chmod(0o600);temp.replace(path)


def read(ident):
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid inspection identifier')
    try:return json.loads((folder()/(ident+'.json')).read_text())
    except FileNotFoundError:raise ValueError('Inspection not found') from None


def safe_spec(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9.*^~<>=|+ -]+',value))


def validate_manifest(package,lock):
    if package.get('workspaces'):raise ValueError('Monorepo workspaces need a dedicated runner profile; currently unsupported')
    for group in ['dependencies','devDependencies','optionalDependencies','peerDependencies']:
        for name,spec in package.get(group,{}).items():
            if not re.fullmatch(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+',name) or not safe_spec(spec):raise ValueError('Only npm registry dependency specifications are supported')
    if package.get('overrides'):raise ValueError('npm overrides require operator review')
    def visit(item):
        if isinstance(item,dict):
            if item.get('link'):raise ValueError('Linked dependencies are unsupported')
            if 'resolved' in item:
                u=urlparse(item['resolved'])
                if u.scheme!='https' or u.hostname!='registry.npmjs.org' or u.port not in [None,443] or u.username or u.password or u.query or u.fragment:raise ValueError('Lockfile downloads must use HTTPS registry.npmjs.org')
                if not item.get('integrity'):raise ValueError('Lockfile dependency has no integrity checksum')
            for value in item.values():visit(value)
        elif isinstance(item,list):
            for value in item:visit(value)
    visit(lock)
    if lock.get('lockfileVersion') not in [1,2,3]:raise ValueError('An npm lockfile version 1, 2, or 3 is required')


def test_profile(package):
    script=package.get('scripts',{}).get('test','')
    args=shlex.split(script)
    if not args or args[0] not in ['mocha','jest']:raise ValueError('Supported test scripts start directly with mocha or jest; shell chains, builds, and custom runners need an operator profile')
    if any(not re.fullmatch(r'[A-Za-z0-9_./*=-]+',a) or '..' in PurePosixPath(a).parts for a in args[1:]):raise ValueError('Test arguments require operator review')
    # Reporter/output arguments are owned by the verifier, not by repository input.
    forbidden=['--reporter','--reporters','-R','--outputFile','--watch','--watchAll','--json','--coverage','--updateSnapshot','-u']
    if any(a.split('=')[0] in forbidden for a in args[1:]):raise ValueError('Test script customizes reporting or mutation; simplify it before importing')
    if args[0]=='mocha':return 'mocha',['node_modules/mocha/bin/mocha.js',*args[1:],'--reporter','json']
    return 'jest',['node_modules/jest/bin/jest.js',*args[1:],'--json','--runInBand','--no-cache']


def inspect(body,actor,public_owner=None):
    github=GitHub(public_owner=public_owner) if public_owner else GitHub()
    try:
        meta=github.check_repository(body.repository)
        from urllib.parse import quote
        commit=github.get('/repos/'+body.repository+'/commits/'+quote(body.ref or meta['default_branch'],safe=''))['sha']
        if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('GitHub did not resolve an immutable commit')
        project=body.project_dir
        if '..' in PurePosixPath(project).parts:raise ValueError('Project folder must remain inside repository')
        prefix=project.rstrip('/')+'/' if project else ''
        try:
            package=json.loads(github.file(body.repository,commit,prefix+'package.json'))
        except MissingFile:
            language='python';package={}
            try:
                manifest_path=prefix+'requirements.txt';text=github.file(body.repository,commit,manifest_path).decode()
            except MissingFile:
                manifest_path=prefix+'pyproject.toml';text=github.file(body.repository,commit,manifest_path).decode()
            dependencies,lines=python_profile.manifest(text,manifest_path)
            reporter,args='pytest',['-c',python_profile.TEST_CODE]
        else:
            language='node';manifest_path=prefix+'package.json';lines=[]
            lock=json.loads(github.file(body.repository,commit,prefix+'package-lock.json'))
            validate_manifest(package,lock);reporter,args=test_profile(package)
            dependencies={**package.get('devDependencies',{}),**package.get('dependencies',{})}
        mcp=(github.mcp_manifest(body.repository,commit) if manifest_path=='package.json' else github.mcp_manifest(body.repository,commit,manifest_path)) if body.use_mcp else None
        value={'id':uuid.uuid4().hex,'actor':actor,'status':'inspected','repository':body.repository,'commit':commit,'dependencies':dependencies,'language':language,'project_dir':project,'manifest_path':manifest_path,'requirements':lines,'reporter':reporter,'test_args':args,'license':str(package.get('license') or 'Unspecified')[:100],'mcp':mcp,'message':('Python 3.11 / pytest inspection passed. Published wheels only; tests run offline without API keys. Missing models, fixtures or integration services will block baseline verification.' if language=='python' else 'Inspection passed.')+' Choose a dependency and exact target version to prepare isolated environments.'}
        if public_owner:value['public_owner']=public_owner;value['actor_name']=public_owner
        save(value);return value
    finally:github.close()


def extract(data,destination):
    total=0;count=0
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        for member in archive:
            count+=1;total+=member.size
            if count>20000 or total>MAX_SOURCE or member.size>10_000_000:raise ValueError('Repository exceeds onboarding size limits')
            parts=PurePosixPath(member.name).parts
            if len(parts)<2:continue
            relative=PurePosixPath(*parts[1:])
            if member.name.startswith('/') or '..' in parts or '\\' in member.name or not (member.isfile() or member.isdir()):raise ValueError('Archive contains unsafe paths, links, or special files')
            template=relative.name.startswith('.env.') and relative.name.endswith(('.example','.sample'))
            if any(p in ['.git','node_modules','.npmrc','.pypirc','.venv','__pycache__',*python_profile.RESERVED] or p=='.env' or (p.startswith('.env.') and not (p==relative.name and template)) for p in relative.parts):raise ValueError('Remove vendored dependencies, credential/configuration files before onboarding')
            target=destination/relative
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():raise ValueError('Archive contains duplicate files')
            with archive.extractfile(member) as source:content=source.read()
            if template and secret_present(content.decode(errors='replace')):raise ValueError('Environment template contains a possible credential; remove it before importing')
            target.write_bytes(content)
            target.chmod(0o755 if member.mode&0o111 else 0o644)


def archive_bytes(github,repo,commit):
    r=github.client.get('/repos/'+repo+'/tarball/'+commit)
    if r.status_code!=302:raise ValueError('GitHub archive redirect unavailable')
    url=r.headers.get('location','');parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='codeload.github.com' or parsed.username or parsed.password:raise ValueError('Unexpected GitHub archive destination')
    # Signed archive redirect only. Never forward the installation token.
    with httpx.Client(timeout=90,trust_env=False) as c:
        with c.stream('GET',url) as response:
            response.raise_for_status();data=bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data)>MAX_ARCHIVE:raise ValueError('Repository archive exceeds size limit')
    return data


def setup(root,case,command):
    name='rescue-onboard-'+uuid.uuid4().hex
    cmd=[*docker_prefix(),'run','--rm','--name',name,'--read-only','--user',f'{os.getuid()}:{os.getgid()}','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128','--memory=768m','--cpus=1','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777','--env','HOME=/tmp','--mount',f'type=bind,src={root},dst=/app','--workdir','/app',case.image,'npm',*command,'--ignore-scripts','--no-audit','--no-fund','--registry=https://registry.npmjs.org','--userconfig=/dev/null']
    try:
        result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
        if result.returncode:raise ValueError('Dependency setup failed. Check lockfile consistency, Node 18 compatibility, and whether native modules require lifecycle scripts.')
    finally:subprocess.run([*docker_prefix(),'rm','-f',name],capture_output=True,timeout=20)
    for p in root.rglob('*'):
        if p.is_symlink() and not p.resolve().is_relative_to(root.resolve()):raise ValueError('Installed dependency symlink escapes the sandbox')


def prepare(body,actor):
    if os.getenv('RESCUE_RUNNER')=='remote' and os.getenv('RESCUE_CLOUD_IMPORTS')=='1':
        from .cloud_imports import prepare_remote
        return prepare_remote(body,actor)
    if os.getenv('RESCUE_RUNNER')!='docker' or os.getenv('RESCUE_ENV')=='production':raise ValueError('Automatic onboarding currently requires the local Docker runner; remote production workers need synchronized immutable snapshots')
    if not LOCK.acquire(blocking=False):raise ValueError('Another repository is being prepared; wait for it to finish')
    try:
        value=read(body.inspection_id)
        if value['actor']!=actor:raise ValueError('Inspection belongs to another operator')
        if value['status']!='inspected':raise ValueError('Inspect again before another preparation')
        if body.dependency not in value['dependencies']:raise ValueError('Select a direct dependency from this inspection')
        value.update(status='preparing',message='Downloading pinned source and preparing dependencies without lifecycle scripts.');save(value)
        threading.Thread(target=prepare_worker,args=(body,value),daemon=True).start()
        return value
    except Exception:
        LOCK.release();raise


def prepare_worker(body,value):
    case_id='github-'+value['id'];root=IMPORTS/case_id
    github=None;registered=False
    try:
        github=GitHub(public_owner=value['public_owner']) if value.get('public_owner') else GitHub()
        github.check_repository(value['repository'])
        IMPORTS.mkdir(parents=True,exist_ok=True,mode=0o700);IMPORTS.chmod(0o700)
        root.mkdir(mode=0o700,exist_ok=False)
        baseline=root/'baseline';baseline.mkdir()
        extract(archive_bytes(github,value['repository'],value['commit']),baseline)
        if value.get('project_dir'):
            selected=baseline/value['project_dir']
            if not selected.is_dir():raise ValueError('Selected project folder is missing')
            selected.rename(root/'selected-project');shutil.rmtree(baseline);(root/'selected-project').rename(baseline)
        language=value.get('language','node')
        if language=='python':
            manifest_path=PurePosixPath(value['manifest_path']).name
            dependencies,lines=python_profile.manifest((baseline/manifest_path).read_text(),manifest_path)
            globs=['**/*.py'];reporter='pytest';args=['-c',python_profile.TEST_CODE]
        else:
            package=json.loads((baseline/'package.json').read_text());lock=json.loads((baseline/'package-lock.json').read_text())
            validate_manifest(package,lock);reporter,args=test_profile(package)
            globs=['src/**/*.js','src/**/*.ts','lib/**/*.js','lib/**/*.ts','index.js','index.ts']
        if not source_preflight(baseline,globs):raise ValueError('No supported editable source files found')
        case=Case(id=case_id,repository=value['repository'],base_commit=value['commit'],dependency=body.dependency,old_version=value['dependencies'][body.dependency],target_version=body.target_version,template_dir='imports/'+case_id,source_globs=globs,test_args=args,reporter=reporter,language=language,project_dir=value.get('project_dir',''),python_manifest=PurePosixPath(value.get('manifest_path','requirements.txt')).name if language=='python' else 'requirements.txt',license=value['license'],evaluation_role='customer repository — baseline not yet verified',**({'image':python_profile.IMAGE} if language=='python' else {}))
        if os.getenv('RESCUE_CLOUD_IMPORTS')=='1':case=case.model_copy(update={'template_dir':'remote-imports/'+case_id})
        upgraded=root/'upgraded';shutil.copytree(baseline,upgraded)
        if language=='python':
            versions=python_profile.setup(baseline,case,lines)
            if body.dependency not in versions:raise ValueError('Selected package is excluded by environment markers')
            case=case.model_copy(update={'old_version':versions[body.dependency]})
            upgraded_lines=python_profile.pin(lines,versions,body.dependency,body.target_version)
            # Preserve the original manifest in baseline; update the upgrade manifest only.
            if manifest_path=='requirements.txt':(upgraded/manifest_path).write_text('\n'.join(upgraded_lines)+'\n')
            else:
                import tomllib,tomli_w
                document=tomllib.loads((upgraded/manifest_path).read_text());document['project']['dependencies']=upgraded_lines
                (upgraded/manifest_path).write_text(tomli_w.dumps(document))
            python_profile.setup(upgraded,case,upgraded_lines)
        else:
            for group in ['dependencies','devDependencies']:
                if body.dependency in package.get(group,{}):package[group][body.dependency]=body.target_version
            (upgraded/'package.json').write_text(json.dumps(package,indent=2)+'\n')
            setup(upgraded,case,['install','--package-lock-only'])
            validate_manifest(package,json.loads((upgraded/'package-lock.json').read_text()))
            for phase in [baseline,upgraded]:setup(phase,case,['ci'])
        if case.version(upgraded)!=body.target_version:raise ValueError('Installed dependency does not match the selected target')
        if case.version(baseline)==body.target_version:raise ValueError('Baseline already uses the requested target version')
        registry=IMPORTS/'registry.json';rows=json.loads(registry.read_text()) if registry.exists() else []
        rows.append(case.model_dump());temp=registry.with_suffix('.tmp');temp.write_text(json.dumps(rows));temp.replace(registry);registered=True
        value.update(status='ready',case_id=case_id,message='Environment prepared. Run repair to check the baseline, reproduce failures, and generate a reviewed patch.');save(value)
    except Exception as error:
        # Do not persist raw HTTP errors: they may contain a signed archive URL.
        value.update(status='failed',message=str(error) if isinstance(error,ValueError) else 'Repository preparation failed ('+type(error).__name__+'). Check worker availability and repository compatibility.');save(value)
        if root.exists() and not registered:shutil.rmtree(root)
    finally:
        if github:github.close()
        LOCK.release()


def recover_interrupted():
    for path in folder().glob('*.json'):
        value=json.loads(path.read_text())
        if value.get('status')=='preparing':
            value.update(status='failed',message='Preparation was interrupted by a server restart. Inspect the repository again to retry.')
            save(value)
