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
from .guards import Repair, apply_repair, digest_files, protected_digest, source_files, source_preflight, normalize_bindings
from .model import propose, ProposalError, ProviderError, dependency_context
from .runner import run_tests
from .security import SecurityViolation, screen_evidence, screen_output, check_new_capabilities
from .config import ROOT, RUNTIME, get_case

TEMPLATES=ROOT/'data/external/templates'


class State(TypedDict, total=False):
    run_id: str
    case_id: str
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
    environment_digest: str
    verified_sources: str
    case_digest: str
    model_calls: Annotated[list[dict],operator.add]
    api_evidence: list[dict]


def case(s):
    return get_case(s.get('case_id','v8r-js-yaml'))


def environment_digest(root):
    # Includes installed dependency content. Cache is the only mutable package directory.
    paths=[p for p in (root/'node_modules').rglob('*') if p.is_file() and '.cache' not in p.parts]
    return digest_files(root,paths)


def cancelled(s):
    return (RUNTIME/s['run_id']/'cancel').exists()


def workspace(s):
    return RUNTIME/s['run_id']/'workspace'


def event(node, detail):
    return {'events':[{'node':node,'detail':detail}]}


def intake(s):
    selected=case(s)
    if not selected.public()['ready']:
        return {'status':'blocked','error':'Run case setup first',**event('intake','Prepared case missing')}
    folder=workspace(s)
    if not folder.exists():
        if shutil.disk_usage(RUNTIME).free<1_500_000_000:
            raise RuntimeError('Insufficient free disk for an isolated run')
        staging=folder.with_name('workspace-staging')
        if staging.exists():shutil.rmtree(staging)
        shutil.copytree(selected.templates/'baseline',staging,symlinks=True)
        staging.replace(folder)
    source_preflight(folder,selected.source_globs)
    return {'status':'running','attempts':0,'case_id':selected.id,**event('intake',f'Pinned {selected.repository}@{selected.base_commit[:12]}; isolated workspace created')}


def baseline(s):
    result=run_tests(workspace(s),case=case(s),phase='baseline')
    return {'baseline':result,'status':'running' if result['ok'] else 'blocked','error':None if result['ok'] else 'Original repository tests do not pass in this environment. Resolve baseline failures or configure a compatible runner before attempting an upgrade.',**event('baseline',f"{result['passes']}/{result['tests']} baseline tests passed")}


def upgrade(s):
    dest=workspace(s)
    # Idempotent replacement of prepared dependency environment, never arbitrary shell.
    selected=case(s)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(selected.templates/'upgraded',dest,symlinks=True)
    if selected.version(dest)!=selected.target_version:
        raise ValueError('Installed dependency must exactly match approved target')
    return {'protected':protected_digest(dest,selected.source_globs),'environment_digest':environment_digest(dest),'sources':{str(p.relative_to(dest)):p.read_text() for p in source_files(dest,selected.source_globs)},**event('upgrade',f'Applied pinned upgrade to {selected.dependency} {selected.target_version}')}


def reproduce(s):
    result=run_tests(workspace(s),case=case(s),phase='upgraded')
    reproduced=not result['ok'] and bool(result['failures']) and not result['timed_out'] and not result.get('infrastructure_error')
    return {'broken':result,'status':'running' if reproduced else 'blocked',**event('reproduce',f"{len(result['failures'])} failures; regression reproduced={reproduced}")}


def investigate(s):
    try:
        evidence=dependency_context(workspace(s),case(s),s['broken'])
        screen_evidence(evidence,'dependency documentation')
    except SecurityViolation as exc:
        return {'status':'blocked','error':str(exc),**event('security','Untrusted dependency evidence blocked before checkpointing or model access')}
    return {'api_evidence':evidence,**event('investigate','Compared original and upgraded package APIs; retrieved '+str(len(evidence))+' bounded evidence sections')}


def diagnose(s):
    # Each attempt starts from original upgraded source, avoiding cumulative patch drift.
    for name,content in s['sources'].items():
        (workspace(s)/name).write_text(content)
    try:
        failure={'tests':s.get('verification',s['broken']),'previous_patch_rejection':s.get('error'),'previous_patch':s.get('repair')}
        repair,usage=propose(workspace(s),failure,s['attempts']+1,case=case(s),api_evidence=s.get('api_evidence'))
        return {'repair':repair,'model_usage':usage,'model_calls':[usage],'attempts':s['attempts']+1,'status':'running','error':'',**event('diagnose','Model proposed a structured source repair')}
    except SecurityViolation as exc:
        return {'status':'blocked','error':str(exc),**event('security','Model processing blocked by security policy; operator review required')}
    except ProposalError as exc:
        return {'repair':{},'model_calls':[exc.usage],'attempts':s['attempts']+1,'status':'retry','error':str(exc),**event('diagnose','Model output failed schema validation; charged against retry budget')}
    except ProviderError as exc:
        return {'status':'blocked','error':str(exc),**event('diagnose','Hosted provider unavailable; check model access or quota')}
    except ValueError:
        return {'repair':{},'attempts':s['attempts']+1,'status':'retry','error':'Invalid structured model output',**event('diagnose','Model output failed schema validation; charged against retry budget')}
    except Exception as exc:
        return {'status':'blocked','error':f'Model failed: {type(exc).__name__}',**event('diagnose','Model request failed; no fallback patch fabricated')}


def apply(s):
    try:
        changed=apply_repair(workspace(s),Repair.model_validate(s['repair']),case(s).source_globs)
        return event('apply','Validated exact-match source edits: '+', '.join(changed))
    except ValueError as exc:
        return {'status':'blocked','error':str(exc),**event('apply','Patch rejected by source-edit policy')}


def normalize(s):
    repair,notes=normalize_bindings(workspace(s),Repair.model_validate(s['repair']),case(s).source_globs)
    return {'repair':repair.model_dump(),**event('normalize','; '.join(notes) if notes else 'Candidate needs no import binding normalization')}


def verify(s):
    root=workspace(s)
    selected=case(s)
    before=digest_files(root,source_files(root,selected.source_globs))
    result=run_tests(root,case=selected,phase='upgraded')
    intact=protected_digest(root,selected.source_globs)==s['protected'] and digest_files(root,source_files(root,selected.source_globs))==before and environment_digest(root)==s['environment_digest']
    installed=selected.version(root)
    result['integrity_ok']=intact
    result['dependency_version']=installed
    result['ok']=result['ok'] and intact and installed==selected.target_version and result['tests']==s['baseline']['tests']
    metadata={'verification':result,'verified_sources':before,'case_digest':hashlib.sha256(selected.model_dump_json().encode()).hexdigest(),**event('verify',f"{result['passes']}/{result['tests']} tests passed; integrity={intact}")}
    if result.get('infrastructure_error') or result.get('timed_out'):
        metadata.update(status='blocked',error='Verification infrastructure failed or exceeded its execution limit')
    return metadata


def route_verification(s):
    if s.get('status')=='blocked' or s['verification'].get('infrastructure_error') or s['verification'].get('timed_out'):
        return END
    if s['verification']['ok']:
        return 'evidence'
    return 'diagnose' if s['attempts']<case(s).max_attempts and s['verification']['integrity_ok'] else 'escalate'


def evidence(s):
    root=workspace(s)
    patch=''
    for name in [*s['sources'],'package.json','package-lock.json']:
        original=ROOT/'bootstrap'/case(s).id/'base'/name
        if name not in ['package.json','package-lock.json'] or not original.is_file():original=case(s).templates/'baseline'/name
        old=original.read_text().splitlines(keepends=True)
        new=(root/name).read_text().splitlines(keepends=True)
        patch+=''.join(difflib.unified_diff(old,new,fromfile='a/'+name if old else '/dev/null',tofile='b/'+name))
    if case(s).test_migration_files:
        patch+=(ROOT/'bootstrap'/case(s).id/'test-migration.patch').read_text()
    bound={'patch':patch,'verification':s['verification'],'environment_digest':s['environment_digest'],'protected_digest':s['protected'],'source_digest':s['verified_sources'],'case':case(s).model_dump()}
    digest=hashlib.sha256(json.dumps(bound,sort_keys=True).encode()).hexdigest()
    return {'patch':patch,'evidence_digest':digest,'status':'awaiting_approval',**event('evidence','Diff, target version, test counts and integrity bound to an approval digest')}


def approval(s):
    decision=interrupt({'run_id':s['run_id'],'evidence_digest':s['evidence_digest'],'action':'Export verified patch bundle; does not merge or deploy'})
    approved=decision.get('approve') is True and decision.get('evidence_digest')==s['evidence_digest']
    return {'approved':approved,'status':'approved' if approved else 'rejected',**event('approval','Reviewer approved evidence' if approved else 'Approval declined or stale digest')}


def export(s):
    root=workspace(s)
    selected=case(s)
    if not all(s.get(key) for key in ['environment_digest','verified_sources','case_digest']):
        return {'status':'blocked','error':'Legacy evidence lacks current integrity metadata; rerun verification',**event('export','Incomplete evidence refused')}
    inventory={str(p.relative_to(root)) for p in source_files(root,selected.source_globs)}
    if inventory!=set(s['sources']) or ('verified_sources' in s and digest_files(root,source_files(root,selected.source_globs))!=s['verified_sources']) or ('case_digest' in s and hashlib.sha256(selected.model_dump_json().encode()).hexdigest()!=s['case_digest']):
        return {'status':'blocked','error':'Source inventory or case definition changed since verification',**event('export','Stale evidence refused')}
    # Approval cannot bless a workspace changed after tests.
    expected={name:content for name,content in s['sources'].items()}
    for edit in s['repair']['edits']:
        expected[edit['path']]=expected[edit['path']].replace(edit['old'],edit['new'],1)
    if any((root/name).read_text()!=content for name,content in expected.items()) or protected_digest(root,case(s).source_globs)!=s['protected'] or ('environment_digest' in s and environment_digest(root)!=s['environment_digest']):
        return {'status':'blocked','error':'Workspace changed since verification',**event('export','Stale evidence refused')}
    try:
        screen_output(json.dumps(s['repair']))
        for edit in s['repair']['edits']:check_new_capabilities(edit['old'],edit['new'])
    except (SecurityViolation,ValueError):
        return {'status':'blocked','error':'Current security policy rejects the stored repair',**event('security','Export refused by current output policy')}
    out=RUNTIME/s['run_id']/'repair.patch'
    out.write_text(s['patch'])
    if out.read_text()!=s['patch']:
        raise RuntimeError('Artifact readback failed')
    return {'status':'completed',**event('export','Approved patch written and read back successfully')}


def escalate(s):
    return {'status':'needs_engineer','error':s.get('error') or 'Verification still fails after the repair budget; engineer review required',**event('escalate','Repair budget exhausted or integrity violation; no export')}


def build_graph(checkpointer):
    graph=StateGraph(State)
    def guarded(fn):
        def call(s):
            if cancelled(s):
                raise RuntimeError('Run cancelled')
            return fn(s)
        return call
    for name,fn in [('intake',intake),('baseline',baseline),('upgrade',upgrade),('reproduce',reproduce),('investigate',investigate),('diagnose',diagnose),('normalize',normalize),('apply',apply),('verify',verify),('evidence',evidence),('approval',approval),('export',export),('escalate',escalate)]:
        graph.add_node(name,guarded(fn))
    graph.add_edge(START,'intake')
    for a,b in [('intake','baseline'),('baseline','upgrade'),('reproduce','investigate')]:
        graph.add_conditional_edges(a,lambda s,n=b: END if s.get('status')=='blocked' else n,[END,b])
    graph.add_edge('upgrade','reproduce')
    graph.add_conditional_edges('investigate',lambda s: END if s.get('status')=='blocked' else 'diagnose',[END,'diagnose'])
    graph.add_conditional_edges('diagnose',lambda s: END if s['status']=='blocked' else ('diagnose' if s['attempts']<case(s).max_attempts else 'escalate') if s['status']=='retry' else 'normalize',[END,'diagnose','escalate','normalize'])
    graph.add_edge('normalize','apply')
    graph.add_conditional_edges('apply',lambda s: ('diagnose' if s['attempts']<case(s).max_attempts else 'escalate') if s.get('status')=='blocked' else 'verify',['diagnose','escalate','verify'])
    graph.add_conditional_edges('verify',route_verification,['evidence','diagnose','escalate',END])
    graph.add_edge('evidence','approval')
    graph.add_conditional_edges('approval',lambda s:'export' if s['approved'] else END,['export',END])
    graph.add_edge('export',END)
    graph.add_edge('escalate',END)
    return graph.compile(checkpointer=checkpointer).with_config({'recursion_limit':64})


def open_graph():
    RUNTIME.mkdir(exist_ok=True,mode=0o700)
    RUNTIME.chmod(0o700)
    os.environ['LANGGRAPH_STRICT_MSGPACK']='true'
    connection=sqlite3.connect(RUNTIME/'checkpoints.sqlite',check_same_thread=False)
    connection.execute('PRAGMA journal_mode=WAL')
    return build_graph(SqliteSaver(connection)),connection
