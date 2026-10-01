"""Run a command with an explicit dotenv file; never evaluate shell expressions."""
import argparse
import os
from pathlib import Path
import re
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--env-file',type=Path,default=Path('.env'))
parser.add_argument('command',nargs=argparse.REMAINDER)
args=parser.parse_args()
if not args.command:parser.error('A command is required')
env=os.environ.copy()
for line in args.env_file.read_text().splitlines():
    line=line.strip()
    if not line or line.startswith('#'):continue
    name,sep,value=line.partition('=')
    if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*',name):raise SystemExit('Invalid environment entry')
    value=value.strip()
    if len(value)>=2 and value[0]==value[-1] and value[0] in ['\"',"'"]:value=value[1:-1]
    env[name]=value
raise SystemExit(subprocess.call(args.command,env=env))
