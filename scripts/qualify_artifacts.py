"""Reverify frozen candidates and prove patches apply to pinned pristine sources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import ROOT,RUNTIME,cases
from rescue.graph import open_graph,verify,evidence

graph,connection=open_graph();results=[]
try:
 for case in cases().values():
  report_path=ROOT/'reports'/f'{case.id}-evaluation.json'
  report=json.loads(report_path.read_text())
  if report['status']!='awaiting_approval':raise RuntimeError('Unqualified candidate: '+case.id)
  config={'configurable':{'thread_id':report['run_id']}}
  state=dict(graph.get_state(config).values)
  state.update(verify(state))
  if not state['verification']['ok']:raise RuntimeError('Reverification failed: '+case.id)
  state.update(evidence(state))
  archive=ROOT/'data/external/downloads'/f'{case.id}.tar.gz'
  if not archive.exists():archive=ROOT/'data/external'/('v8r-base.tar.gz' if case.id=='v8r-js-yaml' else case.dataset_task+'/base.tar.gz')
  expected=json.loads((ROOT/'bootstrap/sources.json').read_text())[case.id]
  assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
  with tempfile.TemporaryDirectory(dir=RUNTIME) as tmp:
   with tarfile.open(archive) as tar:tar.extractall(tmp,filter='data')
   pristine=next(Path(tmp).iterdir())
   applied=subprocess.run(['git','apply','-'],input=state['patch'],cwd=pristine,text=True,capture_output=True,env={**os.environ,'GIT_CEILING_DIRECTORIES':str(pristine.parent)})
   if applied.returncode:raise RuntimeError('Patch does not apply: '+case.id+' '+applied.stderr[:300])
   workspace=RUNTIME/report['run_id']/'workspace'
   for name in [*state['sources'],'package.json','package-lock.json',*case.test_migration_files]:
    assert (pristine/name).read_bytes()==(workspace/name).read_bytes(),(case.id,name)
  update={k:v for k,v in state.items() if k not in ['events','model_calls']}
  update['events']=[{'node':'verify','detail':'Final isolated reverification and pristine-base patch application passed'}]
  graph.update_state(config,update,as_node='verify');graph.invoke(None,config)
  state=dict(graph.get_state(config).values)
  (RUNTIME/report['run_id']/'state.json').write_text(json.dumps(state,indent=2))
  report['verification']=state['verification'];report['status']=state['status']
  report['independent_verifier']='Development tests; canonical API-contract migrations are operator supplied, not held out'
  report['artifact_applies_to_pristine_base']=True
  report_path.write_text(json.dumps(report,indent=2).replace(str(ROOT),'<project>')+'\n')
  results.append({'case_id':case.id,'run_id':report['run_id'],'tests_passed':state['verification']['passes'],'additional_checks_passed':all(c['ok'] for c in state['verification'].get('additional_checks',[])),'patch_applies_to_pristine_base':True,'patched_files_equal_verified_files':True})
  print(case.id+': isolated tests and pristine-base patch application passed',flush=True)
finally:connection.close()
(ROOT/'reports/artifact-qualification.json').write_text(json.dumps(results,indent=2)+'\n')
