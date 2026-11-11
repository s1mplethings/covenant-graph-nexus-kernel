import copy,json,random
import pytest
from cgkn.protocol.adaptive_context import (AdaptiveContextEnvelope,ContextPacker,ContextReferenceResolver,estimate_tokens,encoded)
from cgkn.protocol.contract_integrity import ContractIntegrityChecker
from cgkn.protocol.exchange import exchange
from cgkn.protocol.normalization import ContractError
from cgkn.providers import ModelRoleConfig
from tests.protocol.test_repair_path import registry,snapshot,Fake

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def policy(capacity=100000):
    return {'models':{'fake':{'test':{'limits':[{'kind':'PROVIDER_CONTEXT_LIMIT','unit':'tokens','value':capacity,'source':'test model catalog'}]}}},'roles':{'agent':{'context_share':0.01}}}

def config():return ModelRoleConfig('agent','fake',model_id='test')

@pytest.mark.parametrize('seed',range(200))
def test_property_relative_to_envelope_preserves_mandatory_facts(seed):
    rng=random.Random(seed);capacity=rng.choice([32000,128000,1000000])
    cfg=config();pol=policy(capacity);packer=ContextPacker(pol)
    env=AdaptiveContextEnvelope(pol).derive(cfg,estimate={'upper':100})
    size=int(env['soft_budget']*rng.choice([0.2,1,2,4]))
    fact=''.join(rng.choice('abc汉字123') for _ in range(size))
    prompt={'context':{'goal':'immutable goal','failed_acceptance_ids':['a','b'],'public_contracts':{'fact':fact},'evidence_refs':['raw:1']},'duplicated_contract':{'fact':fact}}
    _,packed,receipt=packer.assemble('system',prompt,cfg)
    assert ContextPacker.restore(packed)==prompt
    assert receipt['critical_context_preserved']
    assert receipt['envelope']['context_capacity']==capacity
    assert not receipt['token_estimate']['exact']
    assert receipt['after_bytes']<=receipt['before_bytes']

def test_soft_budget_can_expand_but_true_token_limit_cannot():
    packer=ContextPacker(policy(4000));prompt={'context':{'goal':'goal','contract':'x'*3000}}
    _,packed,r=packer.assemble('',prompt,config())
    assert 'CONTEXT_EXPANSION_ALLOWED' in r['events']
    assert 'UNKNOWN_LIMIT' in r['events']
    assert ContextPacker.restore(packed)==prompt
    with pytest.raises(ContractError,match='PROVIDER_CONTEXT_LIMIT'):
        packer.assemble('',prompt,config(),tokenizer=lambda text:3000)

def test_sourced_transport_ceiling_and_unknown_model():
    pol={'transport_limits':[{'kind':'GATEWAY_HARD_LIMIT','unit':'bytes','value':100,'source':'test transport contract'}]}
    with pytest.raises(ContractError,match='GATEWAY_HARD_LIMIT') as e:
        ContextPacker(pol).assemble('',{'context':{'goal':'汉'*100}},config())
    assert e.value.details['provider_dispatched'] is False
    assert e.value.details['packing_receipt']['critical_context_preserved']
    assert AdaptiveContextEnvelope({}).derive(config())['context_capacity'] is None

def test_token_estimate_is_not_bytes_and_exact_is_labeled():
    assert estimate_tokens('汉'*10)['upper']!=len(('汉'*10).encode())
    assert estimate_tokens('abc',tokenizer=lambda _:2)=={'lower':2,'upper':2,'exact':True,'source':'caller supplied model tokenizer'}

def test_required_tier_survives_and_raw_logs_are_referenced():
    items=[{'id':'contract','tier':'A','value':{'key':'complete'},'ref':'contract:1'},
        {'id':'raw','tier':'D','value':'log'*10000,'ref':'raw:2'},
        {'id':'related','tier':'B','value':'expected','ref':'e:3','acceptance_links':1}]
    selected,receipt=ContextPacker({}).select(items,1)
    assert selected['included']=={'contract':{'key':'complete'}}
    assert {x['ref'] for x in selected['deferred']}=={'raw:2','e:3'}
    assert receipt['required_preserved']

def test_relevance_is_configurable_and_deterministic():
    items=[{'id':'a','tier':'B','value':'xxx','ref':'a','acceptance_links':1,'dependency_distance':2},
        {'id':'b','tier':'B','value':'xxx','ref':'b','dependency_distance':0}]
    assert list(ContextPacker({'selection_algorithm':'weighted_greedy'}).select(items,5)[0]['included'])==['a']
    assert list(ContextPacker({'selection_algorithm':'dependency_first'}).select(items,5)[0]['included'])==['b']

def test_reserved_literal_is_not_reinterpreted():
    original={'context':{'$context_ref':'literal','context_values':{'x':'y'}}}
    packed,r=ContextPacker({}).fold(original)
    assert packed==original and r['folded_values']==0

@pytest.mark.parametrize('operation,kind',[('fetch_contract','contract'),('fetch_artifact','artifact'),('fetch_evidence','evidence'),('fetch_dependency_result','dependency_result'),('request_more_context','contract')])
def test_context_fetch_stays_in_same_semantic_decision(operation,kind):
    resolver=ContextReferenceResolver({'public:1':{'kind':kind,'value':{'known':'fact'},'public':True}})
    client=Fake([{'context_operation':operation,'ref':'public:1','reason':'needed to decide'},{'action':9}]);events=[]
    result,_,stats=exchange(client,config(),system='intent',context={},snapshot=snapshot(),semantic_attempt_id='one',
        compiler=lambda p,h:p,normalization={},trace=events.append,context_resolver=resolver)
    assert result=={'action':9} and len(client.requests)==2
    assert stats['semantic_decision_attempts']==1 and stats['context_expansion_attempts']==1
    assert stats['schema_repair_attempts']==0
    assert events[0]['status']=='CONTEXT_EXPANDED'
    second=ContextPacker.restore(json.loads(client.requests[1]['user']))
    assert second['call_kind']=='context_expansion_attempt' and second['context_expansion_attempts']==1
    assert second['context_expansions'][0]['value']=={'known':'fact'}
    assert all(c['semantic_attempt_id']=='one' for c in stats['calls'])

def test_hidden_or_repeated_context_request_fails_closed():
    resolver=ContextReferenceResolver({'private':{'kind':'evidence','value':'hidden checker','public':False}})
    assert resolver.catalog()==[]
    with pytest.raises(ContractError,match='NOT_AUTHORIZED'):
        resolver.resolve({'context_operation':'fetch_evidence','ref':'private','reason':'guess'})
    resolver=ContextReferenceResolver({'a':{'kind':'artifact','value':'public','public':True}})
    packet={'context_operation':'fetch_artifact','ref':'a','reason':'needed'}
    client=Fake([packet,packet]);events=[]
    with pytest.raises(ContractError,match='EXPANSION_EXHAUSTED'):
        exchange(client,config(),system='intent',context={},snapshot=snapshot(),semantic_attempt_id='one',compiler=lambda p,h:p,
            normalization={},trace=events.append,context_resolver=resolver)
    assert len(client.requests)==2

def exception_registry():
    doc=registry();entry=doc['entries'][0];definition=entry['definition']
    entry['artifact_declarations'][0]['interfaces']['public_exports'].append({'name':'TaskQueueError','kind':'exception'})
    definition['exceptions']['TaskQueueError']={'base':'Exception','when':'public operation fails'}
    definition['exception_bindings']=[{'name':'TaskQueueError','policy':definition['exceptions']['TaskQueueError'],
        'implementation_ref':'module.py','test_refs':['tests.py'],'acceptance_refs':['public']}]
    return doc

def test_export_omission_is_detected_and_projection_is_exact():
    doc=exception_registry();r=ContractIntegrityChecker.audit(doc)
    assert r['status']=='FAIL' and any(x['code']=='CONTRACT_EXPORT_INCOMPLETE' for x in r['issues'])
    projected,receipt=ContractIntegrityChecker.project_exports(doc)
    assert receipt[0]['after']['name']=='TaskQueueError' and not receipt[0]['semantics_changed']
    assert ContractIntegrityChecker.require(projected)['status']=='PASS'
    assert 'TaskQueueError' not in [x['name'] for x in doc['entries'][0]['definition']['exports']]

def test_ambiguous_export_never_guesses_exception_type():
    doc=exception_registry();doc['entries'][0]['artifact_declarations'][0]['interfaces']['public_exports'][-1].pop('kind')
    with pytest.raises(ContractError,match='AMBIGUOUS'):ContractIntegrityChecker.project_exports(doc)

@pytest.mark.parametrize('key',['exports','field_contracts','return_shapes','acceptance_bindings','types','idempotency','persistence','concurrency','edge_behavior'])
def test_incomplete_contract_cannot_reach_worker(key):
    doc=registry();doc['entries'][0]['definition'].pop(key)
    with pytest.raises(ContractError) as e:ContractIntegrityChecker.require(doc)
    assert e.value.details['failure_domain']=='CONTRACT' and not e.value.details['provider_dispatched']

def test_exception_policy_cannot_be_invented_by_projection():
    doc=exception_registry();del doc['entries'][0]['definition']['exception_bindings']
    doc,_=ContractIntegrityChecker.project_exports(doc)
    with pytest.raises(ContractError,match='CONTRACT_EXCEPTION_INCOMPLETE'):ContractIntegrityChecker.require(doc)

def test_actual_success_usage_informs_next_envelope_without_business_pass():
    client=Fake([{'action':9},{'action':9}]);events=[]
    for ident in ['first','second']:
        exchange(client,config(),system='intent',context={},snapshot=snapshot(),semantic_attempt_id=ident,
            compiler=lambda p,h:p,normalization={},trace=events.append)
    assert events[0]['packing_receipt']['envelope']['recent_success_sample_count']==0
    assert events[1]['packing_receipt']['envelope']['recent_success_sample_count']==1
    assert events[1]['packing_receipt']['recent_success_refs']==[{'request_id':'1','actual_model':'fake-model'}]
    assert 'business_pass' not in events[1]

def test_native_full_transport_payload_limit_is_not_a_model_failure():
    from cgkn.providers.gateway_client import GatewayCompletionError
    class NativeReject:
        def complete(self,**kwargs):raise GatewayCompletionError('request_too_large','full payload includes wrapper overhead')
    events=[]
    with pytest.raises(ContractError,match='GATEWAY_HARD_LIMIT') as e:
        exchange(NativeReject(),config(),system='s',context={},snapshot=snapshot(),semantic_attempt_id='one',
            compiler=lambda p,h:p,normalization={},trace=events.append)
    assert e.value.details['failure_domain']=='RESOURCE_LIMIT' and not e.value.details['provider_dispatched']
    assert events[0]['status']=='RESOURCE_LIMIT'


def test_returned_context_refs_are_exact_lossless_and_preserve_literal_source_text():
    from cgkn.protocol.adaptive_context import resolve_response_refs
    packed={'context_values':{'v1':'frozen goal','v2':['must pass']}}
    raw={'goal':{'$context_ref':'v1'},'accept':{'$context_ref':'v2'},
         'payload':'literal {"$context_ref":"v1"} source string'}
    restored,receipt=resolve_response_refs(raw,packed)
    assert restored=={'goal':'frozen goal','accept':['must pass'],'payload':raw['payload']}
    assert raw['goal']=={'$context_ref':'v1'} and not receipt['semantics_changed']
    assert receipt['resolved_refs']==['v1','v2']
    for bad in [{'$context_ref':'missing'},{'$context_ref':'v1','extra':True}]:
        with pytest.raises(ContractError,match='CONTEXT_RESPONSE_REF_INVALID'):resolve_response_refs(bad,packed)
    with pytest.raises(ContractError,match='CONTEXT_RESPONSE_REF_CYCLE'):
        resolve_response_refs({'$context_ref':'v1'},{'context_values':{'v1':{'$context_ref':'v1'}}})


def test_exchange_resolves_reference_before_preserving_valid_semantic_fields():
    from cgkn.providers import ProviderCompletion
    from cgkn.protocol.compiler import TableSnapshot
    goal='Exact original public goal '+('repeat Unicode 契约 '*40)
    traces=[]
    class Echo:
        def __init__(self):self.calls=0
        def complete(self,**kw):
            self.calls+=1
            packed=json.loads(kw['user']);pool=packed.get('context_values',{})
            key=next(k for k,v in pool.items() if v==goal) if self.calls==1 else None
            packet={'goal':{'$context_ref':key} if self.calls==1 else goal,'target':0 if self.calls==1 else 1}
            return ProviderCompletion(json.dumps(packet),model='fake',request_id=str(self.calls),usage={},raw_finish_reason='completed')
    client=Echo()
    def compile(packet,bound):
        assert packet['goal']==goal
        if packet['target']==0:raise ContractError('INTEGER_ID_REQUIRED',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
        return packet
    value,completion,usage=exchange(client,config(),system='Return bounded JSON',
        context={'goal':goal,'repeat_goal':goal},snapshot=TableSnapshot({'nodes':[]}),
        semantic_attempt_id='alias-regression',compiler=compile,normalization={},trace=traces.append,
        context_policy=policy())
    assert value=={'goal':goal,'target':1} and client.calls==2
    assert traces[0]['context_reference_normalization']['resolved_refs']
    assert traces[-1]['semantic_diff']['changed_fields']==['target']
    assert '$context_ref' in traces[0]['raw_text']
