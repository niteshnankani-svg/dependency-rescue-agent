"""Dedicated worker only. Never deploy this service on a credential-bearing shared host."""
import hmac
import os
from pathlib import Path
import shutil
import tempfile
import threading
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from .config import get_case
from .execution import docker_execute
from .guards import source_files,snapshot_digest

app=FastAPI(title='Rescue isolated executor',docs_url=None,redoc_url=None)
LOCK=threading.BoundedSemaphore(1)


class Execution(BaseModel):
    model_config=ConfigDict(extra="forbid")
    case_id:str=Field(max_length=70)
    phase:str=Field(pattern='^(baseline|upgraded)$')
    files:dict[str,str]


@app.get('/healthz')
def health():
    import subprocess
    from .execution import docker_prefix
    try:
        result=subprocess.run([*docker_prefix(),'info','--format','{{.ServerVersion}}'],capture_output=True,timeout=3)
        if result.returncode==0:
            return {'status':'ok','docker_ready':True}
    except (OSError,subprocess.TimeoutExpired):
        pass
    raise HTTPException(503,'Execution runtime unavailable')


@app.post('/execute')
async def execute(request:Request):
    expected=os.getenv('RESCUE_EXECUTOR_TOKEN','')
    supplied=request.headers.get('authorization','').removeprefix('Bearer ')
    if len(expected)<32 or not supplied.isascii() or len(supplied)>8192 or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,'Executor authentication failed')
    data=bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data)>3_000_000:
            raise HTTPException(413,'Source snapshot too large')
    try:
        body=Execution.model_validate_json(data)
        selected=get_case(body.case_id)
    except ValueError:
        raise HTTPException(422,'Invalid execution request') from None
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429,'Executor busy')
    try:
        source=selected.templates/body.phase
        allowed={str(p.relative_to(source)) for p in source_files(source,selected.source_globs)}
        if set(body.files)!=allowed:
            raise HTTPException(422,'Source snapshot does not match registered case')
        base=Path(os.environ['RESCUE_WORKSPACE_ROOT']).resolve();base.mkdir(parents=True,exist_ok=True)
        # This host path must be identically mounted into the executor service.
        with tempfile.TemporaryDirectory(dir=base,prefix='execute-') as tmp:
            root=Path(tmp)/'repo';shutil.copytree(source,root,symlinks=True)
            for name,text in body.files.items():
                (root/name).write_text(text)
            # Run blocking Docker work outside the API event loop.
            import asyncio
            before=await asyncio.to_thread(snapshot_digest,root)
            result=await asyncio.to_thread(docker_execute,root,selected)
            result['snapshot_digest']=before
            result['snapshot_unchanged']=before==await asyncio.to_thread(snapshot_digest,root)
            result['ok']=result['ok'] and result['snapshot_unchanged']
            return result
    finally:
        LOCK.release()


class Preparation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    actor:str=Field(max_length=100)
    repository:str=Field(pattern=r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$',max_length=200)
    commit:str=Field(pattern=r'^[a-f0-9]{40}$')
    project_dir:str=Field(default='',max_length=150,pattern=r'^(?:[A-Za-z0-9_-][A-Za-z0-9_./-]*)?$')
    public_owner:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
    dependency:str=Field(pattern=r'^(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+$',max_length=200)
    target_version:str=Field(pattern=r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$',max_length=100)


def preparation_auth(request:Request):
    expected=os.getenv('RESCUE_EXECUTOR_TOKEN','');supplied=request.headers.get('authorization','').removeprefix('Bearer ')
    if len(expected)<32 or not supplied.isascii() or len(supplied)>8192 or not hmac.compare_digest(expected,supplied):raise HTTPException(401,'Executor authentication failed')
    if os.getenv('RESCUE_CLOUD_IMPORTS')!='1':raise HTTPException(503,'Cloud preparation disabled')


from fastapi import Depends

@app.post('/prepare',status_code=202,dependencies=[Depends(preparation_auth)])
def prepare_repository(body:Preparation):
    from . import onboarding
    if body.repository.split('/')[0].lower()!=body.public_owner.lower():raise HTTPException(422,'Repository ownership mismatch')
    try:existing=onboarding.read(body.id)
    except ValueError:existing=None
    if existing:
        if any(existing.get(k)!=getattr(body,k) for k in ['actor','repository','commit','project_dir','public_owner']):raise HTTPException(409,'Preparation identity conflict')
        return {'id':body.id,'status':existing['status']}
    if not onboarding.LOCK.acquire(blocking=False):raise HTTPException(429,'Preparation worker busy')
    def task():
        try:
            value=onboarding.inspect(onboarding.Inspect(repository=body.repository,ref=body.commit,project_dir=body.project_dir,use_mcp=False),body.actor,public_owner=body.public_owner)
            old_id=value['id'];value.update(id=body.id,status='preparing');onboarding.save(value)
            (onboarding.folder()/(old_id+'.json')).unlink(missing_ok=True)
            onboarding.prepare_worker(onboarding.Prepare(inspection_id=body.id,dependency=body.dependency,target_version=body.target_version),value)
        except Exception:
            onboarding.save({'id':body.id,'actor':body.actor,'repository':body.repository,'commit':body.commit,'project_dir':body.project_dir,'public_owner':body.public_owner,'status':'failed','message':'Pinned repository inspection failed on the preparation worker.'})
            if onboarding.LOCK.locked():onboarding.LOCK.release()
    threading.Thread(target=task,daemon=True).start()
    return {'id':body.id,'status':'preparing'}


@app.get('/preparations/{ident}',dependencies=[Depends(preparation_auth)])
def preparation_status(ident:str):
    from . import onboarding
    try:value=onboarding.read(ident)
    except ValueError:raise HTTPException(404,'Preparation not found') from None
    if value['status']=='ready':value['case']=get_case(value['case_id']).model_dump()
    return value


@app.get('/preparations/{ident}/snapshot',dependencies=[Depends(preparation_auth)])
def preparation_snapshot(ident:str):
    import hashlib,tarfile
    from . import onboarding
    from .cloud_imports import MAX_BUNDLE
    from fastapi.responses import FileResponse
    try:value=onboarding.read(ident)
    except ValueError:raise HTTPException(404,'Preparation not found') from None
    if value['status']!='ready':raise HTTPException(409,'Preparation not ready')
    case=get_case(value['case_id']);path=onboarding.IMPORTS/(case.id+'.tar.gz')
    if not path.exists():
        temp=path.with_suffix('.tmp')
        with tarfile.open(temp,'w:gz',dereference=True) as archive:archive.add(case.templates,arcname='snapshot')
        if temp.stat().st_size>MAX_BUNDLE:
            temp.unlink();raise HTTPException(413,'Prepared snapshot exceeds transfer limit')
        temp.replace(path)
    digest=hashlib.sha256()
    with path.open('rb') as src:
        for part in iter(lambda:src.read(1024*1024),b''):digest.update(part)
    return FileResponse(path,media_type='application/gzip',headers={'X-Snapshot-SHA256':digest.hexdigest()})
