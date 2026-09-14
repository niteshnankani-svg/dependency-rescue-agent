"""Read repository metadata and README files without cloning or executing code."""
import base64
import concurrent.futures
import json
from pathlib import Path
import subprocess


def gh(path):
    result=subprocess.run(['gh','api',path],capture_output=True,text=True,timeout=30)
    return json.loads(result.stdout) if result.returncode==0 else None


def inspect(repo):
    base='repos/'+repo['full_name']
    readme=gh(base+'/readme')
    tree=gh(base+'/git/trees/'+repo['default_branch']+'?recursive=1') if repo['size'] else None
    files=[x['path'] for x in (tree or {}).get('tree',[]) if x['type']=='blob']
    content=base64.b64decode(readme['content']).decode('utf-8',errors='replace') if readme and readme.get('content') else ''
    return {'name':repo['name'],'url':repo['html_url'],'private':repo['private'],'description':repo['description'],
        'default_branch':repo['default_branch'],'file_count':len(files),'tree_truncated':(tree or {}).get('truncated'),
        'readme':content,'implementation_files':[p for p in files if p.endswith(('.py','.ts','.tsx','.js','.ipynb'))][:100],
        'build_files':[p for p in files if p.split('/')[-1] in ['Dockerfile','pyproject.toml','requirements.txt','package.json','uv.lock','poetry.lock']]}


if __name__=='__main__':
    repos=gh('users/niteshnankani-svg/repos?per_page=100')
    # Authenticated owned repositories include private work not visible in public listings.
    owned=gh('user/repos?affiliation=owner&per_page=100')
    if owned is not None:
        repos=owned
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(inspect,repos))
    dest=Path('research/private/github-inventory.json')
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(records,indent=2))
    print(json.dumps([{k:r[k] for k in ['name','file_count','build_files']} for r in records],indent=2))
