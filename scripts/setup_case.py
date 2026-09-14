"""Prepare the qualified case from official pinned artifacts, without repair solutions."""
import hashlib
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import httpx

ROOT=Path(__file__).resolve().parents[1]
EXTERNAL=ROOT/'data/external'


def main():
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise SystemExit('This qualified case setup currently supports Apple Silicon macOS only.')
    EXTERNAL.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=120,follow_redirects=True) as client:
        files={
            'v8r-base.tar.gz':'https://codeload.github.com/chris48s/v8r/tar.gz/febc231dc747a4743322ea5eb7d91ca4dc81177d',
            'node18.tar.gz':'https://nodejs.org/dist/v18.20.8/node-v18.20.8-darwin-arm64.tar.gz',
            'node18-SHASUMS256.txt':'https://nodejs.org/dist/v18.20.8/SHASUMS256.txt',
        }
        for name,url in files.items():
            target=EXTERNAL/name
            if not target.exists():
                response=client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
    source=EXTERNAL/'v8r/v8r-febc231dc747a4743322ea5eb7d91ca4dc81177d'
    if not source.exists():
        with tarfile.open(EXTERNAL/'v8r-base.tar.gz') as archive:
            archive.extractall(EXTERNAL/'v8r',filter='data')
    for name in ['depbench.py','prepare_case.py']:
        subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,check=True)
    npm=['npm','ci','--ignore-scripts','--no-audit','--no-fund']
    subprocess.run(npm,cwd=source,check=True)
    if not (EXTERNAL/'templates').exists():
        subprocess.run([sys.executable,str(ROOT/'scripts/build_templates.py')],cwd=ROOT,check=True)
    subprocess.run(npm,cwd=EXTERNAL/'templates/upgraded',check=True)
    print('Case ready. Start the API or run scripts/run_case.py.')


if __name__=='__main__':
    main()
