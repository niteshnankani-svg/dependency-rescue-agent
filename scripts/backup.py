"""Consistent SQLite backup, plus review artifacts. Keep the output private."""
import argparse
from pathlib import Path
import shutil
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import RUNTIME

parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);parser.add_argument('--include-workspaces',action=argparse.BooleanOptionalAction,default=True);args=parser.parse_args()
dest=args.destination.resolve();dest.mkdir(parents=True,exist_ok=False,mode=0o700)
for name in ['jobs.sqlite','checkpoints.sqlite']:
    with sqlite3.connect(RUNTIME/name) as source,sqlite3.connect(dest/name) as target:
        source.backup(target)
for p in RUNTIME.glob('*/repair.patch'):
    (dest/p.parent.name).mkdir(exist_ok=True);shutil.copy2(p,dest/p.parent.name/p.name)
if args.include_workspaces:
    for p in RUNTIME.glob('*/workspace'):
        shutil.copytree(p,dest/p.parent.name/'workspace',symlinks=True)
print('Backup complete. Stop workers during backup/restore for a consistent set of workspace files. Credentials are not included.')
