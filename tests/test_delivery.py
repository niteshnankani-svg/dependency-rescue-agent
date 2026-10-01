import httpx
import pytest
from rescue.config import get_case
from rescue.delivery import publish


def test_delivery_allowlist_blocks_unapproved_repository(tmp_path,monkeypatch):
    monkeypatch.delenv('RESCUE_GITHUB_ALLOWED_REPOS',raising=False)
    with pytest.raises(ValueError,match='allowlisted'):
        publish(get_case(),{'status':'completed'},tmp_path)


def test_changed_base_cannot_publish(tmp_path,monkeypatch):
    case=get_case().model_copy(update={'test_migration_files':[]});monkeypatch.setenv('RESCUE_GITHUB_ALLOWED_REPOS',case.repository)
    writes=[]
    def handler(request):
        if request.method!='GET':writes.append(request)
        if request.url.path.endswith('/pulls'):return httpx.Response(200,json=[])
        if '/git/ref/' in request.url.path:return httpx.Response(200,json={'object':{'sha':'a'*40}})
        return httpx.Response(200,json={'default_branch':'main'})
    with httpx.Client(base_url='https://api.github.com',transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError,match='Base branch changed'):
            publish(case,{'status':'completed','run_id':'b'*32},tmp_path,client)
    assert not writes


@pytest.mark.parametrize('tampered',[False,True])
def test_delivery_reuses_only_unchanged_approved_pull_request(tmp_path,monkeypatch,tampered):
    import hashlib
    case=get_case().model_copy(update={'test_migration_files':[]});monkeypatch.setenv('RESCUE_GITHUB_ALLOWED_REPOS',case.repository)
    for name in ['package.json','package-lock.json']:(tmp_path/name).write_text('{}')
    data=b'{}';sha=hashlib.sha1(b'blob 2\0'+data).hexdigest()
    def handler(request):
        assert request.method=='GET'
        path=request.url.path
        if path.endswith('/pulls'):return httpx.Response(200,json=[{'number':1,'html_url':'https://github.com/example/repo/pull/1','head':{'sha':'head'}}])
        if '/git/ref/' in path:return httpx.Response(200,json={'object':{'sha':case.base_commit}})
        if path.endswith('/git/commits/'+case.base_commit):return httpx.Response(200,json={'tree':{'sha':'base-tree'}})
        if path.endswith('/git/commits/head'):return httpx.Response(200,json={'tree':{'sha':'head-tree'},'parents':[{'sha':case.base_commit}]})
        if '/git/trees/' in path:
            tree=[{'path':name,'type':'blob','mode':'100644','sha':sha} for name in ['package.json','package-lock.json']]
            if path.endswith('head-tree') and tampered:tree[0]['sha']='tampered'
            return httpx.Response(200,json={'tree':tree,'truncated':False})
        return httpx.Response(200,json={'default_branch':'main'})
    with httpx.Client(base_url='https://api.github.com',transport=httpx.MockTransport(handler)) as client:
        state={'status':'completed','run_id':'b'*32,'sources':{}}
        if tampered:
            with pytest.raises(ValueError,match='differs'):publish(case,state,tmp_path,client)
        else:assert publish(case,state,tmp_path,client)['reused']


def test_delivery_creates_draft_from_verified_base(tmp_path,monkeypatch):
    import json
    case=get_case().model_copy(update={'test_migration_files':[]});monkeypatch.setenv('RESCUE_GITHUB_ALLOWED_REPOS',case.repository)
    case=case.model_copy(update={'test_migration_files':['test/migration.js']})
    (tmp_path/'test').mkdir();(tmp_path/'test/migration.js').write_text('approvedTest();')
    (tmp_path/'src').mkdir();(tmp_path/'src/main.js').write_text('new();')
    (tmp_path/'package.json').write_text('{}');(tmp_path/'package-lock.json').write_text('{}')
    state={'status':'completed','run_id':'b'*32,'sources':{'src/main.js':'old();'},'verification':{'passes':20,'tests':20},'evidence_digest':'e'*64}
    writes=[]
    def handler(request):
        path=request.url.path;body=json.loads(request.content) if request.content else None
        if request.method=='GET':
            if path.endswith('/pulls'):return httpx.Response(200,json=[])
            if path.endswith('/git/ref/heads/main'):return httpx.Response(200,json={'object':{'sha':case.base_commit}})
            if '/git/ref/heads/rescue/' in path:return httpx.Response(404)
            if path.endswith('/git/commits/'+case.base_commit):return httpx.Response(200,json={'tree':{'sha':'base-tree'}})
            return httpx.Response(200,json={'default_branch':'main'})
        writes.append((path,body))
        if path.endswith('/git/blobs'):return httpx.Response(201,json={'sha':'blob-'+str(len(writes))})
        if path.endswith('/git/trees'):return httpx.Response(201,json={'sha':'new-tree'})
        if path.endswith('/git/commits'):return httpx.Response(201,json={'sha':'new-commit'})
        if path.endswith('/git/refs'):return httpx.Response(201,json={})
        if path.endswith('/pulls'):return httpx.Response(201,json={'number':1,'html_url':'https://github.com/example/repo/pull/1'})
        raise AssertionError(path)
    with httpx.Client(base_url='https://api.github.com',transport=httpx.MockTransport(handler)) as client:
        result=publish(case,state,tmp_path,client)
    assert not result['reused']
    commit=next(body for path,body in writes if path.endswith('/git/commits'))
    pr=next(body for path,body in writes if path.endswith('/pulls'))
    assert commit['parents']==[case.base_commit] and pr['draft'] is True
    assert all('/merge' not in path for path,_ in writes)
    tree=next(body for path,body in writes if path.endswith('/git/trees'))
    assert 'test/migration.js' in {entry['path'] for entry in tree['tree']}
