import json
from types import SimpleNamespace
import pytest
from rescue import python_profile as profile,onboarding
from rescue.github_connection import MissingFile
from rescue.guards import source_files,protected_digest
from rescue.security import check_new_capabilities
from rescue.execution import parse_result

@pytest.mark.parametrize('text',['-r hidden.txt','--index-url https://evil.invalid','widget @ https://evil.invalid/x.whl','-e .','widget\nWidget==2.0'])
def test_requirements_refuse_external_install_instructions(text):
    with pytest.raises(ValueError):profile.requirements(text)

def test_requirements_and_pin_preserve_extras_and_markers():
    deps,lines=profile.requirements('httpx[http2]>=0.20\nwidget<2; python_version < "3.12"')
    assert deps['httpx']=='>=0.20'
    pinned=profile.pin(lines,{'httpx':'0.28.1','widget':'1.0'},'widget','2.0.0')
    assert pinned[0]=='httpx[http2]==0.28.1'
    assert pinned[1].startswith('widget==2.0.0;')

def test_pyproject_static_dependencies():
    assert profile.manifest('[project]\ndependencies=["httpx==0.28.1"]','pyproject.toml')[0]=={'httpx':'==0.28.1'}
    with pytest.raises(ValueError):profile.manifest('[project]\ndynamic=["dependencies"]','pyproject.toml')

def test_python_tests_and_installed_packages_are_not_editable(tmp_path):
    (tmp_path/'app.py').write_text('x=1');(tmp_path/'test_app.py').write_text('assert True')
    (tmp_path/profile.PACKAGES).mkdir();(tmp_path/profile.PACKAGES/'dependency.py').write_text('x=2')
    assert [p.name for p in source_files(tmp_path,['**/*.py'])]==['app.py']
    before=protected_digest(tmp_path,['**/*.py']);(tmp_path/'test_app.py').write_text('assert False')
    assert protected_digest(tmp_path,['**/*.py'])!=before

@pytest.mark.parametrize('code',['import subprocess\nsubprocess.run(["id"])','os.environ["KEY"]','exec("x")','socket.connect(("evil",80))'])
def test_python_repairs_cannot_introduce_sensitive_capabilities(code):
    with pytest.raises(ValueError):check_new_capabilities('x=1',code)

def test_empty_and_skipped_reports_cannot_pass():
    case=SimpleNamespace(image=profile.IMAGE)
    assert not parse_result('{"stats":{"tests":0,"passes":0}}',0,1,case)['ok']
    assert not parse_result('{"stats":{"tests":1,"passes":0},"failures":[{"err":{"message":"Skipped"}}]}',0,1,case)['ok']

def test_python_inspection_pins_manifest_through_mcp(tmp_path,monkeypatch):
    monkeypatch.setattr(onboarding,'RUNTIME',tmp_path);calls=[]
    class GitHub:
        def check_repository(self,r):return {'default_branch':'main'}
        def get(self,path):return {'sha':'a'*40}
        def file(self,r,c,path):
            if path.endswith('package.json'):raise MissingFile('missing')
            return b'httpx==0.28.1'
        def mcp_manifest(self,r,c,path):calls.append(path);return {'verified':True}
        def close(self):pass
    monkeypatch.setattr(onboarding,'GitHub',GitHub)
    result=onboarding.inspect(onboarding.Inspect(repository='owner/repo',project_dir='backend'),'actor')
    assert result['language']=='python' and result['dependencies']=={'httpx':'==0.28.1'}
    assert calls==['backend/requirements.txt']
    with pytest.raises(ValueError):onboarding.inspect(onboarding.Inspect(repository='owner/repo',project_dir='../other'),'actor')

def test_nested_python_case_preserves_patch_paths():
    from rescue.config import Case
    case=Case(id='python-nested',repository='owner/repo',base_commit='a'*40,dependency='httpx',old_version='0.27.2',target_version='0.28.1',template_dir='fixture',source_globs=['**/*.py'],test_args=['-c','pass'],language='python',reporter='pytest',project_dir='backend')
    assert case.repository_path('app.py')=='backend/app.py'
    assert case.dependency_files==['requirements.txt','rescue-python.lock.json']

def test_python_package_integrity_is_bound(tmp_path):
    from rescue.graph import environment_digest
    (tmp_path/profile.PACKAGES).mkdir();p=tmp_path/profile.PACKAGES/'dep.py';p.write_text('x=1')
    before=environment_digest(tmp_path);p.write_text('x=2')
    assert environment_digest(tmp_path)!=before

def test_conftest_setup_and_suffix_tests_are_protected(tmp_path):
    for name in ['conftest.py','setup.py','app_test.py','app.py']:(tmp_path/name).write_text('x=1')
    assert [p.name for p in source_files(tmp_path,['**/*.py'])]==['app.py']

def test_python_semicolon_import_and_bad_syntax_are_rejected(tmp_path):
    from rescue.guards import Repair,apply_repair
    p=tmp_path/'app.py';p.write_text('x=1\n')
    for new in ['x=1; import os\n','if broken syntax\n']:
        repair=Repair(diagnosis='Invalid candidate',edits=[{'path':'app.py','old':'x=1\n','new':new}])
        with pytest.raises(ValueError):apply_repair(tmp_path,repair,['*.py'])
        assert p.read_text()=='x=1\n'

def test_example_environment_files_are_allowed_but_credentials_are_not(tmp_path):
    import io,tarfile
    def archive(content):
        b=io.BytesIO()
        with tarfile.open(fileobj=b,mode='w:gz') as t:
            m=tarfile.TarInfo('repo/frontend/.env.local.example');data=content.encode();m.size=len(data);t.addfile(m,io.BytesIO(data))
        return b.getvalue()
    onboarding.extract(archive('API_URL=http://localhost:8000'),tmp_path)
    assert (tmp_path/'frontend/.env.local.example').exists()
    other=tmp_path/'other';other.mkdir()
    with pytest.raises(ValueError):onboarding.extract(archive('GITHUB_TOKEN=ghp_'+'a'*36),other)

def test_python_imported_api_symbol_migration_is_allowed(tmp_path):
    from rescue.guards import Repair,apply_repair
    p=tmp_path/'app.py';p.write_text('from pydantic import BaseModel\n')
    repair=Repair(diagnosis='Use existing package API',edits=[{'path':'app.py','old':p.read_text(),'new':'from pydantic import BaseModel, ConfigDict\n'}])
    apply_repair(tmp_path,repair,['*.py'])
    assert 'ConfigDict' in p.read_text()

def test_incompatible_python_version_is_reported_before_execution():
    with pytest.raises(ValueError,match='different Python version'):
        profile.manifest('[project]\nrequires-python=">=3.12"\ndependencies=["httpx"]','pyproject.toml')

def test_existing_node_case_review_digest_remains_compatible():
    import hashlib
    from rescue.config import get_case
    from rescue.graph import case_digest
    case=get_case('v8r-js-yaml')
    legacy=case.model_dump_json(exclude={'language','python_manifest','project_dir'})
    assert case_digest(case)==hashlib.sha256(legacy.encode()).hexdigest()
