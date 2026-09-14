"""Run the real development case to the review gate. Never auto-approve."""
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.graph import open_graph, ROOT

graph,connection=open_graph()
run_id=uuid.uuid4().hex
config={'configurable':{'thread_id':run_id}}
print('Run '+run_id,flush=True)
try:
    for update in graph.stream({'run_id':run_id,'events':[]},config,stream_mode='updates'):
        for node,result in update.items():
            if node!='__interrupt__':
                print(node+': '+result.get('status','')+' '+json.dumps(result.get('events',[])),flush=True)
    state=dict(graph.get_state(config).values)
    (ROOT/'reports/latest-run.json').write_text(json.dumps(state,indent=2))
    print(json.dumps({k:state.get(k) for k in ['run_id','status','baseline','broken','verification','model_usage','error']},indent=2),flush=True)
finally:
    connection.close()
