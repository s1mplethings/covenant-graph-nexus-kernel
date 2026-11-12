"""Targeted offline checks; all HTTP endpoints are loopback or MockTransport."""
import contextlib,json,os,sys,threading,time,socket,hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import Mock
import pytest
import httpx
from cgkn.providers import application_network as app
from cgkn.providers.gateway_client import completion_client_from_environment,GatewayCompletionError
from scripts import provider_api_budget as budget

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    original_connect=socket.socket.connect
    def loopback_only(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
            raise AssertionError('OFFLINE_ACCEPTANCE_REFUSES_NON_LOOPBACK_CONNECTION')
        return original_connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback_only)
    root=Path(__file__).resolve().parents[2];state=tmp_path/'state';state.mkdir()
    doc=dict(kind='CGKNApplicationNetwork',mode='domestic',network_config=str(root/'config/network_routes.json'),
        model_routing=str(root/'config/provider_profiles/domestic_model_routing.json'),gateway_state_dir=str(state),
        interface_guid='31fde520-1fc1-4a43-a5a9-8ca730ff5821',gateway_python=sys.executable,auto_start_gateway=False)
    profile=tmp_path/'profile.json';profile.write_text(json.dumps(doc))
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(profile));monkeypatch.delenv('CGKN_NETWORK_MODE',raising=False)
    for name in list(os.environ):
        if name.startswith('CGKN_PROVIDER_') and any(term in name for term in ('BUDGET','MAX_','COST_','CACHE')):monkeypatch.delenv(name,raising=False)
    return state,profile

def admit(monkeypatch,tmp_path,**changes):
    values=dict(CGKN_PROVIDER_BUDGET_LEDGER=str(tmp_path/'budget.json'),CGKN_PROVIDER_MAX_API_CALLS='5',
        CGKN_PROVIDER_MAX_INPUT_TOKENS='100000',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='10000',CGKN_PROVIDER_MAX_ESTIMATED_COST='2',
        CGKN_PROVIDER_INPUT_COST_PER_MILLION='1',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='1')
    values.update(changes)
    for key,value in values.items():monkeypatch.setenv(key,value)


@pytest.mark.happy_path
@pytest.mark.boundary
def test_historical_sender_delegates_to_actual_budgeted_gateway(fake_gateway,monkeypatch,tmp_path):
    from cgkn.providers.legacy_transport import post_json_once
    admit(monkeypatch,tmp_path)
    base=app.session(app.settings())[0]['base_url'].rstrip('/')
    document,error=post_json_once(base+'/responses',{'model':'qwen','messages':[{'role':'user','content':'Return answer'}],
        'max_tokens':100},'unused-compatibility-token',5)
    assert not error and document['output_text']=='{"answer":42}'
    assert len(fake_gateway[0])==1
    ledger=json.loads((tmp_path/'budget.json').read_text())
    assert len(ledger['calls'])==1


@pytest.mark.negative
@pytest.mark.boundary
def test_historical_sender_cannot_bypass_budget_with_credentials(fake_gateway,tmp_path):
    from cgkn.providers.legacy_transport import post_json_once
    with pytest.raises(budget.ProviderBudgetExhausted):
        post_json_once('https://unapproved.example/responses',{'model':'qwen','messages':[]},'dummy-credential',5)
    assert fake_gateway[0]==[]

@pytest.fixture
def fake_gateway(isolated,monkeypatch):
    state,_=isolated;requests=[];response={'mode':'ok','wire_sha256':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,doc):
            raw=json.dumps(doc).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.send(200,{'data':[{'id':'qwen'},{'id':'deepseek'}]})
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw);requests.append(body)
            response['wire_sha256'].append(hashlib.sha256(raw).hexdigest())
            if response['mode']=='nonjson':
                raw=b'<html>not json</html>';self.send_response(200)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            elif response['mode']=='unknown':self.send(502,{'error':{'type':'provider_outcome_unknown','message':'isolated unknown'}})
            else:
                from tests.providers.stream_fixtures import send_gateway
                send_gateway(self,body,dict(id='fake-response',model=body.get('cgkn_model_id') or body['model'],status='completed',output_text='{"answer":42}',usage={'input_tokens':4,'output_tokens':3}),session='isolated-session')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=app.settings();base=f'http://127.0.0.1:{server.server_port}/v1'
    status=dict(running=True,pid=1234,process_created_at=1,session_id='isolated-session',base_url=base,
                network_sha256=config['network_sha256'],interface_guid=config['interface_guid'])
    (state/'status.json').write_text(json.dumps(status));(state/'session.json').write_text(json.dumps(dict(status,access_token='dummy-loopback-only')))
    monkeypatch.setattr(app,'_instance_state',lambda *args:'ALIVE')
    try:yield requests,response
    finally:server.shutdown();server.server_close();thread.join(2)

def test_actual_canonical_adapter_uses_one_budget_owner(fake_gateway,isolated,monkeypatch,tmp_path):
    from scripts import run_local_pipeline_impl as impl
    requests,_=fake_gateway;admit(monkeypatch,tmp_path)
    raw=impl.provider_text([{'role':'user','content':'Return answer'}],'qwen',5,stage='component_file_generation',max_tokens=100)
    assert json.loads(raw)=={'answer':42}
    assert len(requests)==1 and requests[0]['model']=='qwen'
    ledger=json.loads((tmp_path/'budget.json').read_text())
    assert len(ledger['calls'])==1 and ledger['totals']['api_calls']==1

def test_formal_command_wrapper_reaches_actual_adapter(fake_gateway,isolated,monkeypatch,tmp_path):
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'tools/cgkn-agent-kit/src'))
    from cgkn_agent_kit import core
    from scripts import run_codex_conversation_generation as cli,run_local_pipeline_impl as impl
    project=tmp_path/'project';project.mkdir();(project/'.cgkn').mkdir()
    (project/'.cgkn/agent-kit.json').write_text(json.dumps(dict(kind='CGKNAgentKitProject',schema_version='1.0',cgkn_root=str(root),artifact_dir='.cgkn/agent-kit')))
    admit(monkeypatch,tmp_path)
    seen=[]
    def boundary(project_root,**kwargs):
        raw=impl.provider_text([{'role':'user','content':'offline real adapter'}],kwargs['model'],5,max_tokens=100,stage='component_file_generation')
        seen.append(json.loads(raw))
        return dict(status='OFFLINE_WIRING_ONLY',formal_evidence_status='NOT_EVALUATED')
    monkeypatch.setattr(cli.codex_conversation,'run_formal_generation_once',boundary)
    argv=core.generation_command(project,goal='offline',brief_path=tmp_path/'brief.json')
    Path(argv[argv.index('--result')+1]).parent.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(sys,'argv',argv[1:])
    assert cli.main()==0
    assert seen==[{'answer':42}] and len(fake_gateway[0])==1
    assert 'run_codex_conversation_generation.py' in argv[1]

@pytest.mark.parametrize('admission',['budgeted','none','exhausted'])
def test_unmodified_formal_controller_reaches_budgeted_provider(fake_gateway,isolated,monkeypatch,tmp_path,admission):
    """No dispatcher substitute: intentionally invalid model output must not pass."""
    from tests.test_cgkn_mcp_plugin import load_server_module,ready_draft
    from scripts import run_codex_conversation_generation as cli
    root=Path(__file__).resolve().parents[2]
    server=load_server_module().CGKNPluginServer(root)
    project=tmp_path/'formal-project';project.mkdir();(project/'README.md').write_text('Offline fixture only')
    server.initialize(dict(project_root=str(project)))
    server.prepare(dict(project_root=str(project),goal='Create an offline tested sample',gap='Need implementation',category='planning_gap'))
    server.seal_brief(dict(project_root=str(project),draft=ready_draft()))
    from tests.session_authority_support import authorization
    goal='Create an offline tested sample'
    consumer=tmp_path/'independent.py';consumer.write_text("raise SystemExit('NO_VALID_IMPLEMENTATION')\n")
    profile={'kind':'CGKNProjectSessionProfile','schema_version':'1.0','project_id':'formal-fixture','run_id':'one',
        'workspace':str(tmp_path/'candidate'),'intent':{'overall_goal':goal,'user_visible_outcomes':['tested module'],
            'constraints':['offline fixture'],'forbidden_operations':['publication'],
            'delivery_expectations':['validated module'],'major_acceptance_categories':['correctness']},
        'requirements':{'R':{'must':True,'checker_keys':['independent']}},
        'independent_consumer':{'path':str(consumer),'sha256':hashlib.sha256(consumer.read_bytes()).hexdigest(),'public_fields':['value']},
        'execution_authorization':authorization('formal-fixture',('code.implement@1','project.acceptance.external@1'),goal)}
    (project/'.cgkn/project-session.json').write_text(json.dumps(profile))
    if admission=='budgeted':admit(monkeypatch,tmp_path)
    elif admission=='exhausted':admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_API_CALLS='0')
    argv=server.core.generation_command(project,goal='Create an offline tested sample',
        brief_path=project/'.cgkn/agent-kit/codex_capability_brief.json')
    monkeypatch.setattr(sys,'argv',argv[1:])
    expected=GatewayCompletionError if admission=='budgeted' else budget.ProviderBudgetExhausted
    with pytest.raises(expected):cli.main()
    assert 1<=len(fake_gateway[0])<=5 if admission=='budgeted' else len(fake_gateway[0])==0
    assert all(row['model'] in ('qwen','deepseek') for row in fake_gateway[0])
    ledger=json.loads((tmp_path/'budget.json').read_text()) if (tmp_path/'budget.json').exists() else {'calls':[]}
    assert len(ledger['calls'])==len(fake_gateway[0])
    assert [row['request_identity'] for row in ledger['calls']]==['sha256:'+value for value in fake_gateway[1]['wire_sha256']]
    assert not Path(argv[argv.index('--result')+1]).exists()
    errors=list((project/'.cgkn/agent-kit/project_sessions/formal-fixture/one/provider_calls').glob('*/error.json'))
    assert errors
    result=json.loads(errors[-1].read_text(encoding='utf-8'))
    assert result['error_type']==expected.__name__
    assert result.get('status') not in ('PASS','DELIVERED','SUCCEEDED')
    evidence=os.environ.get('CGKN_ACCEPTANCE_EVIDENCE_DIR')
    if evidence:
        target=Path(evidence);target.mkdir(parents=True,exist_ok=True)
        files=['scripts/run_codex_conversation_generation.py','scripts/codex_conversation.py',
            'scripts/run_local_pipeline_impl.py','cgkn/providers/canonical_gateway_adapter.py','cgkn/providers/gateway_client.py']
        record=dict(scope='UNMODIFIED_FORMAL_CONTROLLER_LOOPBACK_FAKE_GATEWAY_ONLY',
            controller_substituted=False,task_status_forged=False,admission=admission,cli_argv=argv,
            gateway_post_count=len(fake_gateway[0]),real_model_generations=0,external_connections_allowed=False,
            task_result_status=result.get('status'),contract_admission_passed=False,
            payload_summaries=[dict(model=row['model'],summary_sha256=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest(),
                wire_sha256=wire,budget_request_identity='sha256:'+wire) for row,wire in zip(fake_gateway[0],fake_gateway[1]['wire_sha256'])],
            synthetic_ledger=ledger,source_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files})
        (target/('formal-controller-'+admission+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')

@pytest.mark.parametrize('admission',['missing','exhausted'])
def test_canonical_no_budget_no_post(fake_gateway,isolated,monkeypatch,tmp_path,admission):
    from scripts import run_local_pipeline_impl as impl
    if admission=='exhausted':admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_API_CALLS='0')
    with pytest.raises(budget.ProviderBudgetExhausted):
        impl.provider_text([{'role':'user','content':'no paid authorization'}],'qwen',5,max_tokens=100)
    assert fake_gateway[0]==[]

def test_unknown_canonical_result_never_repeats(fake_gateway,isolated,monkeypatch,tmp_path):
    from scripts import run_local_pipeline_impl as impl
    admit(monkeypatch,tmp_path);fake_gateway[1]['mode']='unknown'
    args=([{'role':'user','content':'unique unknown request'}],'qwen',5)
    with pytest.raises(GatewayCompletionError) as error:impl.provider_text(*args,max_tokens=100)
    assert error.value.outcome_unknown
    with pytest.raises(budget.ProviderBudgetExhausted):impl.provider_text(*args,max_tokens=100)
    assert len(fake_gateway[0])==1
    fake_gateway[1]['mode']='ok'
    impl.provider_text([{'role':'user','content':'a distinct legitimate request'}],'qwen',5,max_tokens=100)
    ledger=json.loads((tmp_path/'budget.json').read_text())
    assert len(fake_gateway[0])==2 and ledger['calls'][0]['submission_outcome_unknown']
    assert ledger['calls'][1]['status']=='SUCCEEDED'

def test_planning_compatibility_post_is_budgeted(fake_gateway,isolated,monkeypatch,tmp_path):
    from scripts import check_connectivity
    admit(monkeypatch,tmp_path)
    state,_=isolated;base=json.loads((state/'session.json').read_text())['base_url']
    doc,error=check_connectivity._post_json(base+'/responses',{'model':'qwen','messages':[{'role':'user','content':'plan'}],'max_tokens':100},'unused-token',5)
    assert not error and doc['cgkn_transport']=='BUDGETED_GATEWAY'
    assert len(fake_gateway[0])==1

def test_legacy_external_endpoint_is_not_silently_accepted(fake_gateway,isolated,monkeypatch,tmp_path):
    from scripts import check_connectivity
    admit(monkeypatch,tmp_path)
    with pytest.raises(RuntimeError,match='OLD_ENDPOINT_REFUSED'):
        check_connectivity._post_json('https://unapproved.invalid/v1/responses',{'model':'qwen','input':'no'},'unused',5)
    assert not fake_gateway[0]

@pytest.mark.parametrize('stage,provider,purpose',[
    ('requirements_planning','qwen','PLANNING'),('component_file_generation','qwen','GENERATION'),
    ('semantic_repair','qwen','REPAIR'),('lightweight_summary','deepseek','GENERATION')])
def test_saved_roles_and_stage_budgets(fake_gateway,isolated,monkeypatch,tmp_path,stage,provider,purpose):
    from scripts import run_local_pipeline_impl as impl
    admit(monkeypatch,tmp_path)
    impl.provider_text([{'role':'user','content':'short bounded request'}],'surrogate-stage',5,stage=stage,max_tokens=100)
    assert fake_gateway[0][0]['model']==provider
    assert json.loads((tmp_path/'budget.json').read_text())['calls'][0]['purpose']==purpose

def test_bad_profile_never_breaks_local_core_import(isolated,monkeypatch):
    state,profile=isolated;profile.write_text('{bad')
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/cgkn-agent-kit/src'))
    from cgkn_agent_kit import core
    assert core._application_network_status()['state']=='CONFIG_ERROR'
    assert core.APPLICATION_NETWORK_STATUS is None
    with pytest.raises(RuntimeError,match='CONFIG_MISMATCH'):completion_client_from_environment()

def test_alive_unreachable_never_restarts(isolated,monkeypatch):
    config=app.settings();state,_=isolated
    status=dict(running=True,pid=99,process_created_at=1,session_id='alive',base_url='http://127.0.0.1:1/v1',network_sha256=config['network_sha256'],interface_guid=config['interface_guid'])
    (state/'status.json').write_text(json.dumps(status));(state/'session.json').write_text(json.dumps(dict(status,access_token='synthetic-token')))
    monkeypatch.setattr(app,'_instance_state',lambda *args:'ALIVE');start=Mock();monkeypatch.setattr(app,'_start',start)
    with pytest.raises(RuntimeError,match='TEMPORARILY_UNREACHABLE'):app.session(config)
    start.assert_not_called()

def test_pid_reuse_and_access_denied_are_distinguished(isolated,monkeypatch):
    config=app.settings();status=dict(pid=10,process_created_at=1)
    monkeypatch.setattr(app,'process_identity',lambda pid:dict(state='ALIVE',created_at=2,executable='other'))
    assert app._instance_state(status,config)=='OLD_INSTANCE_EXITED_PID_REUSED'
    monkeypatch.setattr(app,'process_identity',lambda pid:dict(state='UNKNOWN'))
    assert app._instance_state(status,config)=='UNKNOWN'
