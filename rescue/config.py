"""Operator-owned case definitions. API callers cannot supply commands or paths."""
import json
import os
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('RESCUE_DATA_ROOT',str(ROOT/'data/external'))).resolve()
RUNTIME=Path(os.getenv('RESCUE_RUNTIME',str(ROOT/'runtime'))).resolve()


class Case(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{2,70}$')
    repository:str=Field(pattern=r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
    base_commit:str=Field(pattern=r'^[a-f0-9]{40}$')
    dependency:str=Field(pattern=r'^(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+$')
    old_version:str
    target_version:str=Field(pattern=r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$')
    template_dir:str
    source_globs:list[str]=Field(min_length=1,max_length=10)
    test_args:list[str]=Field(min_length=2,max_length=30)
    test_migration_files:list[str]=Field(default_factory=list,max_length=10)
    additional_test_args:list[list[str]]=Field(default_factory=list,max_length=5)
    project_dir:str=''
    python_manifest:str=Field(default='requirements.txt',pattern=r'^(requirements.txt|pyproject.toml)$')
    language:str=Field(default='node',pattern=r'^(node|python)$')
    reporter:str='mocha'
    image:str='node:18-bullseye@sha256:0d9e9a8dcd5a83ea737ed92227a6591a31ad70c8bb722b0c51aff7ae23a88b6a'
    writable_dirs:list[str]=Field(default_factory=list)
    license:str='MIT'
    dataset_task:str=''
    evaluation_role:str='development'
    max_attempts:int=Field(default=3,ge=1,le=5)
    max_edits:int=Field(default=3,ge=1,le=5)
    timeout:int=Field(default=90,ge=5,le=300)

    @field_validator('template_dir','project_dir')
    @classmethod
    def safe_template(cls,v):
        p=PurePosixPath(v)
        if p.is_absolute() or '..' in p.parts or '\\' in v:
            raise ValueError('Template path must be relative')
        return v

    @field_validator('source_globs','writable_dirs','test_migration_files')
    @classmethod
    def safe_paths(cls,values):
        for v in values:
            if PurePosixPath(v).is_absolute() or '..' in PurePosixPath(v).parts or '\\' in v:
                raise ValueError('Paths must stay inside repository')
        return values

    @field_validator('reporter')
    @classmethod
    def reporter_known(cls,v):
        if v not in ['mocha','tap','jest','pytest']:
            raise ValueError('Unsupported reporter')
        return v

    @property
    def templates(self):
        path=(DATA/self.template_dir).resolve()
        if not path.is_relative_to(DATA):
            raise ValueError('Template escapes data root')
        return path

    @property
    def dependency_files(self):
        return [self.python_manifest,'rescue-python.lock.json'] if self.language=='python' else ['package.json','package-lock.json']

    def repository_path(self,name):
        return self.project_dir.rstrip('/')+'/'+name if self.project_dir else name

    def version(self,root):
        if self.language=='python':return json.loads((root/'.rescue-python-versions.json').read_text())[self.dependency]
        return json.loads((root/'node_modules'/self.dependency/'package.json').read_text())['version']

    def public(self):
        return {'id':self.id,'repository':self.repository,'base_commit':self.base_commit,'dependency':self.dependency,'from':self.old_version,'to':self.target_version,'license':self.license,'scope':self.evaluation_role,'ready':all((self.templates/n/('.rescue-python-versions.json' if self.language=='python' else 'node_modules/'+self.dependency+'/package.json')).is_file() for n in ['baseline','upgraded'])}


def cases():
    path=Path(os.getenv('RESCUE_CASES_FILE',str(ROOT/'cases.json')))
    values=[Case.model_validate(c) for c in json.loads(path.read_text())]
    imported=DATA/'imports/registry.json'
    if imported.exists():values += [Case.model_validate(c) for c in json.loads(imported.read_text())]
    if len({c.id for c in values})!=len(values):
        raise ValueError('Duplicate case identifiers')
    return {c.id:c for c in values}


def get_case(case_id='v8r-js-yaml'):
    try:
        return cases()[case_id]
    except KeyError:
        raise ValueError('Unregistered case') from None
