"""Real loopback TLS Provider -> bound pool -> Gateway SSE -> original DAG.

Only seeded repository fixtures are model-authored here; never production tasks.
"""
import dataclasses,datetime,hashlib,io,ipaddress,json,socket,ssl,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx,pytest
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.network_transport import NetworkClients,Route
from cgkn.providers.gateway_client import GatewayCompletionClient,GatewayCompletionError
from cgkn.providers.client import ModelRoleConfig
from tests.providers.stream_fixtures import upstream_wire


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from tests.providers.test_domestic_repair import admit
    profile=tmp_path/'legacy.json';profile.write_text('{"kind":"CGKNApplicationNetwork","mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(profile));monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','off')
    # Each TLS fixture owns its complete synthetic budget, including phase caps.
    for name in list(__import__('os').environ):
        if name.startswith('CGKN_PROVIDER_MAX_'):monkeypatch.delenv(name,raising=False)
    admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_API_CALLS='20',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='100000')
    connect=socket.socket.connect
    def only_local(sock,address):
        assert address[0] in ('127.0.0.1','::1','localhost'),'External connections forbidden'
        return connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',only_local)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'offline.local')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
        .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
    certpath=tmp_path/'cert.pem';keypath=tmp_path/'key.pem'
    certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    control=dict(posts=[],mode='ok',progress=[],delay=.02);events=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));control['posts'].append(payload)
            import uuid
            request_id = 'up-' + uuid.uuid4().hex
            interval = {'model':payload['model'], 'start':time.time(), 'end':None}
            control.setdefault('intervals', []).append(interval)
            if not control.get('baseline'):assert payload['stream'] and payload['stream_options']['include_usage']
            model=payload['model'];text=control.get('text','{"ok":true}')
            if control.get('produce'):text=control['produce'](payload)
            if control.get('baseline'):
                time.sleep(control['delay'])
                raw=json.dumps(dict(id='baseline-upstream',model=model,choices=[dict(message={'content':text},finish_reason='stop')],usage={'prompt_tokens':3,'completion_tokens':2})).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw);return
            wire=upstream_wire(model,text[1:],request_id)
            long_seconds=control.pop('next_stream_seconds',0)
            mode=control.get('mode_by_model',{}).get(model,control['mode'])
            if mode=='http_error':
                self.send_response(503);self.end_headers();interval['end']=time.time();return
            if mode=='slow_headers':time.sleep(.65)
            if mode=='eof':wire=wire.replace(b'data: [DONE]\n\n',b'')
            if mode=='length':wire=wire.replace(b'"stop"',b'"length"')
            if mode=='missing_usage':wire=upstream_wire(model,text[1:],request_id,usage={})
            if mode=='wrong_model':wire=upstream_wire('wrong-model',text[1:],request_id)
            if mode=='malformed':wire=b'data: {bad}\n\n'
            if mode=='tool':wire=b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{"}}]}}]}\n\n'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            try:
                if mode in ('heartbeat','total'):
                    for _ in range(30):self.wfile.write(b': alive\n\n');self.wfile.flush();time.sleep(.03)
                    return
                # A dispatched delta precedes terminal content; use actual socket flush.
                first=dict(id=request_id,model=model,choices=[dict(index=0,delta={'content':text[:1]},finish_reason=None)])
                self.wfile.write(('data: '+json.dumps(first)+'\n\n').encode());self.wfile.flush()
                if model=='qwen-fixture' and control.get('independent_finished'):
                    assert control['independent_finished'].wait(5)
                if control.get('steps') and mode=='valid':
                    for offset in range(1, control['steps']+1):
                        time.sleep(control.get('step_delay', .15))
                        delta=dict(id=request_id,model=model,choices=[dict(index=0,delta={'content':text[offset:offset+1]},finish_reason=None)])
                        self.wfile.write(('data: '+json.dumps(delta)+'\n\n').encode());self.wfile.flush()
                    wire=upstream_wire(model,text[control['steps']+1:],request_id)
                if long_seconds:
                    begin=time.monotonic();offset=1
                    while time.monotonic()-begin<long_seconds:
                        time.sleep(1)
                        delta=dict(id=first['id'],model=model,choices=[dict(index=0,delta={'content':text[offset:offset+1]},finish_reason=None)])
                        self.wfile.write(('data: '+json.dumps(delta)+'\n\n').encode());self.wfile.flush();offset+=1
                    wire=upstream_wire(model,text[offset:],first['id'])
                    control.setdefault('long_streams',[]).append(dict(seconds=time.monotonic()-begin,model=model,events=offset))
                delay=control.get('delay_by_model',{}).get(model,control['delay'])
                time.sleep(.65 if mode=='stalled' else delay);self.wfile.write(wire);self.wfile.flush()
            except OSError:pass
            finally:
                interval['end']=time.time()
                if model=='deepseek-fixture' and control.get('independent_finished'):
                    control['independent_finished'].set()
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(certpath,keypath)
    upstream.socket=tls.wrap_socket(upstream.socket,server_side=True)
    thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
    import sys
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    entries=[dataclasses.replace(p,base_url=f'https://127.0.0.1:{upstream.server_port}/v1',model=p.provider_id+'-fixture') for p in ProviderConfigStore().load() if p.provider_id in ('qwen','deepseek')]
    monkeypatch.setattr(ProviderConfigStore,'load',lambda self:entries)
    routes={p:Route(p,None,connect=1,read=.5,progress=.35,first_response=.4,deadline=2) for p in ('qwen','deepseek')}
    trust=ssl.create_default_context(cafile=str(certpath))
    network=NetworkClients(routes,{p:p for p in routes},version='ISOLATED_TLS',log=events.append,
        transports={p:httpx.HTTPTransport(verify=trust,trust_env=False,retries=0) for p in routes})
    class Secrets:
        def resolve(self,p):return 'synthetic-offline'
    gw=DomesticGateway('D:/cgkn-provider-api-lab',None,network=network,secret_manager=Secrets(),response_dir=tmp_path/'recovery')
    info=gw.start();client=GatewayCompletionClient(info.base_url,info.access_token).bind_run('streaming-isolated','streaming-test')
    control.update(gateway=gw,client=client,tmp=tmp_path,events=events,upstream_url=f'https://127.0.0.1:{upstream.server_port}/v1',cert_path=str(certpath))
    try:yield control
    finally:gw.close();upstream.shutdown();upstream.server_close();thread.join(2)


def call(runtime,**kwargs):
    return runtime['client'].complete(system='offline',user='fixture',schema_name='fixture',schema={'type':'object'},
        config=ModelRoleConfig('agent','qwen',timeout_seconds=3,max_output_tokens=100,model_id='qwen-fixture'),**kwargs)


@pytest.mark.parametrize('mode',['eof','length','missing_usage','wrong_model','malformed','tool','heartbeat'])
def test_invalid_tls_stream_never_persists_or_retries(runtime,mode):
    runtime['mode']=mode
    with pytest.raises(GatewayCompletionError) as exc:call(runtime)
    assert exc.value.outcome_unknown
    assert len(runtime['posts'])==1
    assert not list((runtime['tmp']/'recovery').rglob('*.json'))
    ledger=json.loads((runtime['tmp']/'budget.json').read_text())
    assert len(ledger['calls'])==1 and ledger['calls'][0]['status']=='INTERRUPTED_UNKNOWN'
    if mode=='heartbeat':
        # Either bounded watchdog can win; a downstream stall closes the peer
        # before the upstream watchdog, so verify the actual client error too.
        assert exc.value.category=='NO_INITIAL_MEANINGFUL_PROGRESS' or any(e.get('error_type')=='NO_INITIAL_MEANINGFUL_PROGRESS' for e in runtime['events'])


def test_stream_progress_crosses_actual_gateway_before_completion(runtime,monkeypatch):
    from cgkn.providers import gateway_stream
    original=gateway_stream.receive;seen=[]
    def observe(*args,**kwargs):
        kwargs.pop('on_progress',None)
        return original(*args,**kwargs,on_progress=lambda row:seen.append((time.monotonic(),row)))
    monkeypatch.setattr(gateway_stream,'receive',observe)
    runtime['delay']=.12
    result=call(runtime);end=time.monotonic()
    assert json.loads(result.text)=={'ok':True} and len(runtime['posts'])==1
    assert seen and end-seen[0][0]>.08
    ledger=json.loads((runtime['tmp']/'budget.json').read_text())
    assert ledger['calls'][0]['status']=='SUCCEEDED'
    identity=ledger['calls'][0]['request_identity']
    original=(runtime['tmp']/'budget.json').read_bytes()
    recovered=runtime['client'].recover_cached(request_identity=identity,schema={'type':'object'},cache_dir=runtime['tmp']/'recovery')
    assert recovered.text==result.text and recovered.attempts==0 and len(runtime['posts'])==1
    assert (runtime['tmp']/'budget.json').read_bytes()==original


@pytest.mark.parametrize('mode,kind',[('slow_headers','NO_INITIAL_MEANINGFUL_PROGRESS'),('stalled','NO_MEANINGFUL_PROGRESS')])
def test_transport_deadlines_bound_actual_blocking_reads(runtime,mode,kind):
    runtime['mode']=mode
    begin=time.monotonic()
    with pytest.raises(GatewayCompletionError) as exc:call(runtime)
    assert exc.value.outcome_unknown and time.monotonic()-begin<1
    assert len(runtime['posts'])==1
    # Either independent watchdog may win the race to close the socket.
    assert exc.value.category==kind or any(e.get('error_type')==kind for e in runtime['events'])


def test_parser_has_no_elapsed_generation_deadline():
    from cgkn.providers.streaming_sse import StreamLimits,sse_events,collect_chat_completions
    clock=[0.]
    def lines():
        clock[0]=36000.
        yield from upstream_wire('qwen-fixture','{}').splitlines(keepends=True)
    good=collect_chat_completions(sse_events(lines(),limits=StreamLimits()))
    assert good.text=='{}'


@pytest.mark.parametrize('admission',['missing','exhausted'])
def test_no_budget_zero_tls_generation_posts(runtime,monkeypatch,admission):
    from scripts.provider_api_budget import ProviderBudgetExhausted
    if admission=='missing':monkeypatch.delenv('CGKN_PROVIDER_BUDGET_LEDGER')
    else:monkeypatch.setenv('CGKN_PROVIDER_MAX_API_CALLS','0')
    with pytest.raises(ProviderBudgetExhausted):call(runtime)
    assert runtime['posts']==[]


def test_streaming_migration_cannot_evade_pre_stream_unknown(runtime):
    from scripts import provider_api_budget as budget
    payload=dict(model='qwen',input=[{'role':'system','content':'offline'},{'role':'user','content':'fixture'}],
        temperature=0.,max_output_tokens=100,text={'format':{'type':'json_schema','name':'fixture','strict':True,'schema':{'type':'object'}}},cgkn_model_id='qwen-fixture')
    old='sha256:'+hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    reservation=budget.reserve_call(case_id='old',purpose='PLANNING',model='qwen',request_identity=old,estimated_input_tokens=1,requested_output_tokens=100,retry_count=0)
    budget.mark_request_started(reservation);budget.finalize_call(reservation,usage=None,http_status=502,status='INTERRUPTED_UNKNOWN')
    before=(runtime['tmp']/'budget.json').read_bytes()
    with pytest.raises(budget.ProviderBudgetExhausted,match='ALREADY_UNKNOWN'):call(runtime)
    assert runtime['posts']==[] and (runtime['tmp']/'budget.json').read_bytes()==before


def test_completed_but_invalid_contract_is_not_cached_or_unknown(runtime):
    from cgkn.providers.recording import RecordedCompletionClient
    from cgkn.state import FileRunStore
    store=FileRunStore(runtime['tmp']/'recorded')
    runtime['client']=RecordedCompletionClient(runtime['client'],store,'p','r')
    runtime['text']='[]'
    with pytest.raises(GatewayCompletionError,match='schema_validation_failed') as exc:call(runtime)
    assert not exc.value.outcome_unknown
    completed=exc.value.completed_response
    assert completed['model']=='qwen-fixture' and completed['output_text']=='[]'
    error_record=json.loads(next((runtime['tmp']/'recorded').rglob('error.json')).read_text())
    assert error_record['completed_response']==completed
    row=json.loads((runtime['tmp']/'budget.json').read_text())['calls'][0]
    assert row['status']=='FAILED' and row['input_tokens']==3 and row['output_tokens']==2
    assert len(runtime['posts'])==1 and not list((runtime['tmp']/'recovery').rglob('*.json'))


def test_same_tls_fixture_before_after_measurements(runtime,monkeypatch):
    import importlib.util,sys,os
    from cgkn.providers import gateway_stream
    root=Path(__file__).resolve().parents[2]
    def load(name,file):
        spec=importlib.util.spec_from_file_location('cgkn.providers.'+name,root/'artifacts/streaming-first-20261029/baseline/cgkn/providers'/file)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module
    old_gateway=load('_baseline_gateway','domestic_gateway.py');old_client=load('_baseline_client','gateway_client.py')
    class Secrets:
        def resolve(self,p):return 'synthetic-offline'
    trust=ssl.create_default_context(cafile=runtime['cert_path'])
    network=NetworkClients({p:Route(p,None,read=1,deadline=2) for p in ('qwen','deepseek')},{p:p for p in ('qwen','deepseek')},version='BASELINE_FIXTURE',
        transports={p:httpx.HTTPTransport(verify=trust,trust_env=False,retries=0) for p in ('qwen','deepseek')})
    gateway=old_gateway.DomesticGateway('D:/cgkn-provider-api-lab',None,network=network,secret_manager=Secrets())
    runtime.update(baseline=True,delay=.15)
    try:
        info=gateway.start();client=old_client.GatewayCompletionClient(info.base_url,info.access_token)
        begin=time.monotonic();result=client.complete(system='baseline',user='same fixture',schema_name='x',schema={'type':'object'},config=ModelRoleConfig('agent','qwen',timeout_seconds=3,max_output_tokens=100))
        before=time.monotonic()-begin
    finally:gateway.close()
    runtime['baseline']=False;original=gateway_stream.receive;progress=[]
    monkeypatch.setattr(gateway_stream,'receive',lambda *a,**k:original(*a,**{x:y for x,y in k.items() if x!='on_progress'},on_progress=lambda row:progress.append((time.monotonic(),row))))
    begin=time.monotonic();after_result=call(runtime);after=time.monotonic()-begin
    assert after_result.text==result.text and len(runtime['posts'])==2 and any(row.get('text_bytes',0)>0 for _,row in progress)
    assert progress[0][0]-begin<after
    out=Path(os.environ.get('CGKN_STREAMING_EVIDENCE_DIR',runtime['tmp']/'evidence'));out.mkdir(parents=True,exist_ok=True)
    (out/'before-after-local-tls.json').write_text(json.dumps(dict(scope='SAME_LOCAL_TLS_SYNTHETIC_PROVIDER_NOT_REAL_MODEL_PERFORMANCE',
        configured_delay_seconds=.15,before=dict(first_controller_progress=None,completion_seconds=before,posts=1),
        after=dict(first_controller_progress=progress[0][0]-begin,completion_seconds=after,posts=1)),indent=2))


def test_original_agent_dag_worker_and_independent_acceptance_over_tls_sse(runtime):
    from tests.application.software_project.test_gateway_e2e import ProjectGateway,ROOT
    from cgkn.application.software_project.service import SoftwareProjectGenerationService
    from cgkn.application.software_project.contracts import ProjectResultStatus
    from cgkn.providers import CGKNModelRouting
    ProjectGateway.models=[];ProjectGateway.agent_calls=0
    def produce(payload):
        # Reuse the existing seeded fixture response corpus, not a new planner.
        provider='deepseek' if payload['model'].startswith('deepseek') else 'qwen'
        name='cgkn_scoped_project_worker' if provider=='deepseek' else 'cgkn_agent_decision'
        fake=object.__new__(ProjectGateway);fake.rfile=io.BytesIO(json.dumps(dict(model=provider,text={'format':{'name':name}})).encode())
        fake.headers={'Content-Length':len(fake.rfile.getvalue())};fake.wfile=io.BytesIO()
        fake.send_response=lambda *a:None;fake.send_header=lambda *a:None;fake.end_headers=lambda:None
        fake.do_POST()
        from cgkn.providers.streaming_sse import sse_events,StreamLimits
        events=list(sse_events(fake.wfile.getvalue().splitlines(keepends=True),limits=StreamLimits()))
        return json.loads(events[-1].data)['response']['output_text']
    runtime['produce']=produce
    routing=CGKNModelRouting.load(ROOT/'config/provider_profiles/gateway_model_routing.json')
    result=SoftwareProjectGenerationService(ROOT,runtime['tmp']/'artifacts',client=runtime['client'],routing=routing).run_case('seeded_repair',max_repair_rounds=0)
    assert result.status is ProjectResultStatus.PASS
    assert [r['model'] for r in runtime['posts']]==['qwen-fixture','deepseek-fixture','qwen-fixture']
    assert result.receipt['internal_test_result']=='PASS' and result.receipt['hidden_acceptance_result']=='PASS'
    ledger=json.loads((runtime['tmp']/'budget.json').read_text())
    assert len(ledger['calls'])==3 and all(c['status']=='SUCCEEDED' for c in ledger['calls'])
    assert len(list((runtime['tmp']/'recovery').rglob('*.json')))==3
