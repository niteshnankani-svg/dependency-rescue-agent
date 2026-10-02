"""Real Python dependency regression through the graph, stopping at review."""
import json,shutil,sqlite3,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import Case,DATA,ROOT,RUNTIME
from rescue import python_profile as profile
from rescue.graph import open_graph

root=DATA/'imports/python-httpx-validation'
if root.exists():raise SystemExit('Validation fixture already exists; preserve its evidence')
root.mkdir(parents=True);base=root/'baseline';base.mkdir()
(base/'requirements.txt').write_text('httpx==0.27.2\n')
(base/'client.py').write_text('''import httpx

def request_text():
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ready"]
    with httpx.Client(app=app, base_url="http://testserver") as client:
        return client.get("/").text
''')
(base/'test_client.py').write_text('''from client import request_text
import os

def test_wsgi_response():
    assert request_text() == "ready"

def test_no_provider_credentials():
    assert not any(name in os.environ for name in ["RESCUE_MODEL_API_KEY", "GITHUB_TOKEN", "GOOGLE_CLIENT_SECRET"])
''')
up=root/'upgraded';shutil.copytree(base,up);(up/'requirements.txt').write_text('httpx==0.28.1\n')
case=Case(id='python-httpx-validation',repository='encode/httpx',base_commit='0'*40,dependency='httpx',old_version='0.27.2',target_version='0.28.1',template_dir='imports/python-httpx-validation',source_globs=['*.py'],test_args=['-c',profile.TEST_CODE],language='python',reporter='pytest',image=profile.IMAGE,evaluation_role='development — local HTTPX API regression fixture; not an independent customer evaluation',max_attempts=2)
for folder,version in [(base,'0.27.2'),(up,'0.28.1')]:
 print('Preparing HTTPX '+version,flush=True);profile.setup(folder,case,['httpx=='+version])
registry=DATA/'imports/registry.json';rows=json.loads(registry.read_text()) if registry.exists() else [];rows.append(case.model_dump());registry.write_text(json.dumps(rows))
graph,connection=open_graph();run_id=uuid.uuid4().hex;config={'configurable':{'thread_id':run_id}}
try:
 for update in graph.stream({'run_id':run_id,'case_id':case.id,'events':[]},config,stream_mode='updates'):
  for name,result in update.items():
   if name!='__interrupt__':print(name+': '+result.get('status','')+' '+json.dumps(result.get('events',[])),flush=True)
 state=dict(graph.get_state(config).values)
 with sqlite3.connect(RUNTIME/'jobs.sqlite') as jobs:
  jobs.execute('INSERT INTO jobs (id,key,status,created,case_id,actor) VALUES (?,?,?,?,?,?)',(run_id,'python-validation-'+run_id,state.get('status','blocked'),time.time(),case.id,'validation'))
 (ROOT/'reports/python-validation.json').write_text(json.dumps(state,indent=2)+'\n')
 print(json.dumps({k:state.get(k) for k in ['run_id','status','baseline','broken','verification','error']},indent=2))
finally:connection.close()
