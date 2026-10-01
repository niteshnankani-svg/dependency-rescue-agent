"""Prepare additional pinned development environments without gold or verifier access."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SPECS=[
 {'id':'hexo-uglify-terser','repository':'hexojs/hexo-uglify','base_commit':'cca9eb7376b0a2fff9f2e6163957c99c73a55539','dependency':'terser','old_version':'4.3.9','target_version':'5.3.0','dataset_task':'hexojs__hexo-uglify__147','source_globs':['lib/*.js','index.js'],'test_args':['node_modules/mocha/bin/mocha','test/index.js','--reporter','json','--timeout','5000'],'max_edits':3},
 {'id':'get-jwks-lru','repository':'nearform/get-jwks','base_commit':'d3d40dd801bd6600fab7377f1cc4575245ef4bbd','dependency':'lru-cache','old_version':'8.0.0','target_version':'9.0.0','dataset_task':'nearform__get-jwks__197','source_globs':['src/*.js'],'test_args':['node_modules/tap/bin/run.js','--no-coverage','--reporter=json','test/*.spec.js'],'reporter':'tap','max_edits':1},
 {'id':'hexo-yam-svgo','repository':'curbengh/hexo-yam','base_commit':'4b4d3cb342dd9c7c0d6ac78fb86b064eb2fde6ff','dependency':'svgo','old_version':'2.4.0','target_version':'3.0.0','dataset_task':'curbengh__hexo-yam__135','source_globs':['lib/*.js','index.js'],'test_args':['node_modules/jest/bin/jest.js','--json','--runInBand','--coverage=false','--cacheDirectory=/tmp/jest','--no-cache'],'reporter':'jest','max_edits':3},
]


def main():
    existing=json.loads((ROOT/'cases.json').read_text())
    for spec in SPECS:
        folder=ROOT/'data/external'/spec['dataset_task']
        source=next((folder/'source').iterdir())
        spec['template_dir']=spec['dataset_task']+'/templates'
        spec['evaluation_role']='original tests for repair; independent verifier pending'
        templates=folder/'templates';templates.mkdir(exist_ok=True)
        for phase,version in [('baseline',spec['old_version']),('upgraded',spec['target_version'])]:
            dest=templates/phase
            if not dest.exists():
                shutil.copytree(source if phase=='baseline' else templates/'baseline',dest,symlinks=True)
            command=['npm','install','--ignore-scripts','--no-audit','--no-fund','--save-prefix=^',spec['dependency']+'@'+version]
            subprocess.run(command,cwd=dest,check=True,timeout=300)
            installed=json.loads((dest/'node_modules'/spec['dependency']/'package.json').read_text())['version']
            assert installed==version,(spec['id'],phase,installed)
        existing=[c for c in existing if c['id']!=spec['id']]+[spec]
        (ROOT/'cases.json').write_text(json.dumps(existing,indent=2)+'\n')
        print('Prepared '+spec['id'],flush=True)


if __name__=='__main__':
    main()
