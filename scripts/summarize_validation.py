import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
state=json.loads((root/'reports/latest-run.json').read_text())
report={k:state.get(k) for k in ['run_id','status','baseline','broken','verification','model_usage','attempts','events']}
report.update({'date':'2026-09-14','case':'chris48s__v8r__22','dataset_revision':'3eef955c222baa310ef039153755ec9d7cdb03f3','evaluation':'Development case; canonical verifier tests used for feedback; adapted macOS harness, not official or held-out benchmark score','reference_solution_accessed':False,'earlier_development_runs':['8ec5b0fe0eec4cd48077cc6722583997: rejected duplicate edit','3480dc55ef5840a58b548446884a25cc: rejected nonexistent anchors, escalated'],'production_qualified':False})
text=json.dumps(report,indent=2).replace(str(root),'<project>')
(root/'reports/validation.json').write_text(text+'\n')
rows=json.loads((root/'research/private/github-inventory.json').read_text())
overview=[{k:r.get(k) for k in ['name','file_count','tree_truncated','build_files']} for r in rows]
(root/'research/github-summary.json').write_text(json.dumps(overview,indent=2)+'\n')
print('Sanitized validation and inventory summaries saved.')
