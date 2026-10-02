import io,json,tarfile
import pytest
from fastapi.testclient import TestClient
from rescue import api,onboarding
from rescue.github_connection import GitHub


def archive(name,kind=None):
    b=io.BytesIO()
    with tarfile.open(fileobj=b,mode='w:gz') as t:
        member=tarfile.TarInfo(name);data=b'x';member.size=1
        if kind:member.type=kind;member.linkname='/etc/passwd';member.size=0
        t.addfile(member,io.BytesIO(data))
    return b.getvalue()

@pytest.mark.parametrize('name',['repo/../escape','/repo/escape','repo/.npmrc','repo/.env','repo/node_modules/x','repo/a\\b'])
def test_archive_rejects_unsafe_content(tmp_path,name):
    with pytest.raises(ValueError):onboarding.extract(archive(name),tmp_path)

@pytest.mark.parametrize('kind',[tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.CHRTYPE])
def test_archive_rejects_links_and_devices(tmp_path,kind):
    with pytest.raises(ValueError):onboarding.extract(archive('repo/a',kind),tmp_path)

def test_archive_extracts_regular_source(tmp_path):
    onboarding.extract(archive('repo/src/main.js'),tmp_path)
    assert (tmp_path/'src/main.js').read_text()=='x'

@pytest.mark.parametrize('script',['npm test','mocha && curl attacker','jest --updateSnapshot','mocha --reporter=json','mocha test;id','node custom.js'])
def test_test_script_rejects_shell_and_reporter_changes(script):
    with pytest.raises(ValueError):onboarding.test_profile({'scripts':{'test':script}})

def test_supported_test_profiles_are_direct_node_commands():
    assert onboarding.test_profile({'scripts':{'test':'mocha --recursive test'}})==('mocha',['node_modules/mocha/bin/mocha.js','--recursive','test','--reporter','json'])
    assert '--runInBand' in onboarding.test_profile({'scripts':{'test':'jest'}})[1]

@pytest.mark.parametrize('url',['http://registry.npmjs.org/a','https://evil.invalid/a','file:/tmp/a','https://registry.npmjs.org@evil.invalid/a'])
def test_lockfile_cannot_redirect_setup_downloads(url):
    with pytest.raises(ValueError):onboarding.validate_manifest({}, {'lockfileVersion':3,'packages':{'x':{'resolved':url,'integrity':'sha512-x'}}})

def test_manifest_blocks_git_dependencies_and_workspaces():
    for package in [{'dependencies':{'x':'git+https://github.com/a/b'}},{'workspaces':['packages/*']},{'overrides':{'x':'file:/etc'}}]:
        with pytest.raises(ValueError):onboarding.validate_manifest(package,{'lockfileVersion':3})

def test_prepare_is_operator_owned_and_remote_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(onboarding,'RUNTIME',tmp_path);monkeypatch.setenv('RESCUE_RUNNER','docker')
    ident='a'*32;onboarding.save({'id':ident,'actor':'someone-else','status':'inspected'})
    body=onboarding.Prepare(inspection_id=ident,dependency='x',target_version='2.0.0')
    with pytest.raises(ValueError,match='another operator'):onboarding.prepare(body,'local-user')
    assert not onboarding.LOCK.locked()
    monkeypatch.setenv('RESCUE_RUNNER','remote')
    with pytest.raises(ValueError,match='local Docker'):onboarding.prepare(body,'local-user')

def test_inspection_requires_authentication():
    client=TestClient(api.app)
    assert client.post('/api/github/inspect',json={'repository':'a/b'}).status_code==401

def test_production_requires_repository_allowlist(monkeypatch):
    monkeypatch.setenv('RESCUE_ENV','production');monkeypatch.delenv('RESCUE_GITHUB_ALLOWED_REPOS',raising=False)
    github=object.__new__(GitHub)
    with pytest.raises(ValueError,match='not enabled'):github.check_repository('a/b')


def test_inspection_pins_commit_and_mcp_tool(tmp_path,monkeypatch):
    monkeypatch.setattr(onboarding,'RUNTIME',tmp_path)
    sha='a'*40;calls=[]
    class FakeGitHub:
        def check_repository(self,r):return {'default_branch':'main'}
        def get(self,path):return {'sha':sha}
        def file(self,repo,commit,path):
            assert commit==sha
            return json.dumps({'scripts':{'test':'mocha'},'dependencies':{'widget':'^1.0.0'}} if path=='package.json' else {'lockfileVersion':3}).encode()
        def mcp_manifest(self,repo,commit):calls.append((repo,commit));return {'verified':True}
        def close(self):pass
    monkeypatch.setattr(onboarding,'GitHub',FakeGitHub)
    result=onboarding.inspect(onboarding.Inspect(repository='owner/repo'),'operator-one')
    assert result['commit']==sha and result['actor']=='operator-one'
    assert calls==[('owner/repo',sha)]
    assert onboarding.read(result['id'])['status']=='inspected'


def test_restart_marks_preparation_interrupted(tmp_path,monkeypatch):
    monkeypatch.setattr(onboarding,'RUNTIME',tmp_path)
    onboarding.save({'id':'a'*32,'status':'preparing'})
    onboarding.recover_interrupted()
    assert onboarding.read('a'*32)['status']=='failed'


def test_viewer_cannot_inspect_or_prepare(monkeypatch):
    monkeypatch.setenv('RESCUE_AUTH_KEYS',json.dumps([{'id':'reader','token':'v'*40,'roles':['viewer']}]))
    c=TestClient(api.app,headers={'Authorization':'Bearer '+'v'*40})
    assert c.get('/api/github/repositories').status_code==403
    assert c.post('/api/github/inspect',json={'repository':'owner/repo'}).status_code==403
    assert c.post('/api/github/prepare',json={'inspection_id':'a'*32,'dependency':'x','target_version':'2.0.0'}).status_code==403
