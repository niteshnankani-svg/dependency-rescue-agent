"""Reverify a copied successful candidate and test durable approval; no external writes."""
import json
from pathlib import Path
import shutil
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from langgraph.types import Command
from rescue.config import ROOT,RUNTIME
from rescue.graph import open_graph,verify

report=json.loads((ROOT/'reports/v8r-js-yaml-evaluation.json').read_text())
assert report['status']=='awaiting_approval'
source=RUNTIME/report['run_id'];state=json.loads((source/'state.json').read_text())
run_id=uuid.uuid4().hex;dest=RUNTIME/run_id
shutil.copytree(source/'workspace',dest/'workspace',symlinks=True)
state={**state,'run_id':run_id,'events':[]}
state.update(verify(state));assert state['verification']['ok']
graph,conn=open_graph();config={'configurable':{'thread_id':run_id}}
graph.update_state(config,state,as_node='verify');graph.invoke(None,config)
assert graph.get_state(config).values['status']=='awaiting_approval'
conn.close()
# Fresh connection simulates restart at the durable human-review interrupt.
graph,conn=open_graph();snapshot=graph.get_state(config).values
graph.invoke(Command(resume={'approve':True,'evidence_digest':snapshot['evidence_digest']}),config)
final=graph.get_state(config).values
assert final['status']=='completed' and (dest/'repair.patch').read_text()==final['patch']
conn.close()
(ROOT/'reports/review-smoke.json').write_text(json.dumps({'run_id':run_id,'source_run_id':report['run_id'],'scope':'Test-owned copy; original pending review unchanged','linux_reverification':state['verification'],'approval_persisted_across_reopen':True,'patch_export_readback':True},indent=2)+'\n')
print('Fresh Linux verification, durable review and patch export passed: '+run_id)
