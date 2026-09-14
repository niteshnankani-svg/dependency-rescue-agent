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

RUNTIME.mkdir(exist_ok=True)
TOKEN_PATH=RUNTIME/'.api-token'
if not TOKEN_PATH.exists():
    fd=os.open(TOKEN_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(secrets.token_urlsafe(32))
TOKEN=os.getenv('RESCUE_API_TOKEN') or TOKEN_PATH.read_text().strip()
LOCAL=not bool(os.getenv('RESCUE_API_TOKEN'))
STOP=threading.Event()


def db():
    c=sqlite3.connect(RUNTIME/'jobs.sqlite',timeout=10)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, key TEXT UNIQUE, status TEXT, created REAL, error TEXT)')
    c.commit()
    return c


def worker():
    graph,conn=open_graph()
    try:
        while not STOP.is_set():
            with db() as c:
                row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    c.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            if not row:
                STOP.wait(.5)
                continue
            config={'configurable':{'thread_id':row['id']}}
            try:
                existing=graph.get_state(config)
                graph.invoke(None if existing.values else {'run_id':row['id'],'events':[]},config)
                status=graph.get_state(config).values.get('status','blocked')
                with db() as c:
                    c.execute('UPDATE jobs SET status=? WHERE id=?',(status,row['id']))
            except Exception as exc:
                with db() as c:
                    c.execute("UPDATE jobs SET status='blocked', error=? WHERE id=?",(type(exc).__name__,row['id']))
    finally:
        conn.close()


@contextlib.asynccontextmanager
async def lifespan(app):
    STOP.clear()
    with db() as c:
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
    t=threading.Thread(target=worker,daemon=True)
    t.start()
    yield
    STOP.set()
    t.join(timeout=2)


app=FastAPI(title='Dependency Rescue API',version='0.1.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])


def authorize(request: Request):
    bearer=request.headers.get('authorization','').removeprefix('Bearer ')
    supplied=bearer or request.cookies.get('rescue_session','')
    if not supplied or not hmac.compare_digest(supplied,TOKEN):
        raise HTTPException(401,'API token required')
    origin=request.headers.get('origin')
    if origin and origin not in [f'http://{request.headers.get("host")}',f'https://{request.headers.get("host")}']:
        raise HTTPException(403,'Cross-origin request refused')


@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.get('/')
def home(request:Request):
    response=FileResponse(ROOT/'rescue/static/index.html')
    if LOCAL and request.client and request.client.host in ['127.0.0.1','::1','testclient']:
        response.set_cookie('rescue_session',TOKEN,httponly=True,samesite='strict',max_age=3600)
    return response


@app.get('/healthz')
def health():
    return {'status':'ok','mode':'local-pilot','runner':'macOS Seatbelt','production_qualified':False}


@app.get('/api/cases',dependencies=[Depends(authorize)])
def cases():
    return [{'id':'v8r-js-yaml','repository':'chris48s/v8r','dependency':'js-yaml','from':'3.14.x','to':'4.0.0','source':'DepBench','license':'MIT','scope':'Real development case; adapted macOS harness; not held-out benchmark score','ready':(ROOT/'data/external/templates/upgraded/node_modules/js-yaml/package.json').exists()}]


class Start(BaseModel):
    case_id:str='v8r-js-yaml'
    idempotency_key:str=Field(min_length=8,max_length=100)


@app.post('/api/runs',status_code=202,dependencies=[Depends(authorize)])
def start(body:Start):
    if body.case_id!='v8r-js-yaml':
        raise HTTPException(422,'Case not qualified')
    with db() as c:
        existing=c.execute('SELECT id FROM jobs WHERE key=?',(body.idempotency_key,)).fetchone()
        if existing:
            return {'run_id':existing['id']}
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=3:
            raise HTTPException(429,'Queue full')
        run_id=uuid.uuid4().hex
        try:
            c.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(run_id,body.idempotency_key,'queued',time.time(),None))
        except sqlite3.IntegrityError:
            return {'run_id':c.execute('SELECT id FROM jobs WHERE key=?',(body.idempotency_key,)).fetchone()[0]}
    return {'run_id':run_id}


@app.get('/api/runs',dependencies=[Depends(authorize)])
def listing():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,status,created,error FROM jobs ORDER BY created DESC LIMIT 100')]


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
            if job and job['status']=='blocked' and job['error']:
                values.update(status='blocked',error='Worker failed: '+job['error'])
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
def decision(run_id:str,body:Decision):
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
        with db() as c:
            c.execute('UPDATE jobs SET status=? WHERE id=?',(updated['status'],run_id))
        return updated


@app.get('/api/runs/{run_id}/patch',dependencies=[Depends(authorize)])
def patch(run_id:str):
    current=state(run_id)
    if current['status']!='completed':
        raise HTTPException(409,'Patch export requires approval')
    return FileResponse(RUNTIME/run_id/'repair.patch',media_type='text/plain',filename='repair.patch')


app.mount('/static',StaticFiles(directory=ROOT/'rescue/static'),name='static')
