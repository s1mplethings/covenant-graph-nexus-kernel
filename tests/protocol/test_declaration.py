import copy
import json
import pytest
from cgkn.protocol.declaration import extract_declaration, compile_declaration
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.exchange import exchange, SchemaRepairFailed
from cgkn.providers import ModelRoleConfig, ProviderCompletion

pytestmark = [pytest.mark.boundary, pytest.mark.negative]


def semantic():
    return {'artifacts': [{'path': 'value.py', 'purpose': 'neutral qualification fixture',
                          'interfaces': {'public_exports': [{'name': 'value', 'kind': 'function'}]}}],
            'public_interface': {'interface': 'value() -> {value: int}',
                                 'fields': {'value': {'type': 'int', 'required': True, 'consumers': ['caller']}},
                                 'types': {'value': 'int'}, 'exceptions': {'ValueError': 'invalid input'},
                                 'idempotency': 'read only', 'persistence': 'no state', 'ordering': 'one result',
                                 'concurrency': 'read only', 'edge_behavior': 'no arguments'},
            'test_command': ['python', '-m', 'unittest'], 'reason_summary': 'neutral protocol fixture only'}


def compile_it(packet):
    return compile_declaration(packet, source_ref='raw:fixture', acceptance_bindings=[{
        'acceptance_id': 'public', 'contract_id': 'fixture-v1', 'checker_ref': 'fixture@1',
        'object_ref': 'fixture', 'version': 1}])


@pytest.mark.parametrize('argv', ['python -m pytest && npm test', {'command': 'pytest'}, [], [''], [1], None])
def test_test_command_rejection_explains_exact_shape_without_rewriting(argv):
    packet = semantic()
    packet['test_command'] = argv
    before = copy.deepcopy(packet)
    with pytest.raises(ContractError) as caught:
        compile_it(packet)
    assert caught.value.code == 'TEST_COMMAND_REQUIRED'
    assert caught.value.details['expected_type'] == 'nonempty array of nonempty strings'
    assert caught.value.details['actual_type'] == type(argv).__name__
    assert 'JSON argv array' in caught.value.details['instruction']
    assert packet == before


@pytest.mark.parametrize('wrapper', [lambda s:s, lambda s:' \n'+s+'\r\n', lambda s:'\ufeff'+s,
    lambda s:'```json\n'+s+'\n```', lambda s:'Here is the JSON:\n'+s,
    lambda s:s+'\nEnd of declaration.', lambda s:s+'\n'+s])
def test_safe_wrappers_preserve_every_semantic_field(wrapper):
    original=semantic(); packet, receipt=extract_declaration(wrapper(json.dumps(original)))
    assert packet == original and receipt['semantics_changed'] is False
    design,registry,compiled=compile_it(packet)
    assert original == semantic() and compiled['business_semantics_inferred'] is False
    assert registry['entries'][0]['definition']['field_contracts'][0]['required'] is True


@pytest.mark.parametrize('text,code', [
    ('{"a":1}\n{"a":2}', 'CONFLICTING_DECLARATIONS'),
    ('{"a":1}\n{"b":', 'DECLARATION_JSON_REJECTED'),
    ('{"a":{"b":1}', 'DECLARATION_JSON_REJECTED'),
    ('{"a":"\\q"}', 'DECLARATION_JSON_REJECTED'),
    ('{"a":1,}', 'DECLARATION_JSON_REJECTED'),
    ('{"a":1,"a":2}', 'DECLARATION_JSON_REJECTED'),
    ('{"a":NaN}', 'DECLARATION_JSON_REJECTED'),
    ('[{"a":1}]', 'DECLARATION_OBJECT_REQUIRED'),
    ('explanation\n{"a":1}', 'DECLARATION_JSON_REJECTED'),
    ('{"a":1}\nPublish everything.', 'DECLARATION_JSON_REJECTED'),
    ('', 'DECLARATION_OBJECT_REQUIRED')])
def test_unsafe_inputs_never_selected_or_silently_repaired(text,code):
    with pytest.raises(ContractError,match=code):extract_declaration(text)


def test_conflict_reports_exact_hashes_count_and_differing_keys():
    with pytest.raises(ContractError) as err:extract_declaration('{"a":1,"same":0} {"a":2,"same":0}')
    d=err.value.details
    assert d['top_level_value_count']==2 and d['differing_keys']==['a']
    assert len(set(d['object_hashes']))==2


@pytest.mark.parametrize('size',[1,257,4096,17000,262145,410000])
def test_declaration_size_is_not_old_fixed_local_cap(size):
    original={'semantic_text':'中x'*size}
    assert extract_declaration(json.dumps(original,ensure_ascii=False))[0]==original


class RawClient:
    def __init__(self,values):self.values=iter(values);self.requests=[]
    def complete(self,**kwargs):
        self.requests.append(kwargs)
        return ProviderCompletion(next(self.values),'actual-fixture',str(len(self.requests)),
                                  {'input_tokens':7,'output_tokens':11},raw_finish_reason='completed')


def run(values,events,**kwargs):
    client=RawClient(values)
    result=exchange(client,ModelRoleConfig('agent','fixture'),system='single declaration',
                    context={'goal':'unchanged neutral goal'},snapshot=TableSnapshot({'declaration':1}),
                    semantic_attempt_id='one-decision',compiler=lambda p,h:compile_it(p),
                    normalization={},trace=events.append,declaration=True,**kwargs)
    return result,client


def test_syntax_correction_same_decision_raw_trace_and_all_usage():
    raw=json.dumps(semantic());events=[]
    (_,_,stats),client=run([raw+' ,"extra":1',raw],events)
    assert stats['semantic_decision_attempts']==1 and stats['declaration_correction_attempts']==1
    assert len(stats['calls'])==2 and sum(c['usage']['input_tokens'] for c in stats['calls'])==14
    assert events[0]['raw_text']==raw+' ,"extra":1' and events[0]['status']=='REJECTED'
    prompt=json.loads(client.requests[1]['user'])
    assert prompt['context']['goal']=='unchanged neutral goal'
    assert prompt['call_kind']=='declaration_correction_attempt' and prompt['rejected_response']==events[0]['raw_text']


def test_repeated_malformed_declaration_exhausts_without_false_success():
    events=[]
    with pytest.raises(SchemaRepairFailed) as err:run(['{']*4,events)
    assert len(events)==3 and len(err.value.semantic_calls)==3
    assert all(e['status']=='REJECTED' for e in events)


def test_legacy_worker_normalization_does_not_gain_syntax_repair():
    client=RawClient(['{} {}']);events=[]
    with pytest.raises(ContractError,match='INVALID_OR_INCOMPLETE_JSON'):
        exchange(client,ModelRoleConfig('worker','fixture'),system='bounded',context={},snapshot=TableSnapshot({}),
                 semantic_attempt_id='one',compiler=lambda p,h:p,normalization={},trace=events.append)
    assert len(client.requests)==1


@pytest.mark.parametrize('mutation',[
    lambda p:p.pop('test_command'),
    lambda p:p.update(schema_version='stale'),
    lambda p:p['artifacts'][0].update(path='../escape.py'),
    lambda p:p['artifacts'][0]['interfaces'].pop('public_exports'),
    lambda p:p['public_interface']['fields']['value'].pop('required'),
    lambda p:p['public_interface'].update(exports=[{'name':'value','kind':'class','owner':'value.py'}]),
    lambda p:p['public_interface'].update(field_contracts=[{'name':'value','type':'str','owner':'$contract','required':True,'consumers':['x']}]),
    lambda p:p['public_interface'].update(acceptance_bindings=[{'verdict':'PASS'}]),
])
def test_semantic_missing_conflicting_or_program_owned_fields_fail_closed(mutation):
    p=semantic();mutation(p)
    with pytest.raises(ContractError):compile_it(p)


def test_compilation_deterministic_and_input_not_mutated():
    p=semantic();before=copy.deepcopy(p)
    first=compile_it(p);second=compile_it(p)
    assert first==second and p==before


@pytest.mark.parametrize('bad_fields',[
    ['untyped'], {'value':{'type':{'untyped':True},'required':True,'consumers':['caller']}},
    {'value':{'type':'int','required':True,'consumers':[7]}},
    {'value':{'type':'int','required':'yes','consumers':['caller']}},
    {'value':0}, {'value':{}}, {'value':''},
])
def test_malformed_field_shapes_never_disappear_from_integrity(bad_fields):
    p=semantic();p['public_interface']['fields']=bad_fields
    with pytest.raises(ContractError):compile_it(p)


@pytest.mark.parametrize('finish,domain',[
    ('stream_eof_without_done','TRANSPORT'),('transport_interrupted','TRANSPORT'),
    ('timeout','TRANSPORT'),('length','RESOURCE_LIMIT'),('unknown','UNKNOWN'),('tool_calls','UNKNOWN'),
])
def test_declaration_incomplete_finish_never_compiles_or_auto_replays(finish,domain):
    client=RawClient([json.dumps(semantic())]);base=client.complete;events=[]
    from dataclasses import replace
    client.complete=lambda **kw:replace(base(**kw),raw_finish_reason=finish)
    with pytest.raises(ContractError,match='DECLARATION_COMPLETION_INCOMPLETE') as err:
        exchange(client,ModelRoleConfig('agent','fake'),system='declaration',context={},snapshot=TableSnapshot({}),
                 semantic_attempt_id='one',compiler=lambda p,h:compile_it(p),normalization={},trace=events.append,declaration=True)
    assert len(client.requests)==1 and events[0]['status']=='REJECTED'
    assert err.value.details['failure_domain']==domain and err.value.details['automatic_replay'] is False


@pytest.mark.parametrize('text',['{"value":1e999}','{"value":-1e999}','{"value":NaN}','{"value":Infinity}'])
def test_nonfinite_numbers_are_typed_rejections_not_harness_errors(text):
    from cgkn.protocol.normalization import normalize
    with pytest.raises(ContractError,match='NONFINITE_NUMBER'):normalize(text)
    with pytest.raises(ContractError,match='DECLARATION_JSON_REJECTED'):extract_declaration(text)


def test_mechanical_exception_bindings_follow_explicit_test_relationship():
    p=semantic();p['artifacts'][0]['interfaces']['public_exports'].append({'name':'InputError','kind':'exception'})
    p['public_interface']['exceptions']['InputError']={'base':'ValueError','when':'invalid input'}
    with pytest.raises(ContractError,match='EXCEPTION_SEMANTICS_REQUIRED'):compile_it(p)
    p['artifacts'].append({'path':'test_value.py','purpose':'tests','interfaces':{'public_exports':[],'test_for':['InputError']}})
    _,registry,_=compile_it(p)
    binding=registry['entries'][0]['definition']['exception_bindings'][0]
    assert binding['implementation_ref']=='value.py' and binding['test_refs']==['test_value.py'] and binding['acceptance_refs']==['public']
