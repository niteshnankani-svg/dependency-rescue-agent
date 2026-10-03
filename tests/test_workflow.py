import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
import pytest
from rescue import graph as g


def test_approval_survives_restart_and_binds_digest(tmp_path):
    from langgraph.graph import StateGraph, START, END
    def build(conn):
        workflow=StateGraph(g.State)
        workflow.add_node('approval',g.approval)
        workflow.add_edge(START,'approval')
        workflow.add_edge('approval',END)
        return workflow.compile(checkpointer=SqliteSaver(conn))
    conf={'configurable':{'thread_id':'approval-test'}}
    path=tmp_path/'checkpoints.sqlite'
    with sqlite3.connect(path,check_same_thread=False) as conn:
        graph=build(conn)
        result=graph.invoke({'run_id':'test','evidence_digest':'a'*64,'events':[]},conf)
        assert '__interrupt__' in result
    with sqlite3.connect(path,check_same_thread=False) as conn:
        graph=build(conn)
        result=graph.invoke(Command(resume={'approve':True,'evidence_digest':'b'*64}),conf)
        assert result['approved'] is False
        assert result['status']=='rejected'


@pytest.mark.parametrize('passes,attempts,intact,expected',[(True,1,True,'evidence'),(False,1,True,'diagnose'),(False,3,True,'escalate'),(False,1,False,'escalate')])
def test_failed_verification_never_exports(passes,attempts,intact,expected):
    assert g.route_verification({'verification':{'ok':passes,'integrity_ok':intact},'attempts':attempts})==expected


def test_stale_workspace_cannot_be_exported(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'RUNTIME',tmp_path)
    root=tmp_path/'case/workspace'
    (root/'src').mkdir(parents=True)
    (root/'src/main.js').write_text('tampered();')
    state={'run_id':'case','sources':{'src/main.js':'old();'},'repair':{'diagnosis':'Verified source change','edits':[{'path':'src/main.js','old':'old();','new':'new();'}]},'protected':'irrelevant'}
    result=g.export(state)
    assert result['status']=='blocked'
    assert not (tmp_path/'case/repair.patch').exists()


def test_verified_patch_export_is_readable(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'RUNTIME',tmp_path)
    root=tmp_path/'case/workspace'
    (root/'src').mkdir(parents=True)
    (root/'src/main.js').write_text('new();')
    state={'run_id':'case','sources':{'src/main.js':'old();'},'repair':{'diagnosis':'Verified source change','edits':[{'path':'src/main.js','old':'old();','new':'new();'}]},'protected':g.protected_digest(root),'patch':'reviewed patch'}
    import hashlib
    state.update(environment_digest=g.environment_digest(root),verified_sources=g.digest_files(root,g.source_files(root)),case_digest=hashlib.sha256(g.case(state).model_dump_json().encode()).hexdigest())
    assert g.export(state)['status']=='completed'
    assert (tmp_path/'case/repair.patch').read_text()=='reviewed patch'


def test_added_source_after_review_blocks_export(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'RUNTIME',tmp_path)
    root=tmp_path/'case/workspace';(root/'src').mkdir(parents=True)
    (root/'src/main.js').write_text('new();')
    (root/'src/injected.js').write_text('unexpected();')
    state={'run_id':'case','sources':{'src/main.js':'old();'}}
    assert g.export(state)['status']=='blocked'


def test_case_changes_after_verification_block_export(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'RUNTIME',tmp_path)
    root=tmp_path/'case/workspace';(root/'src').mkdir(parents=True)
    (root/'src/main.js').write_text('new();')
    state={'run_id':'case','sources':{'src/main.js':'old();'},'case_digest':'stale'}
    assert g.export(state)['status']=='blocked'
