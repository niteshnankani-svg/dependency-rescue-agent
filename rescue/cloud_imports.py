"""Credential-free preparation on the dedicated worker; bounded snapshot transfer."""
import hashlib,json,os,shutil,tarfile,threading,time
from pathlib import Path,PurePosixPath
import httpx
from fastapi import HTTPException
from .config import RUNTIME,Case
from . import onboarding

MAX_BUNDLE=256_000_000
MAX_EXPANDED=1_500_000_000


def unpack(path,dest):
    total=count=0
    with tarfile.open(path,'r:gz') as archive:
        for member in archive:
            count+=1;total+=member.size
            parts=PurePosixPath(member.name).parts
            if not parts or parts[0]!='snapshot' or '..' in parts or member.name.startswith('/') or '\\' in member.name or not (member.isfile() or member.isdir()):raise ValueError('Unsafe prepared snapshot')
            if count>100000 or total>MAX_EXPANDED or member.size>100_000_000:raise ValueError('Prepared snapshot exceeds limits')
            relative=Path(*parts[1:])
            if relative.parts and relative.parts[0] not in ['baseline','upgraded']:raise ValueError('Invalid snapshot phase')
            target=dest/relative
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            if not relative.parts or target.exists():raise ValueError('Duplicate snapshot file')
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as src,target.open('wb') as out:shutil.copyfileobj(src,out)
            target.chmod(0o755 if member.mode&0o111 else 0o644)


def connection():
    url=os.environ['RESCUE_EXECUTOR_URL'].rstrip('/')
    if not url.startswith('https://') and os.getenv('RESCUE_PRIVATE_EXECUTOR')!='1':raise ValueError('Private worker transport is not configured')
    return url,{'Authorization':'Bearer '+os.environ['RESCUE_EXECUTOR_TOKEN']}


def prepare_remote(body,actor):
    value=onboarding.read(body.inspection_id)
    if value['actor']!=actor or value['status']!='inspected':raise ValueError('Inspect your repository again before preparation')
    if not value.get('public_owner'):raise ValueError('Cloud import currently requires a public repository owned by your GitHub account')
    if value['public_owner'].lower()!=value['actor_name'].lower():raise ValueError('Cloud import is limited to your own public GitHub repositories')
    if body.dependency not in value['dependencies']:raise ValueError('Select a direct dependency')
    if not onboarding.LOCK.acquire(blocking=False):raise ValueError('Another repository is being prepared; try again later')
    try:
        from .api import db
        with db() as c:
            c.execute('BEGIN IMMEDIATE');since=time.time()-86400
            if c.execute("SELECT count(*) FROM audit WHERE action='repository-prepare' AND actor=? AND time>?",(actor,since)).fetchone()[0]>=1:raise ValueError('One repository preparation per account every 24 hours')
            if c.execute("SELECT count(*) FROM audit WHERE action='repository-prepare' AND time>?",(since,)).fetchone()[0]>=8:raise ValueError('Shared preparation allowance reached; try again later')
            c.execute('INSERT INTO audit(time,actor,action,run_id,evidence_digest) VALUES (?,?,?,?,?)',(time.time(),actor,'repository-prepare',value['id'],''))
        value.update(status='preparing',message='Preparing your pinned public repository on the isolated worker.');onboarding.save(value)
        threading.Thread(target=remote_task,args=(body,value),daemon=True).start()
        return value
    except Exception:onboarding.LOCK.release();raise


def remote_task(body,value):
    dest=RUNTIME/'remote-imports'/('github-'+value['id']);staging=dest.with_name(dest.name+'-staging');bundle=dest.with_suffix('.tar.gz')
    try:
        url,headers=connection()
        with httpx.Client(timeout=30,trust_env=False,headers=headers) as client:
            payload={k:value[k] for k in ['id','actor','repository','commit','project_dir','public_owner']}
            payload.update(dependency=body.dependency,target_version=body.target_version)
            response=client.post(url+'/prepare',json=payload);response.raise_for_status()
            deadline=time.monotonic()+1500
            while True:
                response=client.get(url+'/preparations/'+value['id']);response.raise_for_status();status=response.json()
                if status['status']=='ready':break
                if status['status']=='failed':raise ValueError(status['message'])
                if time.monotonic()>deadline:raise ValueError('Preparation exceeded its time limit')
                time.sleep(3)
            case=Case.model_validate(status['case'])
            if case.id!='github-'+value['id'] or case.base_commit!=value['commit'] or case.repository!=value['repository'] or case.target_version!=body.target_version or case.template_dir!='remote-imports/'+case.id:raise ValueError('Worker preparation identity mismatch')
            dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            size=0;digest=hashlib.sha256()
            with client.stream('GET',url+'/preparations/'+value['id']+'/snapshot',timeout=300) as response:
                response.raise_for_status();expected=response.headers.get('X-Snapshot-SHA256','')
                with bundle.open('wb') as out:
                    for part in response.iter_bytes():
                        size+=len(part)
                        if size>MAX_BUNDLE:raise ValueError('Prepared dependency snapshot is too large')
                        digest.update(part);out.write(part)
            if digest.hexdigest()!=expected:raise ValueError('Snapshot transfer integrity failed')
            if shutil.disk_usage(dest.parent).free<MAX_EXPANDED+500_000_000:raise ValueError('Insufficient API storage for repository preparation')
            staging.mkdir(mode=0o700);unpack(bundle,staging)
            for phase in ['baseline','upgraded']:onboarding.source_preflight(staging/phase,case.source_globs)
            if case.version(staging/'upgraded')!=body.target_version:raise ValueError('Prepared dependency version mismatch')
            staging.replace(dest)
            registry=dest.parent/'registry.json';rows=json.loads(registry.read_text()) if registry.exists() else []
            rows.append(case.model_dump());temp=registry.with_suffix('.tmp');temp.write_text(json.dumps(rows));temp.replace(registry)
            value.update(status='ready',case_id=case.id,message='Your repository is prepared. Run repair to verify the baseline and reproduce the upgrade failure.');onboarding.save(value)
    except Exception as error:
        value.update(status='failed',message=str(error) if isinstance(error,ValueError) else 'Cloud preparation failed; inspect repository compatibility and worker availability.');onboarding.save(value)
        if dest.exists():shutil.rmtree(dest)
    finally:
        if staging.exists():shutil.rmtree(staging)
        bundle.unlink(missing_ok=True);onboarding.LOCK.release()
