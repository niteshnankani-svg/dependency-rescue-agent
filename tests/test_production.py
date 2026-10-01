import json
import time
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rescue import auth, api
from rescue.config import Case,get_case
from rescue.execution import parse_result
from rescue.guards import Repair,Edit,apply_repair


@pytest.fixture
def issuer(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setenv('RESCUE_ENV','production');monkeypatch.setenv('RESCUE_OIDC_ISSUER','https://issuer.example')
    monkeypatch.setenv('RESCUE_OIDC_JWKS_URL','https://issuer.example/keys');monkeypatch.setenv('RESCUE_OIDC_AUDIENCE','rescue')
    monkeypatch.setattr(auth,'jwks_client',lambda url:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key())))
    claims={'sub':'reviewer-1','iss':'https://issuer.example','aud':'rescue','iat':int(time.time()),'exp':int(time.time())+300,'roles':['reviewer']}
    return key,claims


def test_oidc_signature_audience_expiry_and_roles(issuer):
    key,claims=issuer
    assert auth.verify(jwt.encode(claims,key,algorithm='RS256'),'local')['roles']==['reviewer']
    for changes in [{'aud':'another-app'},{'iss':'https://attacker.example'},{'exp':0},{'roles':[]}]:
        with pytest.raises(HTTPException):
            auth.verify(jwt.encode({**claims,**changes},key,algorithm='RS256'),'local')
    with pytest.raises(HTTPException):
        auth.verify(jwt.encode(claims,'attacker'*8,algorithm='HS256'),'local')


def test_operator_cannot_approve(monkeypatch,tmp_path):
    monkeypatch.setattr(api,'RUNTIME',tmp_path)
    monkeypatch.setenv('RESCUE_AUTH_KEYS',json.dumps([{'id':'operator','token':'x'*40,'roles':['operator']}]))
    client=TestClient(api.app)
    r=client.post('/api/runs/'+'a'*32+'/decision',headers={'Authorization':'Bearer '+'x'*40},json={'approve':True,'evidence_digest':'b'*64})
    assert r.status_code==403


def test_production_fails_without_isolated_execution(monkeypatch):
    monkeypatch.setenv('RESCUE_ENV','production');monkeypatch.setenv('RESCUE_RUNNER','seatbelt')
    with pytest.raises(RuntimeError,match='separate remote executor'):
        auth.validate_production()


@pytest.mark.parametrize('value',['../outside','/outside'])
def test_case_paths_cannot_escape_data(value):
    config=get_case().model_dump();config['template_dir']=value
    with pytest.raises(ValueError):
        Case.model_validate(config)


def test_empty_or_failed_test_reports_never_pass():
    c=get_case()
    assert not parse_result('{"stats":{"tests":0,"passes":0},"failures":[]}',0,1,c)['ok']
    assert not parse_result('{"stats":{"tests":1,"passes":1},"failures":[]}',1,1,c)['ok']
    assert parse_result('log before\n{"numTotalTests":2,"numPassedTests":2,"testResults":[]}',0,1,c)['ok']
    result=parse_result('Failed to initialize: unable to resolve docker endpoint: context not found',1,1,c)
    assert result['infrastructure_error'] and not result['ok']


def test_model_cannot_add_process_exit(tmp_path):
    (tmp_path/'src').mkdir();(tmp_path/'src/main.js').write_text('old();')
    with pytest.raises(ValueError,match='forbidden'):
        apply_repair(tmp_path,Repair(diagnosis='x',edits=[Edit(path='src/main.js',old='old();',new='process.exit(0);')]))
    assert (tmp_path/'src/main.js').read_text()=='old();'


def test_executor_rejects_missing_auth_before_reading_payload(monkeypatch):
    from rescue.executor_api import app
    monkeypatch.setenv('RESCUE_EXECUTOR_TOKEN','s'*40)
    assert TestClient(app).post('/execute',content='not-json').status_code==401


def test_executor_refuses_test_file_overrides(monkeypatch):
    from rescue.executor_api import app
    monkeypatch.setenv('RESCUE_EXECUTOR_TOKEN','s'*40)
    response=TestClient(app).post('/execute',headers={'Authorization':'Bearer '+'s'*40},json={'case_id':'v8r-js-yaml','phase':'upgraded','files':{'src/cli.spec.js':'skip everything'}})
    assert response.status_code==422


def test_source_credentials_are_blocked_without_echoing_secret(tmp_path):
    from rescue.guards import source_preflight
    (tmp_path/'src').mkdir()
    secret='ghp_'+'a'*30
    (tmp_path/'src/main.js').write_text('const token="'+secret+'";')
    with pytest.raises(ValueError) as error:
        source_preflight(tmp_path)
    assert secret not in str(error.value)


def test_remote_worker_environment_mismatch_fails_closed(monkeypatch,tmp_path):
    import httpx
    from rescue import execution
    monkeypatch.setenv('RESCUE_EXECUTOR_URL','http://worker');monkeypatch.setenv('RESCUE_EXECUTOR_TOKEN','x'*40)
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'ok':True,'snapshot_digest':'wrong','snapshot_unchanged':True})))
    monkeypatch.setattr(execution.httpx,'Client',lambda **kwargs:client)
    with pytest.raises(RuntimeError,match='snapshot differs'):
        execution.remote_execute(tmp_path,get_case(),'baseline')


def test_production_refuses_empty_key_list(monkeypatch):
    monkeypatch.setenv('RESCUE_ENV','production');monkeypatch.setenv('RESCUE_RUNNER','remote')
    monkeypatch.setenv('RESCUE_AUTH_KEYS','[]');monkeypatch.delenv('RESCUE_OIDC_ISSUER',raising=False)
    with pytest.raises(RuntimeError,match='role-scoped'):
        auth.validate_production()


def test_oidc_role_object_cannot_grant_access(issuer):
    key,claims=issuer
    with pytest.raises(HTTPException):
        auth.verify(jwt.encode({**claims,'roles':{'reviewer':False}},key,algorithm='RS256'),'local')


def test_non_ascii_credential_is_rejected_cleanly():
    with pytest.raises(HTTPException) as error:auth.verify('é'*40,'local')
    assert error.value.status_code==401
