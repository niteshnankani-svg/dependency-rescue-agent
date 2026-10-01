"""Single-organization access control; service keys or a configured OIDC issuer."""
import hmac
import json
import os
from functools import lru_cache
from fastapi import HTTPException


@lru_cache(maxsize=1)
def jwks_client(url):
    from jwt import PyJWKClient
    if not url.startswith('https://'):
        raise RuntimeError('JWKS URL must use HTTPS')
    return PyJWKClient(url,cache_keys=True,timeout=5)


def verify(token,local_token):
    if not token.isascii() or len(token)>8192:
        raise HTTPException(401,'Invalid credentials')
    if os.getenv('RESCUE_ENV','development')!='production' and hmac.compare_digest(token,local_token):
        return {'id':'local-user','roles':['viewer','operator','reviewer']}
    for item in json.loads(os.getenv('RESCUE_AUTH_KEYS','[]')):
        if len(item.get('token',''))>=32 and hmac.compare_digest(token,item['token']):
            return {'id':item['id'],'roles':item['roles']}
    issuer=os.getenv('RESCUE_OIDC_ISSUER')
    if issuer:
        import jwt
        try:
            key=jwks_client(os.environ['RESCUE_OIDC_JWKS_URL']).get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256'],issuer=issuer,audience=os.environ['RESCUE_OIDC_AUDIENCE'],options={'require':['exp','iat','iss','aud','sub']})
            roles=claims.get(os.getenv('RESCUE_OIDC_ROLES_CLAIM','roles'),[])
            if not isinstance(roles,list) or not all(isinstance(r,str) for r in roles):
                raise HTTPException(403,'Invalid organization role claim')
            allowed=[r for r in roles if r in ['viewer','operator','reviewer']]
            if not allowed:
                raise HTTPException(403,'No organization role assigned')
            return {'id':claims['sub'],'roles':allowed}
        except (jwt.PyJWTError,KeyError,ValueError):
            pass
    raise HTTPException(401,'Invalid or expired credentials')


def require(actor,role):
    if role not in actor['roles']:
        raise HTTPException(403,f'{role} role required')


def validate_production():
    if os.getenv('RESCUE_ENV')!='production':
        return
    if os.getenv('RESCUE_RUNNER')!='remote':
        raise RuntimeError('Production API must use a separate remote executor')
    keys=json.loads(os.getenv('RESCUE_AUTH_KEYS','[]'))
    if not keys and not os.getenv('RESCUE_OIDC_ISSUER'):
        raise RuntimeError('Production requires role-scoped keys or OIDC')
    for key in keys:
        if not isinstance(key,dict) or not key.get('id') or len(key.get('token',''))<32 or not key.get('roles') or not set(key['roles'])<=set(['viewer','operator','reviewer']):
            raise RuntimeError('Invalid production service key configuration')
    if os.getenv('RESCUE_OIDC_ISSUER') and (not os.getenv('RESCUE_OIDC_JWKS_URL','').startswith('https://') or not os.getenv('RESCUE_OIDC_AUDIENCE')):
        raise RuntimeError('OIDC requires an HTTPS JWKS URL and explicit audience')
    if len(os.getenv('RESCUE_EXECUTOR_TOKEN',''))<32:
        raise RuntimeError('Executor token must contain at least 32 characters')
    if not os.getenv('RESCUE_ALLOWED_HOSTS'):
        raise RuntimeError('Production requires explicit allowed hosts')
