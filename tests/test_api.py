from fastapi.testclient import TestClient
from rescue import api


def test_requests_require_authentication_and_reject_cross_origin(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    client=TestClient(api.app)
    assert client.get('/api/runs').status_code==401
    headers={'Authorization':'Bearer '+api.TOKEN}
    assert client.get('/api/runs',headers=headers).status_code==200
    assert client.post('/api/runs',headers={**headers,'Origin':'https://attacker.example'},json={'idempotency_key':'12345678'}).status_code==403


def test_submission_is_idempotent_and_unknown_cases_are_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    monkeypatch.setattr(api,'ensure_execution_ready',lambda selected:None)
    client=TestClient(api.app)
    headers={'Authorization':'Bearer '+api.TOKEN}
    a=client.post('/api/runs',headers=headers,json={'idempotency_key':'same-request'})
    b=client.post('/api/runs',headers=headers,json={'idempotency_key':'same-request'})
    assert a.status_code==202 and a.json()==b.json()
    assert client.post('/api/runs',headers=headers,json={'case_id':'get-jwks-lru','idempotency_key':'same-request'}).status_code==409
    assert client.post('/api/runs',headers=headers,json={'case_id':'arbitrary-repo','idempotency_key':'other-request'}).status_code==422


def test_unavailable_execution_cannot_enqueue(tmp_path,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    def unavailable(selected):raise HTTPException(503,'Worker unavailable')
    monkeypatch.setattr(api,'ensure_execution_ready',unavailable)
    client=TestClient(api.app);headers={'Authorization':'Bearer '+api.TOKEN}
    assert client.post('/api/runs',headers=headers,json={'idempotency_key':'unavailable-request'}).status_code==503
    assert client.get('/api/runs',headers=headers).json()==[]


def test_cross_host_requests_are_rejected():
    client=TestClient(api.app)
    assert client.get('/',headers={'Host':'attacker.example'}).status_code==400


def test_tampered_export_cannot_be_downloaded(tmp_path,monkeypatch):
    run_id='a'*32
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    monkeypatch.setattr(api,'state',lambda run:{'status':'completed','patch':'approved content'})
    (tmp_path/run_id).mkdir();(tmp_path/run_id/'repair.patch').write_text('tampered content')
    client=TestClient(api.app);headers={'Authorization':'Bearer '+api.TOKEN}
    assert client.get('/api/runs/'+run_id+'/patch',headers=headers).status_code==409
    (tmp_path/run_id/'repair.patch').write_text('approved content')
    response=client.get('/api/runs/'+run_id+'/patch',headers=headers)
    assert response.status_code==200 and response.text=='approved content'
