"""Run registered cases with real models. Store summaries, never invent successes."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import cases,ROOT,RUNTIME
from rescue.graph import open_graph

parser=argparse.ArgumentParser();parser.add_argument('case_ids',nargs='*')
parser.add_argument('--serial-colima',help='Development only: suspend a dedicated Colima profile during local inference')
args=parser.parse_args()
if args.serial_colima:
    import os
    from rescue import graph as graph_module
    if os.getenv('RESCUE_MODEL_PROVIDER','ollama')!='ollama' or os.getenv('RESCUE_MODEL_URL','http://127.0.0.1:11434') not in ['http://127.0.0.1:11434','http://localhost:11434']:
        raise SystemExit('Serial Colima mode is only for a local Ollama model')
    original_propose=graph_module.propose
    def serial_propose(*values,**kwargs):
        print('resources: suspending dedicated worker VM for local inference',flush=True)
        subprocess.run(['colima','stop',args.serial_colima],check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:return original_propose(*values,**kwargs)
        finally:
            subprocess.run(['ollama','stop',os.getenv('RESCUE_MODEL','qwen3:4b')],timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            print('resources: restoring dedicated worker VM for verification',flush=True)
            subprocess.run(['colima','start',args.serial_colima,'--memory','1.5','--activate=false','--ssh-config=false','--downloader','curl'],check=True,timeout=180,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    graph_module.propose=serial_propose
graph,connection=open_graph()
summaries=[]
for case_id in args.case_ids or list(cases()):
    run_id=uuid.uuid4().hex;config={'configurable':{'thread_id':run_id}}
    print(case_id+' '+run_id,flush=True)
    try:
        for update in graph.stream({'run_id':run_id,'case_id':case_id,'events':[]},config,stream_mode='updates'):
            for node,result in update.items():
                if node!='__interrupt__':
                    print(node+' '+json.dumps(result.get('events',[])),flush=True)
        state=dict(graph.get_state(config).values)
        (RUNTIME/run_id/'state.json').write_text(json.dumps(state,indent=2))
        report={k:state.get(k) for k in ['run_id','case_id','status','baseline','broken','verification','attempts','model_calls','events','error']}
        report['reference_solution_accessed']=False
        report['independent_verifier']='not yet run'
    except Exception as exc:
        report={'run_id':run_id,'case_id':case_id,'status':'blocked','error':type(exc).__name__+': '+str(exc)[:500]}
    report=json.loads(json.dumps(report).replace(str(ROOT),'<project>'))
    output=ROOT/'reports'/f'{case_id}-evaluation.json'
    temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(output)
    summaries.append(report)
    print('RESULT '+case_id+' '+report['status'],flush=True)
connection.close()
