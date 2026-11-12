import json
from cgkn.adapters.veriarbor.provider_novelty_adapter import request_novelty, novelty_disposition


def request(attempt='1', artifact='source', evidence='missing media'):
    return {'schema_name':'worker_action','system':'bounded work','schema':None,
            'user':json.dumps({'semantic_attempt_id':attempt,'table_hash':attempt,'call_kind':'semantic',
              'context':{'leaf_goal':'repair','observations':{'source_hash':artifact},
                         'actual_behavior':{'failure':evidence}},'tables':{'paths':[]}})}


def test_attempt_and_timestamp_do_not_make_novelty():
    a=request_novelty(request('1'),'worker',{'node_id':'a','attempt_id':'1'})
    b=request_novelty(request('2'),'worker',{'node_id':'a','attempt_id':'2'})
    assert a==b
    assert novelty_disposition([a],b)=='NO_NOVEL_DELTA'


def test_artifact_and_actual_new_evidence_permit_work():
    a=request_novelty(request(),'worker')
    assert novelty_disposition([a],request_novelty(request(artifact='changed'),'worker'))=='EXECUTE'
    assert novelty_disposition([a],request_novelty(request(evidence='different counterexample'),'worker'))=='EXECUTE'


def test_different_node_is_different_work_not_same_request():
    a=request_novelty(request(),'worker',{'node_id':'a'})
    b=request_novelty(request(),'worker',{'node_id':'b'})
    assert novelty_disposition([a],b)=='EXECUTE'


def test_opaque_inputs_use_exact_boundary():
    a=request_novelty({'user':'task','schema_name':'plain'},'agent')
    assert novelty_disposition([a],a)=='NO_NOVEL_DELTA'
    b=request_novelty({'user':'different task','schema_name':'plain'},'agent')
    assert novelty_disposition([a],b)=='EXECUTE'


def test_folded_context_is_lossless_for_novelty():
    public=request()
    packed=json.loads(public['user'])
    actual=packed['context']['actual_behavior']
    packed['context']['actual_behavior']={'$context_ref':'fact'}
    packed['context_values']={'fact':actual}
    assert request_novelty({**public,'user':json.dumps(packed)},'worker')==request_novelty(public,'worker')


def test_recorded_call_rejects_same_facts_before_second_dispatch(tmp_path):
    import pytest
    from cgkn.providers import ModelRoleConfig, ProviderCompletion
    from cgkn.providers.recording import RecordedCompletionClient
    from cgkn.providers.gateway_client import GatewayCompletionError
    from cgkn.state import FileRunStore
    class Client:
        calls=0
        def complete(self,**kwargs):
            self.calls+=1
            return ProviderCompletion('{}','fixture','response',{})
    client=Client();store=FileRunStore(tmp_path/'state')
    recorded=RecordedCompletionClient(client,store,'p','r')
    config=ModelRoleConfig('worker','fixture')
    recorded.complete(**request('1'),config=config)
    before={str(p):p.read_bytes() for p in recorded.root.glob('*/*.json')}
    with pytest.raises(GatewayCompletionError,match='NO_NOVEL_DELTA'):
        recorded.complete(**request('2'),config=config)
    assert client.calls==1
    assert all(__import__('pathlib').Path(p).read_bytes()==b for p,b in before.items())
    assert len(list(recorded.root.glob('*/request.json')))==1
    recorded.complete(**request('3',artifact='new'),config=config)
    assert client.calls==2
    assert any(e.event_type=='PROVIDER_NOVELTY_DENIED' for e in store.load_events('p','r'))
