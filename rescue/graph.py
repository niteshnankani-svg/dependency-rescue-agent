"""Durable repair loop with reproducibility, independent checks, and approval."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Annotated, TypedDict
import operator
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from .guards import Repair, apply_repair, digest_files, protected_digest, source_files
from .model import propose
from .runner import run_tests

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'runtime'
TEMPLATES=ROOT/'data/external/templates'


class State(TypedDict, total=False):
    run_id: str
    status: str
    events: Annotated[list[dict],operator.add]
    baseline: dict
    broken: dict
    verification: dict
    repair: dict
    model_usage: dict
    attempts: int
    protected: str
    sources: dict
    patch: str
    evidence_digest: str
    approved: bool
    error: str


def workspace(s):
    return RUNTIME/s['run_id']/'workspace'


def event(node, detail):
    return {'events':[{'node':node,'detail':detail}]}


def intake(s):
    if not all((TEMPLATES/n/'node_modules/js-yaml/package.json').exists() for n in ['baseline','upgraded']):
        return {'status':'blocked','error':'Run case setup first',**event('intake','Prepared case missing')}
    folder=workspace(s)
    if not folder.exists():
        shutil.copytree(TEMPLATES/'baseline',folder)
    return {'status':'running','attempts':0,**event('intake','Pinned MIT-licensed development case; isolated workspace created')}


def baseline(s):
    result=run_tests(workspace(s))
    return {'baseline':result,'status':'running' if result['ok'] else 'blocked',**event('baseline',f"{result['passes']}/{result['tests']} baseline tests passed")}


def upgrade(s):
    dest=workspace(s)
    # Idempotent replacement of prepared dependency environment, never arbitrary shell.
    shutil.copytree(TEMPLATES/'upgraded',dest,dirs_exist_ok=True)
    version=json.loads((dest/'node_modules/js-yaml/package.json').read_text())['version']
    if version!='4.0.0':
        raise ValueError('Installed dependency must exactly match approved target 4.0.0')
    return {'protected':protected_digest(dest),'sources':{str(p.relative_to(dest)):p.read_text() for p in source_files(dest)},**event('upgrade','Applied pinned manifest and installed js-yaml 4.0.0')}


def reproduce(s):
    result=run_tests(workspace(s))
    reproduced=not result['ok'] and result['tests']==s['baseline']['tests'] and result['passes']>0 and not result['timed_out']
    return {'broken':result,'status':'running' if reproduced else 'blocked',**event('reproduce',f"{len(result['failures'])} failures; regression reproduced={reproduced}")}


def diagnose(s):
    # Each attempt starts from original upgraded source, avoiding cumulative patch drift.
    for name,content in s['sources'].items():
        (workspace(s)/name).write_text(content)
    try:
        failure={'tests':s.get('verification',s['broken']),'previous_patch_rejection':s.get('error')}
        repair,usage=propose(workspace(s),failure,s['attempts']+1)
        return {'repair':repair,'model_usage':usage,'attempts':s['attempts']+1,'status':'running','error':'',**event('diagnose','Model proposed a structured source repair')}
    except Exception as exc:
        return {'status':'blocked','error':f'Model failed: {type(exc).__name__}',**event('diagnose','Model request failed; no fallback patch fabricated')}


def apply(s):
    try:
        changed=apply_repair(workspace(s),Repair.model_validate(s['repair']))
        return event('apply','Validated exact-match source edits: '+', '.join(changed))
    except ValueError as exc:
        return {'status':'blocked','error':str(exc),**event('apply','Patch rejected by source-edit policy')}


def verify(s):
    root=workspace(s)
    before=digest_files(root,source_files(root))
    result=run_tests(root)
    intact=protected_digest(root)==s['protected'] and digest_files(root,source_files(root))==before
    installed=json.loads((root/'node_modules/js-yaml/package.json').read_text())['version']
    result['integrity_ok']=intact
    result['dependency_version']=installed
    result['ok']=result['ok'] and intact and installed=='4.0.0' and result['tests']==s['baseline']['tests']
    return {'verification':result,**event('verify',f"{result['passes']}/{result['tests']} tests passed; integrity={intact}")}


def route_verification(s):
    if s['verification']['ok']:
        return 'evidence'
    return 'diagnose' if s['attempts']<2 and s['verification']['integrity_ok'] else 'escalate'


def evidence(s):
    root=workspace(s)
    patch=''
    for name in ['package.json','package-lock.json',*s['sources']]:
        old=(TEMPLATES/'baseline'/name).read_text().splitlines(keepends=True)
        new=(root/name).read_text().splitlines(keepends=True)
        patch+=''.join(difflib.unified_diff(old,new,fromfile='a/'+name,tofile='b/'+name))
    digest=hashlib.sha256((patch+json.dumps(s['verification'],sort_keys=True)).encode()).hexdigest()
    return {'patch':patch,'evidence_digest':digest,'status':'awaiting_approval',**event('evidence','Diff, target version, test counts and integrity bound to an approval digest')}


def approval(s):
    decision=interrupt({'run_id':s['run_id'],'evidence_digest':s['evidence_digest'],'action':'Export verified patch bundle; does not merge or deploy'})
    approved=decision.get('approve') is True and decision.get('evidence_digest')==s['evidence_digest']
    return {'approved':approved,'status':'approved' if approved else 'rejected',**event('approval','Reviewer approved evidence' if approved else 'Approval declined or stale digest')}


def export(s):
    root=workspace(s)
    # Approval cannot bless a workspace changed after tests.
    expected={name:content for name,content in s['sources'].items()}
    for edit in s['repair']['edits']:
        expected[edit['path']]=expected[edit['path']].replace(edit['old'],edit['new'],1)
    if any((root/name).read_text()!=content for name,content in expected.items()) or protected_digest(root)!=s['protected']:
        return {'status':'blocked','error':'Workspace changed since verification',**event('export','Stale evidence refused')}
    out=RUNTIME/s['run_id']/'repair.patch'
    out.write_text(s['patch'])
    if out.read_text()!=s['patch']:
        raise RuntimeError('Artifact readback failed')
    return {'status':'completed',**event('export','Approved patch written and read back successfully')}


def escalate(s):
    return {'status':'needs_engineer',**event('escalate','Repair budget exhausted or integrity violation; no export')}


def build_graph(checkpointer):
    graph=StateGraph(State)
    for name,fn in [('intake',intake),('baseline',baseline),('upgrade',upgrade),('reproduce',reproduce),('diagnose',diagnose),('apply',apply),('verify',verify),('evidence',evidence),('approval',approval),('export',export),('escalate',escalate)]:
        graph.add_node(name,fn)
    graph.add_edge(START,'intake')
    for a,b in [('intake','baseline'),('baseline','upgrade'),('reproduce','diagnose'),('diagnose','apply')]:
        graph.add_conditional_edges(a,lambda s,n=b: END if s.get('status')=='blocked' else n,[END,b])
    graph.add_edge('upgrade','reproduce')
    graph.add_conditional_edges('apply',lambda s: ('diagnose' if s['attempts']<2 else 'escalate') if s.get('status')=='blocked' else 'verify',['diagnose','escalate','verify'])
    graph.add_conditional_edges('verify',route_verification,['evidence','diagnose','escalate'])
    graph.add_edge('evidence','approval')
    graph.add_conditional_edges('approval',lambda s:'export' if s['approved'] else END,['export',END])
    graph.add_edge('export',END)
    graph.add_edge('escalate',END)
    return graph.compile(checkpointer=checkpointer)


def open_graph():
    RUNTIME.mkdir(exist_ok=True)
    os.environ['LANGGRAPH_STRICT_MSGPACK']='true'
    connection=sqlite3.connect(RUNTIME/'checkpoints.sqlite',check_same_thread=False)
    connection.execute('PRAGMA journal_mode=WAL')
    return build_graph(SqliteSaver(connection)),connection
