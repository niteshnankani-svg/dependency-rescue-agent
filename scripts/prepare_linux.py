"""Recreate pinned benchmark environments in Linux. Never downloads gold solutions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import ROOT,DATA,cases
from rescue.execution import docker_prefix


def main():
    parser=argparse.ArgumentParser();parser.add_argument('case_ids',nargs='*');args=parser.parse_args()
    hashes=json.loads((ROOT/'bootstrap/sources.json').read_text())
    selected=cases()
    for case_id in args.case_ids or selected:
        case=selected[case_id]
        subprocess.run([*docker_prefix(),'pull',case.image],check=True)
        download=DATA/'downloads';download.mkdir(parents=True,exist_ok=True)
        archive=download/(case.id+'.tar.gz')
        if not archive.exists():
            with httpx.Client(timeout=120,follow_redirects=True) as client:
                response=client.get(f'https://codeload.github.com/{case.repository}/tar.gz/{case.base_commit}')
                response.raise_for_status();archive.write_bytes(response.content)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=hashes[case.id]:
            raise ValueError('Pinned source checksum mismatch: '+case.id)
        case.templates.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=download) as tmp:
            with tarfile.open(archive) as tar:tar.extractall(tmp,filter='data')
            source=next(Path(tmp).iterdir())
            for phase in ['baseline','upgraded']:
                dest=case.templates/phase
                if dest.exists():
                    print(f'{case.id}/{phase}: exists; refusing to overwrite',flush=True);continue
                staging=case.templates/(phase+'-staging')
                if staging.exists():shutil.rmtree(staging)
                shutil.copytree(source,staging)
                if case.id in ['v8r-js-yaml','hexo-uglify-terser'] or (case.id in ['hexo-yam-svgo','get-jwks-lru'] and phase=='upgraded'):
                    # This case is explicitly development data: canonical test additions were used.
                    patch=(ROOT/'bootstrap'/case.id/'test-migration.patch').read_bytes()
                    subprocess.run(['git','apply','-'],input=patch,cwd=staging,env={**os.environ,'GIT_CEILING_DIRECTORIES':str(staging.parent)},check=True)
                for name in ['package.json','package-lock.json']:
                    shutil.copyfile(ROOT/'bootstrap'/case.id/phase/name,staging/name)
                # Setup has network access, no credentials, and never executes lifecycle scripts.
                name='rescue-setup-'+uuid.uuid4().hex
                try:
                    subprocess.run([*docker_prefix(),'run','--rm','--name',name,'--user',f'{os.getuid()}:{os.getgid()}','--env','HOME=/tmp','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128','--memory=768m','--cpus=1','--mount',f'type=bind,src={staging},dst=/app','--workdir','/app',case.image,'npm','ci','--ignore-scripts','--package-lock=true','--no-audit','--no-fund'],check=True,timeout=600)
                finally:
                    subprocess.run([*docker_prefix(),'rm','-f',name],capture_output=True,timeout=20)
                lock=json.loads((ROOT/'bootstrap'/case.id/phase/'package-lock.json').read_text())
                expected=lock['packages']['node_modules/'+case.dependency]['version'] if 'packages' in lock else lock['dependencies'][case.dependency]['version']
                if case.version(staging)!=expected:raise ValueError('Installed version mismatch')
                staging.replace(dest)
                print(f'{case.id}/{phase}: ready',flush=True)


if __name__=='__main__':main()
