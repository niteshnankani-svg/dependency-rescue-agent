import pytest
from starlette.requests import Request
from fastapi import HTTPException
from rescue import api


def request(origin,forwarded=None):
    headers=[(b'host',b'backend.example.com'),(b'cookie',b'rescue_session=test'),(b'origin',origin.encode())]
    if forwarded:headers.append((b'x-forwarded-host',forwarded.encode()))
    return Request({'type':'http','method':'POST','path':'/api/runs','headers':headers})


def test_configured_public_origin_works_without_trusting_forwarded_headers(monkeypatch):
    monkeypatch.setenv('RESCUE_PUBLIC_URL','https://dependency-rescue-ui.vercel.app')
    monkeypatch.setattr(api,'verify',lambda *a:{'id':'test','roles':['viewer']})
    assert api.authorize(request('https://dependency-rescue-ui.vercel.app'))['id']=='test'
    with pytest.raises(HTTPException) as exc:
        api.authorize(request('https://attacker.example','attacker.example'))
    assert exc.value.status_code==403


def test_unconfigured_frontend_is_not_allowed(monkeypatch):
    monkeypatch.delenv('RESCUE_PUBLIC_URL',raising=False)
    monkeypatch.setattr(api,'verify',lambda *a:{'id':'test'})
    with pytest.raises(HTTPException):api.authorize(request('https://dependency-rescue-ui.vercel.app'))
