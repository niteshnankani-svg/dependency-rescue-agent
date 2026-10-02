import contextlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from langgraph.types import Command
from .graph import ROOT, RUNTIME, open_graph
from .config import cases as registry
from .auth import verify, require, validate_production
from .http_security import RequestGuard

RUNTIME.mkdir(exist_ok=True,mode=0o700)
RUNTIME.chmod(0o700)
TOKEN_PATH=RUNTIME/'.api-token'
if not TOKEN_PATH.exists():
    fd=os.open(TOKEN_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(secrets.token_urlsafe(32))
TOKEN=os.getenv('RESCUE_API_TOKEN') or TOKEN_PATH.read_text().strip()
LOCAL=os.getenv('RESCUE_ENV','development')!='production' and not bool(os.getenv('RESCUE_API_TOKEN'))
STOP=threading.Event()


def db():
    c=sqlite3.connect(RUNTIME/'jobs.sqlite',timeout=10)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, key TEXT UNIQUE, status TEXT, created REAL, error TEXT)')
    columns={r[1] for r in c.execute('PRAGMA table_info(jobs)')}
    for name,definition in [('case_id',"TEXT DEFAULT 'v8r-js-yaml'"),('actor',"TEXT DEFAULT 'local-user'"),('lease_until','REAL DEFAULT 0'),('worker_id','TEXT')]:
        if name not in columns:
            c.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
    c.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, actor TEXT, action TEXT, run_id TEXT, evidence_digest TEXT)')
    c.commit()
    return c


def worker():
    graph,conn=open_graph()
    worker_id=uuid.uuid4().hex
    try:
        while not STOP.is_set():
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute("UPDATE jobs SET status='queued' WHERE status='running' AND lease_until<?",(time.time(),))
                row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    c.execute("UPDATE jobs SET status='running',lease_until=?,worker_id=? WHERE id=?",(time.time()+45,worker_id,row['id']))
            if not row:
                STOP.wait(.5)
                continue
            config={'configurable':{'thread_id':row['id']}}
            heartbeat_stop=threading.Event()
            def heartbeat():
                while not heartbeat_stop.wait(10):
                    with db() as c:
                        c.execute("UPDATE jobs SET lease_until=? WHERE id=? AND worker_id=? AND status='running'",(time.time()+45,row['id'],worker_id))
            heartbeat_thread=threading.Thread(target=heartbeat,daemon=True);heartbeat_thread.start()
            try:
                existing=graph.get_state(config)
                graph.invoke(None if existing.values else {'run_id':row['id'],'case_id':row['case_id'],'events':[]},config)
                status=graph.get_state(config).values.get('status','blocked')
                with db() as c:
                    c.execute("UPDATE jobs SET status=? WHERE id=? AND status!='cancelled'",(status,row['id']))
            except Exception as exc:
                with db() as c:
                    status='cancelled' if (RUNTIME/row['id']/'cancel').exists() else 'blocked'
                    c.execute('UPDATE jobs SET status=?,error=? WHERE id=?',(status,type(exc).__name__,row['id']))
            finally:
                heartbeat_stop.set();heartbeat_thread.join(timeout=1)
    finally:
        conn.close()


@contextlib.asynccontextmanager
async def lifespan(app):
    validate_production()
    STOP.clear()
    t=threading.Thread(target=worker,daemon=True)
    t.start()
    yield
    STOP.set()
    t.join(timeout=2)


app=FastAPI(title='Dependency Rescue API',version='0.2.0',lifespan=lifespan)
app.add_middleware(RequestGuard)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=os.getenv('RESCUE_ALLOWED_HOSTS','127.0.0.1,localhost,testserver').split(','))


def authorize(request: Request):
    bearer=request.headers.get('authorization','').removeprefix('Bearer ')
    supplied=bearer or request.cookies.get('rescue_session','')
    if not supplied:
        raise HTTPException(401,'API token required')
    actor=verify(supplied,TOKEN)
    if not bearer and request.method not in ['GET','HEAD','OPTIONS'] and not request.headers.get('origin') and request.headers.get('sec-fetch-site')!='same-origin':
        raise HTTPException(403,'Cookie-authenticated writes require same-origin browser evidence')
    origin=request.headers.get('origin')
    if origin and origin not in [f'http://{request.headers.get("host")}',f'https://{request.headers.get("host")}']:
        raise HTTPException(403,'Cross-origin request refused')
    return actor


def audit(actor,action,run_id,digest=''):
    with db() as c:
        c.execute('INSERT INTO audit(time,actor,action,run_id,evidence_digest) VALUES (?,?,?,?,?)',(time.time(),actor['id'],action,run_id,digest))


@app.post('/api/session')
def session(request:Request,actor=Depends(authorize)):
    response=JSONResponse({'actor':actor['id'],'roles':actor['roles']})
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if not token:
        raise HTTPException(400,'Bearer token required for login')
    response.set_cookie('rescue_session',token,httponly=True,samesite='strict',secure=not LOCAL,max_age=3600)
    return response


@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'; connect-src 'self'"
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['X-Frame-Options']='DENY'
    if os.getenv('RESCUE_ENV')=='production':response.headers['Strict-Transport-Security']='max-age=31536000'
    return response


@app.get('/')
def home(request:Request):
    response=FileResponse(ROOT/'rescue/static/index.html')
    if LOCAL and request.client and request.client.host in ['127.0.0.1','::1','testclient']:
        response.set_cookie('rescue_session',TOKEN,httponly=True,samesite='strict',max_age=3600)
        response.headers['X-Rescue-Local-Session']='renewed'
    return response


@app.get('/healthz')
def health():
    return {'status':'ok','mode':os.getenv('RESCUE_ENV','development'),'runner':os.getenv('RESCUE_RUNNER','seatbelt')}


@app.get('/readyz')
def ready():
    from .readiness import check
    status=check()
    return JSONResponse(status,status_code=200 if status['ready'] else 503)


@app.get('/api/cases',dependencies=[Depends(authorize)])
def cases():
    return [c.public() for c in registry().values()]


class Start(BaseModel):
    case_id:str='v8r-js-yaml'
    idempotency_key:str=Field(min_length=8,max_length=100)


def ensure_execution_ready(selected):
    from .readiness import check
    if not selected.public()['ready']:
        raise HTTPException(503,'Prepared repository environment is unavailable')
    if not check()['ready']:
        raise HTTPException(503,'Model or execution worker unavailable; check /readyz')


@app.post('/api/runs',status_code=202,dependencies=[Depends(authorize)])
def start(body:Start,actor=Depends(authorize)):
    require(actor,'operator')
    if body.case_id not in registry():
        raise HTTPException(422,'Case not qualified')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT id,case_id FROM jobs WHERE key=?',(body.idempotency_key,)).fetchone()
        if existing:
            if existing['case_id']!=body.case_id:
                raise HTTPException(409,'Idempotency key already belongs to another case')
            return {'run_id':existing['id']}
        ensure_execution_ready(registry()[body.case_id])
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=3:
            raise HTTPException(429,'Queue full')
        run_id=uuid.uuid4().hex
        try:
            c.execute('INSERT INTO jobs(id,key,status,created,error,case_id,actor) VALUES (?,?,?,?,?,?,?)',(run_id,body.idempotency_key,'queued',time.time(),None,body.case_id,actor['id']))
        except sqlite3.IntegrityError:
            return {'run_id':c.execute('SELECT id FROM jobs WHERE key=?',(body.idempotency_key,)).fetchone()[0]}
    audit(actor,'submit',run_id)
    return {'run_id':run_id}


@app.get('/api/runs',dependencies=[Depends(authorize)])
def listing():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,status,created,error,case_id FROM jobs ORDER BY created DESC LIMIT 100')]


def state(run_id):
    if not (len(run_id)==32 and all(c in '0123456789abcdef' for c in run_id)):
        raise HTTPException(404,'Run not found')
    graph,conn=open_graph()
    try:
        snapshot=graph.get_state({'configurable':{'thread_id':run_id}})
        if not snapshot.values:
            with db() as c:
                row=c.execute('SELECT status FROM jobs WHERE id=?',(run_id,)).fetchone()
                if row:
                    return {'run_id':run_id,'status':row['status'],'events':[]}
            raise HTTPException(404,'Run not found')
        values=dict(snapshot.values)
        values.pop('sources',None)
        with db() as c:
            job=c.execute('SELECT status,error FROM jobs WHERE id=?',(run_id,)).fetchone()
            if job and job['status'] in ['blocked','cancelled'] and job['error']:
                values.update(status=job['status'],error='Worker stopped: '+job['error'])
        return values
    finally:
        conn.close()


@app.get('/api/runs/{run_id}',dependencies=[Depends(authorize)])
def detail(run_id:str):
    return state(run_id)


class Decision(BaseModel):
    approve:bool
    evidence_digest:str=Field(min_length=64,max_length=64)


DECISION_LOCK=threading.Lock()


@app.post('/api/runs/{run_id}/decision',dependencies=[Depends(authorize)])
def decision(run_id:str,body:Decision,actor=Depends(authorize)):
    require(actor,'reviewer')
    with DECISION_LOCK:
        current=state(run_id)
        if current['status']!='awaiting_approval':
            raise HTTPException(409,'Run is not awaiting approval')
        if body.evidence_digest!=current['evidence_digest']:
            raise HTTPException(409,'Evidence changed; refresh before approval')
        graph,conn=open_graph()
        try:
            graph.invoke(Command(resume=body.model_dump()),{'configurable':{'thread_id':run_id}})
        finally:
            conn.close()
        updated=state(run_id)
        audit(actor,'approve' if body.approve else 'reject',run_id,body.evidence_digest)
        with db() as c:
            c.execute('UPDATE jobs SET status=? WHERE id=?',(updated['status'],run_id))
        return updated


@app.post('/api/runs/{run_id}/cancel')
def cancel(run_id:str,actor=Depends(authorize)):
    require(actor,'operator');current=state(run_id)
    if current['status'] not in ['running','queued','awaiting_approval']:
        raise HTTPException(409,'Run is terminal')
    folder=RUNTIME/run_id;folder.mkdir(exist_ok=True)
    (folder/'cancel').touch()
    with db() as c:
        c.execute("UPDATE jobs SET status='cancelled',error='Cancelled by operator' WHERE id=?",(run_id,))
    audit(actor,'cancel',run_id)
    return {'run_id':run_id,'status':'cancelled'}


@app.get('/api/runs/{run_id}/audit',dependencies=[Depends(authorize)])
def audit_history(run_id:str):
    state(run_id)
    with db() as c:
        return [dict(r) for r in c.execute('SELECT time,actor,action,evidence_digest FROM audit WHERE run_id=? ORDER BY id',(run_id,))]


@app.post('/api/runs/{run_id}/publish')
def publish(run_id:str,actor=Depends(authorize)):
    require(actor,'reviewer')
    with DECISION_LOCK:
        current=state(run_id)
        if current['status']!='completed':
            raise HTTPException(409,'Approve patch export before delivery')
        from .graph import export, workspace, case
        from .delivery import publish as deliver
        graph,conn=open_graph()
        try:
            snapshot=dict(graph.get_state({'configurable':{'thread_id':run_id}}).values)
            if export(snapshot)['status']!='completed':
                raise HTTPException(409,'Evidence is stale')
            result=deliver(case(snapshot),snapshot,workspace(snapshot))
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from None
        finally:
            conn.close()
        audit(actor,'publish-draft-pr',run_id,current['evidence_digest'])
        return result


@app.get('/api/runs/{run_id}/patch',dependencies=[Depends(authorize)])
def patch(run_id:str):
    current=state(run_id)
    if current['status']!='completed':
        raise HTTPException(409,'Patch export requires approval')
    try:
        payload=(RUNTIME/run_id/'repair.patch').read_bytes()
    except OSError:
        raise HTTPException(409,'Approved artifact is missing') from None
    if payload!=current['patch'].encode():
        raise HTTPException(409,'Approved artifact has changed')
    return Response(payload,media_type='text/plain',headers={'Content-Disposition':'attachment; filename="repair.patch"'})


app.mount('/static',StaticFiles(directory=ROOT/'rescue/static'),name='static')
