"""Loopback-only administrator configuration. Never returns client secrets."""
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlparse
from pydantic import BaseModel,ConfigDict,Field
from fastapi import HTTPException
from .config import ROOT

LOCK=threading.Lock()

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    provider:str=Field(pattern=r'^(github|google)$')
    client_id:str=Field(min_length=3,max_length=300,pattern=r'^[A-Za-z0-9_.-]+$')
    client_secret:str=Field(min_length=8,max_length=500,pattern=r'^[A-Za-z0-9_.-]+$')
    account:str=Field(min_length=1,max_length=254)


def guard(request,actor):
    if os.getenv('RESCUE_ENV')=='production' or not request.client or request.client.host not in ['127.0.0.1','::1','testclient']:
        raise HTTPException(403,'OAuth setup is available only on the local development app')
    if 'reviewer' not in actor['roles']:raise HTTPException(403,'Administrator setup requires reviewer access')


def save(value,origin):
    parsed=urlparse(origin)
    if parsed.hostname not in ['127.0.0.1','localhost'] or parsed.scheme not in ['http','https'] or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:raise ValueError('Use the local application origin')
    account=value.account.strip().lower()
    if value.provider=='github':
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?',account):raise ValueError('Enter your GitHub username, without a URL or @')
        identity='github-login:'+account
    else:
        if not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}',account):raise ValueError('Enter your Google account email address')
        identity='google-email:'+account
    path=ROOT/'.env'
    with LOCK:
        if path.is_symlink():raise ValueError('Local configuration path must not be a symlink')
        lines=path.read_text().splitlines() if path.exists() else []
        existing={}
        for line in lines:
            key,sep,content=line.partition('=')
            if sep and not key.startswith('#'):existing[key]=content.strip().strip('\"\x27')
        mapping=json.loads(existing.get('RESCUE_OAUTH_ROLES','{}'))
        mapping[identity]=['viewer','operator','reviewer']
        updates={'RESCUE_PUBLIC_URL':origin,'RESCUE_'+value.provider.upper()+'_OAUTH_CLIENT_ID':value.client_id,'RESCUE_'+value.provider.upper()+'_OAUTH_CLIENT_SECRET':value.client_secret,'RESCUE_OAUTH_ROLES':json.dumps(mapping)}
        output=[line for line in lines if line.partition('=')[0] not in updates]
        output.extend(key+'='+content for key,content in updates.items())
        fd,name=tempfile.mkstemp(prefix='.env.oauth-',dir=ROOT)
        try:
            with os.fdopen(fd,'w') as f:f.write('\n'.join(output)+'\n');f.flush();os.fsync(f.fileno())
            os.chmod(name,0o600);os.replace(name,path)
        finally:
            if Path(name).exists():Path(name).unlink()
        os.environ.update(updates)
    return {'saved':True,'provider':value.provider,'callback_url':origin+'/auth/'+value.provider+'/callback'}
