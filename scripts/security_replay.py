"""Replay known repairs through current policies without model calls or modifying reviews."""
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import ROOT,RUNTIME,get_case
from rescue.guards import Repair,apply_repair,source_preflight
from rescue.security import screen_evidence,screen_output
from rescue.model import context

results=[]
for report_file in sorted((ROOT/'reports').glob('*-evaluation.json')):
    report=json.loads(report_file.read_text());case=get_case(report['case_id'])
    state=json.loads((RUNTIME/report['run_id']/'state.json').read_text())
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp).resolve()
        for name,content in state['sources'].items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        source_preflight(root,case.source_globs)
        failures=[{k:str(f.get(k,''))[:1800] for k in ['title','message','stack']} for f in state['broken'].get('failures',[])[:3]]
        screen_evidence({'source':context(root,{'failures':failures},case),'docs':state['api_evidence'],'failures':failures})
        screen_output(json.dumps(state['repair']))
        apply_repair(root,Repair.model_validate(state['repair']),case.source_globs)
        for name in state['sources']:
            assert (root/name).read_bytes()==(RUNTIME/report['run_id']/'workspace'/name).read_bytes()
    results.append({'case_id':case.id,'input_guard_passed':True,'output_guard_passed':True,'patch_policy_passed':True,'original_review_unchanged':True})
(ROOT/'reports/security-replay.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
