import json,os
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rescue import api,oauth_setup


def test_secret_saved_privately_without_changing_other_configuration(tmp_path,monkeypatch):
    monkeypatch.setattr(oauth_setup,'ROOT',tmp_path)
    monkeypatch.setattr(oauth_setup.os,'environ',os.environ.copy())
    (tmp_path/'.env').write_text('GEMINI_API_KEY=preserve-me\n# comment\n')
    value=oauth_setup.Settings(provider='github',client_id='client-id',client_secret='private-secret',account='my-account')
    result=oauth_setup.save(value,'http://127.0.0.1:8093')
    assert 'private-secret' not in json.dumps(result)
    assert (tmp_path/'.env').stat().st_mode&0o777==0o600
    assert 'GEMINI_API_KEY=preserve-me' in (tmp_path/'.env').read_text()
    assert os.environ['RESCUE_GITHUB_OAUTH_CLIENT_SECRET']=='private-secret'


def test_setup_rejects_remote_production_and_non_admin(monkeypatch):
    local=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))
    remote=SimpleNamespace(client=SimpleNamespace(host='198.51.100.1'))
    actor={'roles':['reviewer']}
    with pytest.raises(HTTPException):oauth_setup.guard(remote,actor)
    with pytest.raises(HTTPException):oauth_setup.guard(local,{'roles':['viewer']})
    monkeypatch.setenv('RESCUE_ENV','production')
    with pytest.raises(HTTPException):oauth_setup.guard(local,actor)


def test_setup_validation_never_echoes_secrets(tmp_path,monkeypatch):
    monkeypatch.setattr(oauth_setup,'ROOT',tmp_path)
    monkeypatch.setattr(api,'LOCAL',True)
    client=TestClient(api.app);client.get('/')
    secret='secret-with\ninjected-line'
    response=client.post('/api/oauth/setup',headers={'Origin':'http://testserver'},json={'provider':'github','client_id':'x','client_secret':secret,'account':'my-account'})
    assert response.status_code==422 and 'secret-with' not in response.text and not (tmp_path/'.env').exists()
    assert client.post('/api/oauth/setup',headers={'Origin':'https://evil.invalid'},json={}).status_code==403


def test_api_saves_and_status_never_returns_secret(tmp_path,monkeypatch):
    monkeypatch.setattr(oauth_setup,'ROOT',tmp_path)
    monkeypatch.setattr(oauth_setup.os,'environ',os.environ.copy())
    monkeypatch.setattr(api,'LOCAL',True)
    c=TestClient(api.app,base_url='http://127.0.0.1:8093');c.get('/')
    body={'provider':'github','client_id':'client-id','client_secret':'private-secret','account':'my-account'}
    r=c.post('/api/oauth/setup',headers={'Origin':'http://127.0.0.1:8093'},json=body)
    assert r.status_code==200 and 'private-secret' not in r.text
    r=c.get('/api/oauth/setup')
    assert r.status_code==200 and r.json()['github'] is True and 'private-secret' not in r.text
