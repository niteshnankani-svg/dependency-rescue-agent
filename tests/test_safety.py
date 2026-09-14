from pathlib import Path
import pytest
from rescue.guards import Edit, Repair, apply_repair, protected_digest


@pytest.fixture
def repo(tmp_path):
    (tmp_path/'src').mkdir()
    (tmp_path/'src/main.js').write_text('call(old);\n')
    (tmp_path/'src/main.spec.js').write_text('assert(true);\n')
    (tmp_path/'package.json').write_text('{}')
    return tmp_path


@pytest.mark.parametrize('path',['../outside.js','/tmp/outside.js','package.json','src/main.spec.js'])
def test_untrusted_edit_cannot_escape_source_policy(repo,path):
    repair=Repair(diagnosis='test',edits=[Edit(path=path,old='call(old);',new='call(new);')])
    with pytest.raises(ValueError):
        apply_repair(repo,repair)
    assert (repo/'src/main.js').read_text()=='call(old);\n'


def test_missing_anchor_does_not_mutate(repo):
    with pytest.raises(ValueError):
        apply_repair(repo,Repair(diagnosis='x',edits=[Edit(path='src/main.js',old='invented();',new='changed();')]))
    assert (repo/'src/main.js').read_text()=='call(old);\n'


def test_symlink_cannot_escape(repo,tmp_path):
    outside=tmp_path/'outside.js'
    outside.write_text('private')
    (repo/'src/link.js').symlink_to(outside)
    with pytest.raises(ValueError):
        apply_repair(repo,Repair(diagnosis='x',edits=[Edit(path='src/link.js',old='private',new='overwritten')]))
    assert outside.read_text()=='private'


def test_test_tampering_changes_integrity(repo):
    before=protected_digest(repo)
    (repo/'src/main.spec.js').write_text('skip();')
    assert protected_digest(repo)!=before


def test_source_edit_preserves_protected_files(repo):
    before=protected_digest(repo)
    apply_repair(repo,Repair(diagnosis='x',edits=[Edit(path='src/main.js',old='call(old);',new='call(new);')]))
    assert protected_digest(repo)==before
