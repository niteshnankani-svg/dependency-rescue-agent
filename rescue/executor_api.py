"""Dedicated worker only. Never deploy this service on a credential-bearing shared host."""
import hmac
import os
from pathlib import Path
import shutil
import tempfile
import threading
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from .config import get_case
from .execution import docker_execute
from .guards import source_files,snapshot_digest

app=FastAPI(title='Rescue isolated executor',docs_url=None,redoc_url=None)
LOCK=threading.BoundedSemaphore(1)


class Execution(BaseModel):
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
    if len(expected)<32 or not hmac.compare_digest(expected,supplied):
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
