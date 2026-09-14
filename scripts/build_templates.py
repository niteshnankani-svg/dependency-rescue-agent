"""Prepare two frozen local development-case environments; not a benchmark score."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile

root=Path(__file__).resolve().parents[1]
external=root/'data/external'
expected=next(l.split()[0] for l in (external/'node18-SHASUMS256.txt').read_text().splitlines() if l.endswith('node-v18.20.8-darwin-arm64.tar.gz'))
assert hashlib.sha256((external/'node18.tar.gz').read_bytes()).hexdigest()==expected
with tarfile.open(external/'node18.tar.gz') as archive:
    archive.extractall(external,filter='data')
base=next((external/'v8r').iterdir())
case=external/'depbench/chris48s__v8r__22'
templates=external/'templates'
templates.mkdir(exist_ok=True)
for name in ['baseline','upgraded']:
    dest=templates/name
    if dest.exists():
        raise SystemExit(f'{dest} already exists; refusing to overwrite')
    shutil.copytree(base,dest)
    subprocess.run(['git','apply','--unsafe-paths','--directory',str(dest),str(case/'tests/test.patch')],cwd=root,check=True)
    if name=='upgraded':
        subprocess.run(['git','apply','--unsafe-paths','--directory',str(dest),str(case/'environment/patches/manifest.patch')],cwd=root,check=True)
print('Templates prepared; install upgraded dependencies with npm ci --ignore-scripts before running the graph.')
