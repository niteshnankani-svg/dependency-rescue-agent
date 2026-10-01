"""Exercise built API/worker images locally, without a model call or external writes."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import ROOT,RUNTIME,get_case
from rescue.execution import docker_prefix
from rescue.guards import source_files

prefix=docker_prefix();suffix=secrets.token_hex(4)
worker='rescue-smoke-worker-'+suffix;api='rescue-smoke-api-'+suffix;network='rescue-smoke-'+suffix
folder=RUNTIME/'container-smoke';folder.mkdir(parents=True,exist_ok=True)
work=folder/'workspaces';work.mkdir(exist_ok=True)
executor_token=secrets.token_urlsafe(32);operator=secrets.token_urlsafe(32);reviewer=secrets.token_urlsafe(32)
envfile=folder/'secrets.env'
fd=os.open(envfile,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
with os.fdopen(fd,'w') as f:
 f.write('RESCUE_EXECUTOR_TOKEN='+executor_token+'\nRESCUE_AUTH_KEYS='+json.dumps([{'id':'operator','token':operator,'roles':['operator']},{'id':'reviewer','token':reviewer,'roles':['reviewer']}])+'\n')

def docker(*args):return subprocess.run([*prefix,*args],check=True,capture_output=True,text=True).stdout.strip()
def wait(url):
 for _ in range(60):
  try:
   if httpx.get(url,timeout=3).status_code==200:return
  except httpx.HTTPError:pass
  time.sleep(1)
 raise RuntimeError('Service did not become healthy: '+url)

checks={}
try:
 docker('network','create',network)
 common=['--detach','--rm','--network',network,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp:size=64m','--env-file',str(envfile),'--mount',f'type=bind,src={ROOT}/data/external,dst=/data,readonly']
 docker('run',*common,'--name',worker,'-p','127.0.0.1:8094:8094','--mount','type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock','--mount',f'type=bind,src={work},dst={work}','-e','RESCUE_WORKSPACE_ROOT='+str(work),'dependency-rescue-executor:local')
 wait('http://127.0.0.1:8094/healthz');checks['worker_docker_health']=True
 docker('run',*common,'--name',api,'-p','127.0.0.1:8095:8093','--tmpfs','/runtime:uid=10001,gid=10001,mode=700,size=64m','-e','RESCUE_ENV=production','-e','RESCUE_RUNNER=remote','-e','RESCUE_PRIVATE_EXECUTOR=1','-e','RESCUE_EXECUTOR_URL=http://'+worker+':8094','-e','RESCUE_MODEL='+os.getenv('RESCUE_MODEL','qwen3:4b'),'-e','RESCUE_MODEL_URL=http://host.docker.internal:11434','-e','RESCUE_ALLOWED_HOSTS=localhost,127.0.0.1','dependency-rescue:local')
 wait('http://127.0.0.1:8095/healthz');checks['production_api_startup']=True
 with httpx.Client(base_url='http://127.0.0.1:8095',timeout=10) as client:
  assert client.get('/api/cases').status_code==401;checks['unauthenticated_request_refused']=True
  r=client.get('/api/cases',headers={'Authorization':'Bearer '+operator});r.raise_for_status();assert len(r.json())==4;checks['registered_cases_visible']=True
  r=client.post('/api/runs/'+'a'*32+'/decision',headers={'Authorization':'Bearer '+operator},json={'approve':True,'evidence_digest':'a'*64});assert r.status_code==403;checks['operator_cannot_approve']=True
  r=client.post('/api/runs',headers={'Authorization':'Bearer '+reviewer},json={'idempotency_key':'smoke-forbidden'});assert r.status_code==403;checks['reviewer_cannot_execute']=True
  r=client.post('/api/session',headers={'Authorization':'Bearer '+reviewer});assert r.status_code==200 and 'Secure' in r.headers['set-cookie'] and 'HttpOnly' in r.headers['set-cookie'];checks['secure_login_cookie']=True
 case=get_case();root=case.templates/'baseline'
 payload={'case_id':case.id,'phase':'baseline','files':{str(p.relative_to(root)):p.read_text() for p in source_files(root,case.source_globs)}}
 r=httpx.post('http://127.0.0.1:8094/execute',headers={'Authorization':'Bearer '+executor_token},json=payload,timeout=180);r.raise_for_status();result=r.json();assert result['ok'] and result['passes']==20
 checks['remote_baseline_execution']=result
 # Prove the API image cannot find the host Docker socket.
 assert docker('exec',api,'python','-c',"from pathlib import Path; assert not Path('/var/run/docker.sock').exists()") == ''
 checks['api_has_no_docker_socket']=True
 checks['readyz']=httpx.get('http://127.0.0.1:8095/readyz',timeout=10).json()
 assert checks['readyz']['ready'],checks['readyz']
 (ROOT/'reports/container-smoke.json').write_text(json.dumps(checks,indent=2).replace(str(ROOT),'<project>')+'\n')
 print(json.dumps(checks,indent=2))
finally:
 for name in [api,worker]:subprocess.run([*prefix,'rm','-f',name],capture_output=True)
 subprocess.run([*prefix,'network','rm',network],capture_output=True)
 envfile.unlink(missing_ok=True)
