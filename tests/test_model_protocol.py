import json
from types import SimpleNamespace
import httpx
import pytest
from rescue import model,graph


def fixture_case(tmp_path):
    baseline=tmp_path/'templates/baseline/node_modules/widget';baseline.mkdir(parents=True)
    current=tmp_path/'workspace/node_modules/widget';current.mkdir(parents=True)
    for folder,text in [(baseline,'const Cache = require("widget")'),(current,'const { Cache } = require("widget")')]:
        (folder/'package.json').write_text('{"main":"index.js"}')
        (folder/'README.md').write_text(text)
        (folder/'index.js').write_text('exports.Cache = class Cache {}')
    source=tmp_path/'workspace/src';source.mkdir()
    (source/'main.js').write_text('const Local = require("widget")\nnew Local()\n')
    case=SimpleNamespace(dependency='widget',old_version='1.0.0',target_version='2.0.0',templates=tmp_path/'templates',source_globs=['src/*.js'],max_edits=1)
    return case,tmp_path/'workspace'


def test_provider_prompt_explains_edit_contract_and_version_changes(tmp_path,monkeypatch):
    case,root=fixture_case(tmp_path);captured={}
    output={'diagnosis':'Named export preserves local binding','edits':[{'path':'src/main.js','start_line':1,'end_line':2,'new':'const { Cache: Local } = require("widget")'}]}
    def respond(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200,json={'message':{'content':json.dumps(output)},'prompt_eval_count':100,'eval_count':50,'done_reason':'stop'})
    client=httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    repair,usage=model.propose(root,{'tests':{'failures':[{'message':'Local is not a constructor'}]}},1,case)
    prompt=json.loads(captured['messages'][1]['content'])
    assert prompt['output_schema']==captured['format']
    assert 'NUMBERED ORIGINAL SOURCE' in prompt['edit_contract']
    assert any('Cache' in x.get('text','') for x in prompt['dependency_api_changes'])
    assert repair['edits'][0]['old']=='const Local = require("widget")\n'
    assert repair['edits'][0]['new']=='const { Cache: Local } = require("widget")\n' and usage['valid']


def test_schema_failure_records_call_without_echoing_model_text(tmp_path,monkeypatch):
    case,root=fixture_case(tmp_path)
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':'{"unexpected":"PRIVATE_CONTENT"}'},'done_reason':'length','eval_count':3000})))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    with pytest.raises(model.ProposalError) as error:model.propose(root,{},1,case)
    assert error.value.usage['valid'] is False
    assert error.value.usage['output_tokens']==3000
    assert 'PRIVATE_CONTENT' not in str(error.value)
    assert 'diagnosis' in str(error.value)


def test_compatible_provider_uses_numbered_ranges(tmp_path,monkeypatch):
    case,root=fixture_case(tmp_path);captured={}
    output={'diagnosis':'Named export','edits':[{'path':'src/main.js','start_line':1,'end_line':2,'new':'const { Cache: Local } = require("widget")'}]}
    def respond(request):
        captured.update(json.loads(request.content))
        assert request.headers['Authorization']=='Bearer test-only-provider-key'
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(output)},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':40}})
    client=httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setenv('RESCUE_MODEL_URL','https://provider.example/v1');monkeypatch.setenv('RESCUE_MODEL','test-model');monkeypatch.setenv('RESCUE_MODEL_PROVIDER','chat-completions');monkeypatch.setenv('RESCUE_MODEL_API_KEY','test-only-provider-key')
    repair,usage=model.propose(root,{},1,case)
    assert captured['response_format']['json_schema']['strict']
    assert repair['edits'][0]['old']=='const Local = require("widget")\n'
    assert usage['output_tokens']==40


def test_out_of_range_proposal_never_changes_source(tmp_path,monkeypatch):
    case,root=fixture_case(tmp_path);original=(root/'src/main.js').read_text()
    output={'diagnosis':'Invalid range','edits':[{'path':'src/main.js','start_line':500,'end_line':501,'new':'anything'}]}
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(output)}})))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    with pytest.raises(model.ProposalError):model.propose(root,{},1,case)
    assert (root/'src/main.js').read_text()==original


def test_numbered_replacement_preserves_neighboring_line(tmp_path,monkeypatch):
    from rescue.guards import Repair,apply_repair
    case,root=fixture_case(tmp_path)
    output={'diagnosis':'Named export','edits':[{'path':'src/main.js','start_line':1,'end_line':2,'new':'1: const { Cache: Local } = require("widget")'}]}
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(output)}})))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    repair,_=model.propose(root,{},1,case);apply_repair(root,Repair.model_validate(repair),case.source_globs)
    assert (root/'src/main.js').read_text()=='const { Cache: Local } = require("widget")\nnew Local()\n'


def test_qwen_retry_uses_bounded_thinking_without_persisting_trace(tmp_path,monkeypatch):
    case,root=fixture_case(tmp_path);captured={}
    output={'diagnosis':'Named export','edits':[{'path':'src/main.js','start_line':1,'end_line':2,'new':'const { Cache: Local } = require("widget")'}]}
    def respond(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200,json={'message':{'content':json.dumps(output),'thinking':'PRIVATE_REASONING'},'eval_count':100})
    client=httpx.Client(transport=httpx.MockTransport(respond));monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setenv('RESCUE_MODEL','qwen3:4b')
    repair,usage=model.propose(root,{},2,case)
    assert captured['think'] is True and captured['options']['num_predict']==4000
    assert usage['thinking_enabled'] and 'PRIVATE_REASONING' not in json.dumps([repair,usage])


def test_invalid_model_output_exhausts_budget_without_apply(tmp_path,monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    monkeypatch.setattr(graph,'RUNTIME',tmp_path)
    def invalid(*args,**kwargs):raise model.ProposalError('Invalid fields',{'valid':False})
    monkeypatch.setattr(graph,'propose',invalid)
    workflow=graph.build_graph(InMemorySaver());config={'configurable':{'thread_id':'invalid'}}
    workflow.update_state(config,{'run_id':'invalid','events':[],'status':'running','attempts':0,'sources':{},'broken':{'failures':[]}},as_node='investigate')
    result=workflow.invoke(None,config)
    assert result['status']=='needs_engineer' and result['attempts']==3
    assert len(result['model_calls'])==3
    assert not any(e['node']=='apply' for e in result['events'])


def test_import_normalization_preserves_referenced_local_binding(tmp_path):
    from rescue.guards import normalize_bindings,Repair,Edit
    case,root=fixture_case(tmp_path)
    repair=Repair(diagnosis='Named constructor export',edits=[Edit(path='src/main.js',old='const Local = require("widget")',new='const { Cache } = require("widget")')])
    normalized,notes=normalize_bindings(root,repair,case.source_globs)
    assert normalized.edits[0].new=='const { Cache: Local } = require("widget")'
    assert notes and (root/'src/main.js').read_text().startswith('const Local =')
    # When all usages have already been renamed, no alias may undo that change.
    repair.edits.append(Edit(path='src/main.js',old='new Local()',new='new Cache()'))
    normalized,notes=normalize_bindings(root,repair,case.source_globs)
    assert normalized.edits[0].new=='const { Cache } = require("widget")' and not notes


def test_normalization_preserves_commonjs_format_and_binding(tmp_path):
    from rescue.guards import normalize_bindings,Repair,Edit
    case,root=fixture_case(tmp_path)
    repair=Repair(diagnosis='Named export',edits=[Edit(path='src/main.js',old='const Local = require("widget")',new='import { Cache } from "widget"')])
    normalized,notes=normalize_bindings(root,repair,case.source_globs)
    assert normalized.edits[0].new=='const { Cache: Local } = require("widget")'
    assert len(notes)==2


def test_duplicate_export_rejected_without_partial_write(tmp_path):
    from rescue.guards import apply_repair,Repair,Edit
    root=tmp_path;source=root/'main.js'
    original='const f = () => 1;\nmodule.exports = f;\n';source.write_text(original)
    repair=Repair(diagnosis='Candidate',edits=[Edit(path='main.js',old='const f = () => 1;',new='const f = () => 2;\nmodule.exports = f;')])
    with pytest.raises(ValueError,match='existing export'):apply_repair(root,repair,['*.js'])
    assert source.read_text()==original


@pytest.mark.parametrize('provider,header', [('gemini','x-goog-api-key'),('anthropic','x-api-key')])
def test_native_hosted_provider_contract(tmp_path,monkeypatch,provider,header):
    case,root=fixture_case(tmp_path)
    output={'diagnosis':'Named export','edits':[{'path':'src/main.js','start_line':1,'end_line':2,'new':'const { Cache: Local } = require("widget")'}]}
    def respond(request):
        assert request.headers[header]=='test-only-key'
        payload=json.loads(request.content)
        assert 'test-only-key' not in request.content.decode()
        if provider=='gemini':
            assert payload['generationConfig']['responseJsonSchema']['additionalProperties'] is False
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'PRIVATE_REASONING','thought':True},{'text':json.dumps(output)}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':40}})
        assert payload['output_config']['format']['type']=='json_schema'
        return httpx.Response(200,json={'content':[{'type':'text','text':json.dumps(output)}],'usage':{'input_tokens':100,'output_tokens':40},'stop_reason':'end_turn'})
    client=httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(model.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setenv('RESCUE_MODEL_PROVIDER',provider)
    monkeypatch.setenv(provider.upper()+'_API_KEY','test-only-key')
    repair,usage=model.propose(root,{},1,case)
    assert usage['output_tokens']==40 and usage['valid']
    assert 'PRIVATE_REASONING' not in json.dumps([repair,usage])


def test_provider_error_is_actionable_and_redacted():
    response=httpx.Response(429,json={'error':{'message':'PRIVATE_KEY_OR_SOURCE'}})
    with pytest.raises(model.ProviderError) as error:model.provider_status(response)
    assert 'quota' in str(error.value) and 'PRIVATE' not in str(error.value)
