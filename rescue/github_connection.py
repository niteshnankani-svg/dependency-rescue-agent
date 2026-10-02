"""Server-side GitHub access. Credentials never enter model context or browsers."""
import base64
import json
import os
import re
import subprocess
from urllib.parse import quote
import httpx
from .delivery import installation_token

REPOSITORY=re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def token():
    if os.getenv('RESCUE_GITHUB_APP_ID'):
        return installation_token()
    if os.getenv('RESCUE_GITHUB_READ_TOKEN'):
        return os.environ['RESCUE_GITHUB_READ_TOKEN']
    if os.getenv('RESCUE_ENV')!='production' and os.getenv('RESCUE_GITHUB_LOCAL_CLI')=='1':
        result=subprocess.run(['gh','auth','token','--hostname','github.com'],capture_output=True,text=True,timeout=10)
        if result.returncode==0:return result.stdout.strip()
    return None


class GitHub:
    def __init__(self):
        self.token=token()
        self.client=httpx.Client(base_url='https://api.github.com',timeout=30,trust_env=False,headers={'Accept':'application/vnd.github+json',**({'Authorization':'Bearer '+self.token} if self.token else {})})
    def close(self):self.client.close()
    def get(self,path,**kwargs):
        r=self.client.get(path,**kwargs)
        if r.status_code in (401,403,404):raise ValueError('GitHub access denied, rate limited, or repository/file unavailable. Check the server connection and repository permissions.')
        r.raise_for_status();return r.json()
    def check_repository(self,repo):
        if not REPOSITORY.fullmatch(repo) or any(x in ['.','..'] for x in repo.split('/')):raise ValueError('Use owner/repository, not a URL')
        allowed=set(filter(None,os.getenv('RESCUE_GITHUB_ALLOWED_REPOS','').split(',')))
        if os.getenv('RESCUE_ENV')=='production' and repo not in allowed:raise ValueError('Repository is not enabled by the organization administrator')
        return self.get('/repos/'+repo)
    def repositories(self):
        if not self.token:return []
        if os.getenv('RESCUE_GITHUB_APP_ID'):
            data=self.get('/installation/repositories',params={'per_page':100})['repositories']
        else:data=self.get('/user/repos',params={'per_page':100,'sort':'updated','affiliation':'owner,collaborator,organization_member'})
        allowed=set(filter(None,os.getenv('RESCUE_GITHUB_ALLOWED_REPOS','').split(',')))
        return [{'repository':r['full_name'],'private':r['private']} for r in data if os.getenv('RESCUE_ENV')!='production' or r['full_name'] in allowed]
    def file(self,repo,sha,path):
        response=self.client.get('/repos/'+repo+'/contents/'+quote(path,safe='/'),params={'ref':sha})
        if response.status_code==404:
            raise ValueError(f'Required root file {path} is unavailable at this commit. This importer supports npm projects with root package.json and package-lock.json; Python projects and nested frontend projects need a separate execution profile.')
        if response.status_code in (401,403):raise ValueError('GitHub access denied or rate limited. Check the server connection and repository permissions.')
        response.raise_for_status();data=response.json()
        if not isinstance(data,dict) or data.get('encoding')!='base64' or data.get('size',0)>2_000_000:raise ValueError('Unsupported or oversized repository file')
        return base64.b64decode(data['content'])
    def mcp_manifest(self,repo,sha):
        """One fixed read-only MCP tool; no arbitrary endpoints or model tool dispatch."""
        if not self.token:raise ValueError('GitHub authentication is required for MCP')
        owner,name=repo.split('/')
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/json, text/event-stream','X-MCP-Readonly':'true','X-MCP-Tools':'get_file_contents'}
        with httpx.Client(timeout=30,trust_env=False,headers=headers) as c:
            def rpc(method,params,ident=None):
                body={'jsonrpc':'2.0','method':method,'params':params}
                if ident is not None:body['id']=ident
                r=c.post('https://api.githubcopilot.com/mcp/',json=body)
                if r.status_code>=400:raise ValueError('GitHub MCP connection failed; check token permissions and MCP access')
                if r.headers.get('mcp-session-id'):c.headers['Mcp-Session-Id']=r.headers['mcp-session-id']
                if ident is None:return {}
                if len(r.content)>2_000_000:raise ValueError('MCP response exceeds inspection limit')
                if 'text/event-stream' in r.headers.get('content-type',''):
                    messages=[json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith('data:')]
                    value=next((v for v in messages if v.get('id')==ident),{})
                else:value=r.json()
                if value.get('error') or value.get('result',{}).get('isError'):raise ValueError('GitHub MCP could not read the pinned manifest')
                return value.get('result',{})
            initialized=rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'dependency-rescue','version':'0.3.0'}},1)
            c.headers['MCP-Protocol-Version']=initialized.get('protocolVersion','2025-03-26')
            rpc('notifications/initialized',{})
            result=rpc('tools/call',{'name':'get_file_contents','arguments':{'owner':owner,'repo':name,'path':'package.json','ref':sha}},2)
            if not result.get('content'):raise ValueError('GitHub MCP returned no manifest evidence')
            return {'tool':'get_file_contents','repository':repo,'commit':sha,'verified':True}
