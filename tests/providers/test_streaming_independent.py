"""Independent negative-protocol review; no vendor transport or paid calls.

These fixtures are authored separately from the implementation tests. They do
not stand in for installed-plugin end-to-end acceptance or business correctness.
"""
import io
import json
import pytest
from tests.providers.test_streaming_runtime import runtime

from cgkn.providers.streaming_sse import (
    SSEEvent, StreamError, collect_chat_completions, collect_responses,
    save_immutable_json,
)
from cgkn.providers.gateway_stream import PROTOCOL, receive


def chat(delta=None, finish=None, **extra):
    return SSEEvent(json.dumps(dict(id='one', model='qwen-test',
        choices=[dict(index=0, delta=delta or {}, finish_reason=finish)], **extra)))


def test_reject_content_after_finish_before_done():
    with pytest.raises(StreamError):
        collect_chat_completions([
            chat({'content': '{"ok":true}'}, 'stop'),
            chat({'content': ' malicious-tail'}), SSEEvent('[DONE]')])


def test_reject_refusal_even_when_text_is_present():
    with pytest.raises(StreamError):
        collect_chat_completions([
            chat({'content': '{"ok":true}', 'refusal': 'refused'}, 'stop'),
            SSEEvent('[DONE]')])


def test_responses_reject_conflicting_final_text():
    with pytest.raises(StreamError):
        collect_responses([
            SSEEvent(json.dumps({'type':'response.output_text.delta','delta':'A'})),
            SSEEvent(json.dumps({'type':'response.completed','response':{
                'id':'one','status':'completed','model':'qwen-test','output_text':'B',
                'usage':{'input_tokens':1,'output_tokens':1}}}))])


def test_responses_reject_delta_from_other_request():
    with pytest.raises(StreamError):
        collect_responses([
            SSEEvent(json.dumps({'type':'response.created','response':{'id':'one'}})),
            SSEEvent(json.dumps({'type':'response.output_text.delta','response_id':'two','delta':'A'})),
            SSEEvent(json.dumps({'type':'response.completed','response':{
                'id':'one','status':'completed','model':'qwen-test','output_text':'A'}}))])


def channel(events):
    return io.BytesIO(b''.join(('event: '+kind+'\ndata: '+json.dumps(body)+'\n\n').encode()
        for kind,body in events))


def envelope(sequence, **updates):
    return dict(protocol=PROTOCOL,request_identity='sha256:request',session_id='session-one',
                sequence=sequence,**updates)


@pytest.mark.parametrize('mutation', ['identity','session','sequence','missing_start','error','eof'])
def test_gateway_channel_never_accepts_invalid_terminal(mutation):
    first=('cgkn.started',envelope(1))
    last=('cgkn.completed',envelope(2,gateway_http_status=200,
        response={'status':'completed','output_text':'{}'}))
    if mutation=='identity':last[1]['request_identity']='sha256:other'
    elif mutation=='session':last[1]['session_id']='old-session'
    elif mutation=='sequence':last[1]['sequence']=3
    elif mutation=='missing_start':first=('cgkn.progress',envelope(1,progress={'events':1}))
    elif mutation=='error':last=('cgkn.error',envelope(2,error_type='provider_outcome_unknown'))
    rows=[first] if mutation=='eof' else [first,last]
    with pytest.raises(StreamError):receive(channel(rows),'sha256:request',setup_seconds=1,expected_session='session-one')


def test_progress_is_delivered_before_final_content():
    progress=[]
    def lines():
        yield from channel([('cgkn.started',envelope(1)),
            ('cgkn.progress',envelope(2,progress={'text_bytes':2}))])
        assert progress==[{'text_bytes':2}]
        yield from channel([('cgkn.completed',envelope(3,gateway_http_status=200,
            response={'status':'completed','output_text':'{}'}))])
    class Response:
        iterator=lines()
        def readline(self, limit):return next(self.iterator,b'')
    assert receive(Response(),'sha256:request',setup_seconds=1,on_progress=progress.append)['output_text']=='{}'


def test_atomic_result_refuses_late_overwrite(tmp_path):
    target=tmp_path/'response.json'
    save_immutable_json(target,{'original':'accepted'})
    original=target.read_bytes()
    with pytest.raises(FileExistsError):save_immutable_json(target,{'late':'different'})
    assert target.read_bytes()==original
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('defect',['usage_missing','wrong_model','missing_status','missing_stream_completion'])
def test_formal_client_rejects_unproven_terminal(monkeypatch,defect):
    """An authenticated channel envelope alone must not admit incomplete output."""
    import hashlib
    from cgkn.providers.gateway_client import GatewayCompletionClient,GatewayCompletionError
    from cgkn.providers.client import ModelRoleConfig
    from scripts import provider_api_budget as budget
    monkeypatch.setattr('cgkn.providers.application_network.settings',lambda:None)
    monkeypatch.setattr(budget,'load_cached_response',lambda *_:None)
    monkeypatch.setattr(budget,'configured_cache_mode',lambda:'off')
    saved=[]
    monkeypatch.setattr(budget,'store_cached_response',lambda *args:saved.append(args))
    calls=[]
    def fake_open(req,timeout):
        calls.append(req)
        identity='sha256:'+hashlib.sha256(req.data).hexdigest()
        body=dict(id='upstream-one',model='qwen-test',status='completed',output_text='{}',
            usage={'input_tokens':1,'output_tokens':1},
            cgkn_model_identity={'provider_id':'qwen','requested_model':'qwen-test','actual_model':'qwen-test','identity_status':'MATCH'},
            cgkn_stream={'completed':True,'usage_status':'KNOWN'})
        if defect=='usage_missing':body.pop('usage')
        elif defect=='wrong_model':body['model']='other'
        elif defect=='missing_status':body.pop('status')
        else:body.pop('cgkn_stream')
        start=envelope(1);start['request_identity']=identity
        terminal=envelope(2,response=body,gateway_http_status=200);terminal['request_identity']=identity
        response=channel([('cgkn.started',start),('cgkn.completed',terminal)])
        response.status=200;response.headers={'Content-Type':'text/event-stream'}
        return response
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',fake_open)
    client=GatewayCompletionClient('http://127.0.0.1:1','offline-only',enforce_budget=False)
    with pytest.raises(GatewayCompletionError):
        client.complete(system='offline',user='offline',schema_name='object',schema={'type':'object'},
            config=ModelRoleConfig('agent','qwen',model_id='qwen-test'))
    assert len(calls)==1 and saved==[]


def test_adjusting_transport_timeout_cannot_replay_unknown_logical_request(runtime):
    from cgkn.providers.client import ModelRoleConfig
    from cgkn.providers.gateway_client import GatewayCompletionError
    from scripts.provider_api_budget import ProviderBudgetExhausted
    runtime['mode']='eof'
    config=ModelRoleConfig('agent','qwen',timeout_seconds=3,max_output_tokens=100,model_id='qwen-fixture')
    kwargs=dict(system='offline stable logical request',user='same input',schema_name='fixture',schema={'type':'object'})
    with pytest.raises(GatewayCompletionError):runtime['client'].complete(**kwargs,config=config)
    before=(runtime['tmp']/'budget.json').read_bytes()
    runtime['mode']='ok'
    import dataclasses
    with pytest.raises(ProviderBudgetExhausted):
        runtime['client'].complete(**kwargs,config=dataclasses.replace(config,timeout_seconds=4))
    assert len(runtime['posts'])==1
    assert (runtime['tmp']/'budget.json').read_bytes()==before
