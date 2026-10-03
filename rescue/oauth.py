"""Authorization-code login with browser-bound state, PKCE and opaque sessions."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from urllib.parse import urlencode,urlparse
import httpx
import jwt
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from .config import RUNTIME

PROVIDERS={'github':('https://github.com/login/oauth/authorize','https://github.com/login/oauth/access_token','read:user'),'google':('https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token','openid email profile')}


def db():
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    c=sqlite3.connect(RUNTIME/'oauth.sqlite',timeout=10);c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS flows(state TEXT PRIMARY KEY,provider TEXT,browser TEXT,verifier TEXT,nonce TEXT,expires REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,actor TEXT,expires REAL)')
    c.execute('DELETE FROM flows WHERE expires<?',(time.time(),));c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),));c.commit()
    (RUNTIME/'oauth.sqlite').chmod(0o600)
    return c


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def configured(provider):
    prefix='RESCUE_'+provider.upper()+'_OAUTH_'
    return provider in PROVIDERS and bool(os.getenv(prefix+'CLIENT_ID') and os.getenv(prefix+'CLIENT_SECRET') and os.getenv('RESCUE_PUBLIC_URL'))


def origin():
    value=os.environ['RESCUE_PUBLIC_URL'].rstrip('/');u=urlparse(value)
    if u.username or u.password or u.query or u.fragment or u.path or u.scheme not in ['http','https'] or not u.hostname:raise ValueError('RESCUE_PUBLIC_URL must be an origin without a path')
    if u.scheme!='https' and (os.getenv('RESCUE_ENV')=='production' or u.hostname not in ['localhost','127.0.0.1']):raise ValueError('OAuth requires HTTPS except for local development')
    return value


def secure():return origin().startswith('https://')


def roles(identity,alias=''):
    mapping=json.loads(os.getenv('RESCUE_OAUTH_ROLES','{}'))
    values=mapping.get(identity,mapping.get(alias,[]))
    if not isinstance(values,list) or not values or not set(values)<=set(['viewer','operator','reviewer']):raise HTTPException(403,'Your account is not enabled for this organization. Ask its administrator for access.')
    return values


def start(provider,request):
    if not configured(provider):raise HTTPException(503,'This login provider needs administrator configuration')
    if request.headers.get('sec-fetch-site')=='cross-site':raise HTTPException(403,'Start sign-in from this application')
    state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
    with db() as c:
        if c.execute('SELECT COUNT(*) FROM flows').fetchone()[0]>=1000:raise HTTPException(429,'Too many sign-in attempts. Try again later.')
        c.execute('INSERT INTO flows VALUES (?,?,?,?,?,?)',(digest(state),provider,digest(browser),verifier,nonce,time.time()+600))
    params={'client_id':os.environ['RESCUE_'+provider.upper()+'_OAUTH_CLIENT_ID'],'redirect_uri':origin()+'/auth/'+provider+'/callback','response_type':'code','scope':PROVIDERS[provider][2],'state':state,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256'}
    if provider=='google':params['nonce']=nonce
    response=RedirectResponse(PROVIDERS[provider][0]+'?'+urlencode(params),status_code=303)
    response.set_cookie('rescue_oauth_'+provider,browser,httponly=True,secure=secure(),samesite='lax',max_age=600,path='/auth/'+provider)
    return response


def consume(provider,state,browser):
    if not state or not browser or len(state)>200 or len(browser)>200:raise HTTPException(400,'Missing or invalid sign-in state')
    with db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM flows WHERE state=?',(digest(state),)).fetchone()
        if not row or row['provider']!=provider or not hmac.compare_digest(row['browser'],digest(browser)) or row['expires']<time.time():raise HTTPException(400,'Sign-in expired or belongs to another browser. Start again.')
        c.execute('DELETE FROM flows WHERE state=?',(digest(state),))
        return dict(row)


def google_claims(id_token,nonce):
    from .auth import jwks_client
    key=jwks_client('https://www.googleapis.com/oauth2/v3/certs').get_signing_key_from_jwt(id_token).key
    claims=jwt.decode(id_token,key,algorithms=['RS256'],audience=os.environ['RESCUE_GOOGLE_OAUTH_CLIENT_ID'],issuer=['https://accounts.google.com','accounts.google.com'],options={'require':['exp','iat','iss','aud','sub','nonce']})
    if not hmac.compare_digest(claims['nonce'],nonce) or claims.get('email_verified') is not True or claims.get('azp',os.environ['RESCUE_GOOGLE_OAUTH_CLIENT_ID'])!=os.environ['RESCUE_GOOGLE_OAUTH_CLIENT_ID']:raise ValueError('Invalid Google identity')
    return claims


def exchange(provider,code,flow):
    prefix='RESCUE_'+provider.upper()+'_OAUTH_'
    with httpx.Client(timeout=20,trust_env=False) as c:
        response=c.post(PROVIDERS[provider][1],data={'client_id':os.environ[prefix+'CLIENT_ID'],'client_secret':os.environ[prefix+'CLIENT_SECRET'],'code':code,'code_verifier':flow['verifier'],'grant_type':'authorization_code','redirect_uri':origin()+'/auth/'+provider+'/callback'},headers={'Accept':'application/json'})
        response.raise_for_status();tokens=response.json()
        if provider=='github':
            if not tokens.get('access_token') or tokens.get('token_type','').lower()!='bearer':raise ValueError('GitHub token exchange failed')
            response=c.get('https://api.github.com/user',headers={'Authorization':'Bearer '+tokens['access_token'],'Accept':'application/vnd.github+json'});response.raise_for_status();user=response.json()
            ident='github:'+str(user['id']);alias='github-login:'+user['login'].lower();name=user['login']
        else:
            user=google_claims(tokens['id_token'],flow['nonce']);ident='google:'+user['sub'];alias='google-email:'+user['email'].lower();name=user.get('name',user['email'])
        # Provider tokens are deliberately not retained or reused for repository access.
        return {'id':ident,'roles':roles(ident,alias),'name':name,'provider':provider,'alias':alias}


def issue(actor):
    value='rs_'+secrets.token_urlsafe(32)
    with db() as c:c.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(value),json.dumps(actor),time.time()+3600))
    return value


def verify_session(value):
    with db() as c:row=c.execute('SELECT actor FROM sessions WHERE token=? AND expires>?',(digest(value),time.time())).fetchone()
    if not row:raise HTTPException(401,'Session expired. Sign in again.')
    actor=json.loads(row['actor'])
    # Role removals take effect immediately, even during an existing session.
    actor['roles']=roles(actor['id'],actor.get('alias',''))
    return actor


def callback(provider,request):
    if not configured(provider):raise HTTPException(503,'Login provider unavailable')
    try:
        flow=consume(provider,request.query_params.get('state',''),request.cookies.get('rescue_oauth_'+provider,''))
        if request.query_params.get('error'):raise HTTPException(400,'Sign-in was cancelled. Start again when ready.')
        code=request.query_params.get('code','')
        if not code or len(code)>2048:raise HTTPException(400,'Missing or invalid authorization code')
        actor=exchange(provider,code,flow)
        session=issue(actor)
    except HTTPException:raise
    except Exception:raise HTTPException(502,'Sign-in could not be completed. Check provider configuration and try again.') from None
    destination='/workspace' if os.getenv('RESCUE_VERCEL_WORKSPACE')=='1' else '/'
    response=RedirectResponse(destination,status_code=303);response.set_cookie('rescue_session',session,httponly=True,secure=secure(),samesite='strict',max_age=3600)
    response.delete_cookie('rescue_oauth_'+provider,path='/auth/'+provider,secure=secure(),httponly=True,samesite='lax')
    return response


def revoke(value):
    with db() as c:c.execute('DELETE FROM sessions WHERE token=?',(digest(value),))
