"""Configure OAuth privately; never print secrets or commit them."""
import getpass,json
from pathlib import Path
import os
provider=input('Provider (github/google): ').strip().lower()
if provider not in ['github','google']:raise SystemExit('Choose github or google')
origin=input('Application origin [http://127.0.0.1:8093]: ').strip() or 'http://127.0.0.1:8093'
client=input('OAuth client ID: ').strip()
secret=getpass.getpass('OAuth client secret (hidden): ').strip()
identity=input('Approved identity (github-login:username or google-email:address): ').strip()
if not client or not secret or not identity:raise SystemExit('All values are required')
path=Path(__file__).resolve().parents[1]/'.env'
values={}
if path.exists():
 for line in path.read_text().splitlines():
  if '=' in line and not line.startswith('#'):
   key,value=line.split('=',1);values[key]=value
roles=json.loads(values.get('RESCUE_OAUTH_ROLES','{}'));roles[identity]=['viewer','operator','reviewer']
values.update({'RESCUE_PUBLIC_URL':origin,'RESCUE_'+provider.upper()+'_OAUTH_CLIENT_ID':client,'RESCUE_'+provider.upper()+'_OAUTH_CLIENT_SECRET':secret,'RESCUE_OAUTH_ROLES':json.dumps(roles)})
# This private local setup helper grants the explicitly nominated administrator.
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:f.write('\n'.join(k+'='+v for k,v in values.items())+'\n')
path.chmod(0o600)
print('Saved private configuration. Restart the backend; open the configured origin and sign in.')
