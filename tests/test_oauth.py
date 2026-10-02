import hashlib,json,time
from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from rescue import oauth,api,auth

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(oauth,'RUNTIME',tmp_path)
    monkeypatch.setenv('RESCUE_PUBLIC_URL','http://testserver')
    # Local HTTP requires a loopback origin; use it for the provider URI.
    monkeypatch.setenv('RESCUE_PUBLIC_URL','http://127.0.0.1:8093')
    monkeypatch.setenv('RESCUE_GITHUB_OAUTH_CLIENT_ID','client-id')
    monkeypatch.setenv('RESCUE_GITHUB_OAUTH_CLIENT_SECRET','private-client-secret')
    monkeypatch.setenv('RESCUE_OAUTH_ROLES',json.dumps({'github:42':['viewer','operator']}))
    monkeypatch.setattr(api,'LOCAL',False)
    return TestClient(api.app)


def begin(client):
    response=client.get('/auth/github/start',follow_redirects=False)
    assert response.status_code==303
    params=parse_qs(urlparse(response.headers['location']).query)
    assert params['code_challenge_method']==['S256'] and 'client_secret' not in params
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    return params['state'][0]


def test_successful_callback_uses_opaque_revocable_session(client,monkeypatch):
    state=begin(client)
    monkeypatch.setattr(oauth,'exchange',lambda *a:{'id':'github:42','name':'tester','provider':'github','roles':['viewer','operator']})
    response=client.get('/auth/github/callback',params={'state':state,'code':'test-code'},follow_redirects=False)
    assert response.status_code==303
    assert 'SameSite=strict' in response.headers['set-cookie']
    value=client.cookies.get('rescue_session');assert value.startswith('rs_')
    assert client.get('/api/me').json()['id']=='github:42'
    with oauth.db() as c:assert c.execute('SELECT token FROM sessions').fetchone()[0]==hashlib.sha256(value.encode()).hexdigest()
    assert client.post('/api/logout',headers={'Origin':'http://testserver'}).status_code==200
    client.cookies.set('rescue_session',value)
    assert client.get('/api/me').status_code==401


def test_state_is_browser_bound_single_use_and_provider_bound(client):
    state=begin(client)
    with pytest.raises(HTTPException):oauth.consume('github',state,'wrong-browser')
    browser=client.cookies.get('rescue_oauth_github')
    with pytest.raises(HTTPException):oauth.consume('google',state,browser)
    oauth.consume('github',state,browser)
    with pytest.raises(HTTPException):oauth.consume('github',state,browser)


def test_expired_state_and_denied_account_cannot_create_session(client,monkeypatch):
    state=begin(client)
    with oauth.db() as c:c.execute('UPDATE flows SET expires=0')
    assert client.get('/auth/github/callback',params={'state':state,'code':'test'}).status_code==400
    with pytest.raises(HTTPException):oauth.roles('github:unapproved')
    assert 'rescue_session' not in client.cookies


def test_callback_failure_never_exposes_provider_secret_or_code(client,monkeypatch):
    state=begin(client)
    def fail(*a):raise RuntimeError('private-client-secret test-code')
    monkeypatch.setattr(oauth,'exchange',fail)
    r=client.get('/auth/github/callback',params={'state':state,'code':'test-code'})
    assert r.status_code==502 and 'private-client-secret' not in r.text and 'test-code' not in r.text


def test_role_removal_applies_to_existing_sessions(client,monkeypatch):
    value=oauth.issue({'id':'github:42','roles':['viewer','operator']})
    monkeypatch.setenv('RESCUE_OAUTH_ROLES','{}')
    with pytest.raises(HTTPException):auth.verify(value,'unrelated-local-token')


def test_no_external_plain_http_origin_or_redirect_path(client,monkeypatch):
    for origin in ['http://evil.invalid','https://app.invalid/path','https://user:secret@app.invalid','https://app.invalid?redirect=x']:
        monkeypatch.setenv('RESCUE_PUBLIC_URL',origin)
        with pytest.raises(ValueError):oauth.origin()
    monkeypatch.setenv('RESCUE_ENV','production');monkeypatch.setenv('RESCUE_PUBLIC_URL','http://127.0.0.1:8093')
    with pytest.raises(ValueError):oauth.origin()


def test_google_signed_identity_validates_audience_nonce_expiry_and_signature(client,monkeypatch):
    monkeypatch.setenv('RESCUE_GOOGLE_OAUTH_CLIENT_ID','google-client')
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setattr(auth,'jwks_client',lambda url:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key())))
    claims={'iss':'https://accounts.google.com','sub':'123','aud':'google-client','iat':int(time.time()),'exp':int(time.time())+60,'nonce':'nonce','email':'user@example.com','email_verified':True}
    encoded=lambda c:jwt.encode(c,key,algorithm='RS256')
    assert oauth.google_claims(encoded(claims),'nonce')['sub']=='123'
    for changed in [{'aud':'other-app'},{'nonce':'other'},{'exp':0},{'email_verified':False},{'iss':'https://evil.invalid'},{'azp':'other-client'}]:
        with pytest.raises((ValueError,jwt.PyJWTError)):oauth.google_claims(encoded({**claims,**changed}),'nonce')


def test_unknown_provider_and_unconfigured_provider_are_unavailable(client,monkeypatch):
    assert client.get('/auth/unknown/start').status_code==503
    monkeypatch.delenv('RESCUE_GITHUB_OAUTH_CLIENT_SECRET')
    assert client.get('/auth/providers').json()['github']['enabled'] is False
    assert client.get('/auth/github/start').status_code==503


def test_expired_session_and_forged_google_signature_rejected(client,monkeypatch):
    value=oauth.issue({'id':'github:42','roles':['viewer']})
    with oauth.db() as c:c.execute('UPDATE sessions SET expires=0')
    with pytest.raises(HTTPException):oauth.verify_session(value)
    monkeypatch.setenv('RESCUE_GOOGLE_OAUTH_CLIENT_ID','google-client')
    trusted=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    attacker=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setattr(auth,'jwks_client',lambda url:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=trusted.public_key())))
    claims={'iss':'https://accounts.google.com','sub':'123','aud':'google-client','iat':int(time.time()),'exp':int(time.time())+60,'nonce':'nonce','email':'user@example.com','email_verified':True}
    with pytest.raises(jwt.InvalidSignatureError):oauth.google_claims(jwt.encode(claims,attacker,algorithm='RS256'),'nonce')
