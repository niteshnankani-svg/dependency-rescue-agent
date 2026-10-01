"""Run previously withheld canonical test additions after a model run. No feedback to model."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import get_case,ROOT,RUNTIME
from rescue.runner import run_tests

parser=argparse.ArgumentParser();parser.add_argument('case_id');args=parser.parse_args();case=get_case(args.case_id)
evaluation=json.loads((ROOT/'reports'/f'{case.id}-evaluation.json').read_text())
if evaluation['status']!='awaiting_approval':
    raise SystemExit('Only a successfully verified candidate can enter independent evaluation')
if case.test_migration_files:
    raise SystemExit('This case uses canonical tests as development feedback; it is not an independent holdout.')
run_id=evaluation['run_id'];revision='3eef955c222baa310ef039153755ec9d7cdb03f3'
dest=ROOT/'data/external/depbench'/case.dataset_task/'independent'
dest.mkdir(parents=True,exist_ok=True)
with httpx.Client(timeout=45,follow_redirects=True) as c:
    for filename in ['test.patch','test_state.py']:
        r=c.get(f'https://huggingface.co/datasets/Depbench/build_from_source/resolve/{revision}/dataset/tasks/{case.dataset_task}/tests/{filename}')
        r.raise_for_status();(dest/filename).write_text(r.text)
base=RUNTIME/'independent';base.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=base) as tmp:
    root=Path(tmp)/'repo';shutil.copytree(RUNTIME/run_id/'workspace',root,symlinks=True)
    patch=dest/'test.patch'
    if patch.stat().st_size:
        result=subprocess.run(['git','apply','--unsafe-paths','--directory',str(root),str(patch)],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:
            raise SystemExit('Canonical verifier patch could not apply; not counted as a pass: '+result.stderr[:500])
    result=run_tests(root,case=case)
    result['run_id']=run_id;result['case_id']=case.id
    result['scope']='Canonical verifier test patch, adapted Linux Node18 execution; no feedback to repair model. See test_state.py for any additional commands not covered.'
    (ROOT/'reports'/f'{case.id}-independent.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ok'] else 1)
