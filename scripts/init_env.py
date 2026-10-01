"""Generate deployment secrets into a private file without printing them."""
import argparse
import json
import os
from pathlib import Path
import secrets

parser=argparse.ArgumentParser();parser.add_argument('--domain',required=True);parser.add_argument('--executor-url',required=True);parser.add_argument('--model-url',required=True);parser.add_argument('--model-provider',choices=['ollama','gemini','anthropic','chat-completions'],default='gemini');parser.add_argument('--model',default='gemini-3.1-pro-preview');parser.add_argument('--data-root',required=True);parser.add_argument('--workspace-root',required=True);parser.add_argument('--output',type=Path,default=Path('.env.production'));args=parser.parse_args()
if not args.executor_url.startswith('https://'):
    raise SystemExit('Use an HTTPS executor endpoint for separate hosts')
values={'RESCUE_DOMAIN':args.domain,'RESCUE_ALLOWED_HOSTS':args.domain+',127.0.0.1,localhost','RESCUE_EXECUTOR_URL':args.executor_url,'RESCUE_EXECUTOR_TOKEN':secrets.token_urlsafe(32),'RESCUE_AUTH_KEYS':json.dumps([{'id':'operator','roles':['viewer','operator'],'token':secrets.token_urlsafe(32)},{'id':'reviewer','roles':['viewer','reviewer'],'token':secrets.token_urlsafe(32)}]),'RESCUE_DATA_ROOT':str(Path(args.data_root).resolve()),'RESCUE_WORKSPACE_ROOT':str(Path(args.workspace_root).resolve()),'RESCUE_MODEL_PROVIDER':args.model_provider,'RESCUE_MODEL':args.model,'RESCUE_MODEL_URL':args.model_url}
for value in values.values():
    if any(c in value for c in ["'",'\n','\r']):
        raise SystemExit('Unsupported quote/newline in configuration')
fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    f.write('\n'.join(k+"='"+v+"'" for k,v in values.items())+'\n')
print('Private deployment configuration written to '+str(args.output)+'. No existing file overwritten.')
