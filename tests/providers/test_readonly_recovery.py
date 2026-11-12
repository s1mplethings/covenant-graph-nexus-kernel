"""Offline-only recovery and original Agent contract; no business candidate."""
import dataclasses,hashlib,json,threading
from pathlib import Path
import httpx,pytest
import socket
from cgkn.providers.gateway_client import GatewayCompletionClient,GatewayCompletionError
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.network_transport import NetworkClients,Route
from cgkn.providers.client import ModelRoleConfig
from cgkn.providers.recording import RecordedCompletionClient
from cgkn.state import FileRunStore
from cgkn.agent.composer import AgentComposer,AgentDecisionContext,AGENT_SCHEMA,parse_agent_decision
from cgkn.orchestration.capability_tree import CapabilityTree
from scripts import provider_api_budget as budget

DECISION=dict(schema_version='1.0',decision_id='offline-contract-only',summary='fixture',reason='fixture',
    edits=[],request_run=False,finish=False,needs_escalation=True,escalation_reason='offline fixture')

@pytest.fixture
def live_path(tmp_path,monkeypatch):
    connect=socket.socket.connect
    def loopback_only(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
            pytest.fail('Offline recovery tests refuse non-loopback connection')
        return connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback_only)
    legacy=tmp_path/'legacy.json';legacy.write_text('{"kind":"CGKNApplicationNetwork","mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(legacy))
    monkeypatch.delenv('CGKN_NETWORK_MODE',raising=False)
    from tests.providers.test_domestic_repair import admit
    admit(monkeypatch,tmp_path)
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','off')
    control={'mode':'ok','posts':0};events=[]
    def upstream(request):
        control['posts']+=1
        trace=request.extensions['trace']
        trace('http11.send_request_headers.started',{'request':request})
        trace('http11.send_request_headers.complete',{'request':request})
        if control['mode']=='timeout':raise httpx.ReadTimeout('must-not-log-this')
        if control['mode']=='unknown_status':return httpx.Response(502,json={'error':'synthetic'})
        if control['mode']=='partial':
            class Partial(httpx.SyncByteStream):
                def __iter__(self):
                    yield b'{"partial":'
                    raise httpx.ReadTimeout('must-not-log-this')
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Partial())
        row=dict(id='offline-upstream',model=models['qwen'],choices=[dict(index=0,delta=dict(content=json.dumps(DECISION)),finish_reason='stop')],usage=dict(prompt_tokens=3,completion_tokens=5,total_tokens=8))
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=('data: '+json.dumps(row)+'\n\ndata: [DONE]\n\n').encode())
    routes={p:Route(route_id=p,proxy_url=None,read=1,deadline=2) for p in ('qwen','deepseek')}
    network=NetworkClients(routes,{p:p for p in routes},version='OFFLINE',transports={p:httpx.MockTransport(upstream) for p in routes},log=events.append)
    class Secrets:
        def resolve(self,provider):return 'synthetic-only'
    # This transport fixture must not depend on the user's live default tier.
    # Max admission has its own positive/negative controls; UNKNOWN recovery
    # needs a concrete offline model that actually reaches the mock transport.
    import sys
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    configured=ProviderConfigStore().load()
    monkeypatch.setattr(ProviderConfigStore,'load',lambda self:[
        dataclasses.replace(p,model=p.provider_id+'-fixture') for p in configured])
    gw=DomesticGateway('D:/cgkn-provider-api-lab',None,network=network,secret_manager=Secrets(),response_dir=tmp_path/'recovery')
    from cgkn.providers.route_diagnostics import install
    install(gw,read_only=False)
    models={p.provider_id:p.model for p in gw.providers}
    info=gw.start();client=GatewayCompletionClient(info.base_url,info.access_token).bind_run('offline-run','offline-case')
    config=ModelRoleConfig('agent','qwen',max_output_tokens=100,timeout_seconds=4,model_id=models['qwen'])
    try:yield client,config,control,events,tmp_path
    finally:gw.close()

@pytest.mark.parametrize('mode',['timeout','partial','unknown_status'])
def test_submitted_failure_never_repeats_across_recorded_controller_reopen(live_path,mode):
    client,config,control,events,tmp=live_path;control['mode']=mode
    store=FileRunStore(tmp/'state');recorded=RecordedCompletionClient(client,store,'p','r')
    kwargs=dict(system='bounded',user='same original request',schema_name='agent',schema=AGENT_SCHEMA,config=config)
    with pytest.raises(GatewayCompletionError) as first:recorded.complete(**kwargs)
    assert first.value.outcome_unknown
    ledger=json.loads((tmp/'budget.json').read_text());before=(tmp/'budget.json').read_bytes()
    assert ledger['calls'][0]['status']=='INTERRUPTED_UNKNOWN'
    with pytest.raises(GatewayCompletionError,match='prior_submission_unknown'):
        RecordedCompletionClient(client,store,'p','r').complete(**kwargs)
    with pytest.raises(GatewayCompletionError,match='prior_submission_unknown'):
        RecordedCompletionClient(client,store,'p','r').complete(**{**kwargs,'config':dataclasses.replace(config,timeout_seconds=5,model_id='different-offline-model')})
    assert control['posts']==1 and (tmp/'budget.json').read_bytes()==before
    assert len(list(recorded.root.glob('*/request.json')))==1
    assert client.recover_cached(request_identity=ledger['calls'][0]['request_identity'],schema=AGENT_SCHEMA,cache_dir=tmp/'recovery') is None
    assert control['posts']==1
    if mode!='unknown_status':
        failure=next(e for e in events if e.get('phase')=='transport_failure')
        assert failure['submitted'] and ('ReadTimeout' in failure['exception_types'])
        assert failure['partial']==(mode=='partial')
        assert 'must-not-log-this' not in json.dumps(events)
        assert any(e.get('gateway_http_status')==502 and e.get('error_type')=='provider_outcome_unknown' for e in events)

def test_normal_response_and_readonly_hit_return_to_original_planning_contract(live_path,monkeypatch):
    client,config,control,events,tmp=live_path
    context=AgentDecisionContext('p','r','offline test',1,CapabilityTree('offline test',()),(),{}, {}, {})
    decision=AgentComposer(client,config).decide(context)
    assert decision.decision_id==DECISION['decision_id'] and decision.needs_escalation
    ledger=json.loads((tmp/'budget.json').read_text());identity=ledger['calls'][0]['request_identity'];before=(tmp/'budget.json').read_bytes()
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',lambda *a,**k:pytest.fail('Read-only recovery must never dial'))
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(tmp/'does-not-exist.json'))
    completion=client.recover_cached(request_identity=identity,schema=AGENT_SCHEMA,cache_dir=tmp/'recovery')
    restored=parse_agent_decision(json.loads(completion.text),completion,json.dumps(context.as_dict(),ensure_ascii=False,sort_keys=True))
    assert restored.decision_id==decision.decision_id and completion.attempts==0
    assert control['posts']==1 and (tmp/'budget.json').read_bytes()==before
    begin=next(e for e in events if e.get('phase')=='transport_begin')
    assert begin['client_request_identity']==identity and begin['timeouts']['read']==185
    assert begin['timeouts']['total_remaining'] is None
    assert begin['timeouts']['first_response']==180 and begin['timeouts']['progress']==120
    assert begin['client_call_id']==ledger['calls'][0]['call_id'] and begin['client_run_id']=='offline-run'
    assert any(e.get('phase')=='upstream_headers' and e.get('upstream_http_status')==200 for e in events)
    assert any(e.get('phase')=='model_progress' for e in events)
    assert any(e.get('phase')=='gateway_response_persisted' for e in events)
    assert any(e.get('phase')=='local_response_write_completed' and e['client_request_identity']==identity for e in events)

@pytest.mark.parametrize('mode',['miss','incomplete','usage_only','wrong_identity','invalid_contract','no_completion_marker','too_large'])
def test_readonly_miss_or_incomplete_never_submits(tmp_path,monkeypatch,mode):
    client=GatewayCompletionClient('http://127.0.0.1:1','unused-read-only')
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',lambda *a,**k:pytest.fail('No network permitted'))
    identity='a'*64;path=tmp_path/identity[:2]/(identity+'.json')
    if mode!='miss':
        path.parent.mkdir()
        response=dict(status='completed',output_text=json.dumps(DECISION),usage={'input_tokens':1})
        if mode=='incomplete':response['status']='incomplete'
        if mode=='no_completion_marker':response.pop('status')
        if mode=='usage_only':response.pop('output_text')
        if mode=='invalid_contract':response['output_text']='{}'
        if mode=='too_large':response['output_text']='x'*2097152
        path.write_text(json.dumps(dict(request_identity='b'*64 if mode=='wrong_identity' else identity,call_mode='CACHE_REPLAY',response=response)))
    if mode=='miss':assert client.recover_cached(request_identity=identity,schema=AGENT_SCHEMA,cache_dir=tmp_path) is None
    else:
        with pytest.raises(GatewayCompletionError):client.recover_cached(request_identity=identity,schema=AGENT_SCHEMA,cache_dir=tmp_path)

def test_replay_only_mode_miss_also_refuses_live_submission(live_path,monkeypatch):
    client,config,control,_,tmp=live_path
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','replay_only')
    monkeypatch.setenv('CGKN_PROVIDER_RESPONSE_CACHE_DIR',str(tmp/'absent-cache'))
    with pytest.raises(GatewayCompletionError,match='cache_miss'):
        client.complete(system='s',user='u',schema_name='agent',schema=AGENT_SCHEMA,config=config)
    assert control['posts']==0 and not (tmp/'budget.json').exists()
