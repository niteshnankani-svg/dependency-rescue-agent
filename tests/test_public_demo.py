import json,time
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rescue import api,oauth


def test_demo_signup_opt_in_and_explicit_revocation(monkeypatch):
    monkeypatch.setenv('RESCUE_OAUTH_ROLES','{}')
    monkeypatch.delenv('RESCUE_PUBLIC_GITHUB_DEMO',raising=False)
    with pytest.raises(HTTPException):oauth.roles('github:123')
    monkeypatch.setenv('RESCUE_PUBLIC_GITHUB_DEMO','1')
    assert oauth.roles('github:123')==['viewer','demo']
    with pytest.raises(HTTPException):oauth.roles('google:123')
    monkeypatch.setenv('RESCUE_OAUTH_ROLES',json.dumps({'github:123':[]}))
    with pytest.raises(HTTPException):oauth.roles('github:123')


@pytest.fixture
def demo(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    monkeypatch.setattr(api,'ensure_execution_ready',lambda case:None)
    actor={'id':'github:123','name':'niteshnankani-svg','roles':['viewer','demo'],'provider':'github'}
    api.app.dependency_overrides[api.authorize]=lambda:actor
    yield TestClient(api.app),actor
    api.app.dependency_overrides.clear()


def test_demo_is_owner_scoped_and_cannot_escalate(demo,monkeypatch):
    client,actor=demo
    with api.db() as c:
        c.execute('INSERT INTO jobs(id,key,status,created,actor) VALUES (?,?,?,?,?)',('a'*32,'other','awaiting_approval',time.time(),'github:other'))
    monkeypatch.setattr(api,'state',lambda run:{'status':'awaiting_approval'})
    assert client.get('/api/runs').json()==[]
    for path in ['', '/audit','/patch']:
        assert client.get('/api/runs/'+'a'*32+path).status_code==404
    assert client.post('/api/runs/'+'a'*32+'/cancel',json={}).status_code==404
    assert client.post('/api/runs/'+'a'*32+'/decision',json={'approve':True,'evidence_digest':'a'*64}).status_code==403
    assert client.post('/api/runs/'+'a'*32+'/publish',json={}).status_code==403
    assert [c['id'] for c in client.get('/api/cases').json()]==['hexo-uglify-terser']


def test_demo_repository_list_is_limited_to_authenticated_public_owner(demo,monkeypatch):
    client,actor=demo;seen=[]
    class PublicGitHub:
        def __init__(self,public_owner):seen.append(public_owner);self.public_owner=public_owner;self.token=None
        def repositories(self):return [{'repository':f'{self.public_owner}/public-demo','private':False}]
        def close(self):pass
    monkeypatch.setattr(api,'GitHub',PublicGitHub)
    response=client.get('/api/github/repositories')
    assert response.status_code==200
    assert response.json()=={'connected':True,'public_owner':'niteshnankani-svg','repositories':[{'repository':'niteshnankani-svg/public-demo','private':False}],'limit':100}
    assert seen==['niteshnankani-svg']


def test_demo_has_account_limit_and_idempotency(demo):
    client,actor=demo
    body={'case_id':'hexo-uglify-terser','idempotency_key':'demo-request'}
    first=client.post('/api/runs',json=body);assert first.status_code==202
    assert client.post('/api/runs',json=body).json()==first.json()
    assert client.post('/api/runs',json={**body,'idempotency_key':'second-request'}).status_code==429
    assert client.post('/api/runs',json={**body,'case_id':'v8r-js-yaml'}).status_code==403
    actor['id']='github:456'
    second=client.post('/api/runs',json=body);assert second.status_code==202
    assert second.json()!=first.json()
    assert [r['id'] for r in client.get('/api/runs').json()]==[second.json()['run_id']]


def test_demo_global_budget_checked_before_provider_call(demo,monkeypatch):
    client,_=demo
    monkeypatch.setattr(api,'ensure_execution_ready',lambda case:pytest.fail('Budget must be checked first'))
    with api.db() as c:
        for i in range(8):c.execute('INSERT INTO audit(time,actor,action,run_id,evidence_digest) VALUES (?,?,?,?,?)',(time.time(),str(i),'demo-submit',str(i),''))
    assert client.post('/api/runs',json={'case_id':'hexo-uglify-terser','idempotency_key':'demo-request'}).status_code==429
