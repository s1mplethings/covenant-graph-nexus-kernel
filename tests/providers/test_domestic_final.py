"""Final acceptance safety tests: local sockets/processes, zero model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import httpx
import pytest

from scripts import provider_api_budget as budget
from cgkn.providers.windows_interface import validate_snapshot

GUID='31fde520-1fc1-4a43-a5a9-8ca730ff5821'

def prepare_fixture(root):
    from scripts import domestic_task_acceptance as acceptance
    root.parent.mkdir(parents=True,exist_ok=True)
    oracle=root.parent/'independent_add.py'
    oracle.write_text('import runpy,sys\nmodule=runpy.run_path(sys.argv[1])\nassert module["add"](-2,5)==3\n')
    return acceptance.prepare(root,oracle=oracle)


@pytest.fixture(autouse=True)
def isolate_acceptance_budget_environment(monkeypatch,tmp_path):
    profile=tmp_path/"legacy.json";profile.write_text('{"mode":"legacy"}')
    monkeypatch.setenv("CGKN_APPLICATION_PROFILE",str(profile))
    # The CLI intentionally configures its own process; unit calls must not leak
    # that opt-in cache/budget into unrelated Gateway tests in the same pytest.
    names={'CGKN_PROVIDER_BUDGET_LEDGER','CGKN_PROVIDER_MAX_API_CALLS','CGKN_PROVIDER_MAX_PLANNING_CALLS',
        'CGKN_PROVIDER_MAX_GENERATION_CALLS','CGKN_PROVIDER_MAX_INPUT_TOKENS','CGKN_PROVIDER_MAX_OUTPUT_TOKENS',
        'CGKN_PROVIDER_MAX_ESTIMATED_COST','CGKN_PROVIDER_INPUT_COST_PER_MILLION','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION',
        'CGKN_PROVIDER_CACHE_MODE','CGKN_PROVIDER_RESPONSE_CACHE_DIR'}
    for key in names:monkeypatch.setenv(key,os.environ.get(key,''))


def configure(monkeypatch,root):
    values={'CGKN_PROVIDER_BUDGET_LEDGER':str(root/'ledger.json'),'CGKN_PROVIDER_MAX_API_CALLS':'5',
        'CGKN_PROVIDER_MAX_INPUT_TOKENS':'100000','CGKN_PROVIDER_MAX_OUTPUT_TOKENS':'10000',
        'CGKN_PROVIDER_MAX_ESTIMATED_COST':'2','CGKN_PROVIDER_INPUT_COST_PER_MILLION':'20',
        'CGKN_PROVIDER_OUTPUT_COST_PER_MILLION':'60','CGKN_PROVIDER_CACHE_MODE':'off'}
    for k,v in values.items():monkeypatch.setenv(k,v)


@pytest.mark.parametrize('usage_first',[True,False])
def test_unknown_submission_latch_survives_late_usage_and_reconciliation(tmp_path,monkeypatch,usage_first):
    configure(monkeypatch,tmp_path)
    args=dict(case_id='synthetic',purpose='planning',model='qwen',request_identity='same-fixed-identity',estimated_input_tokens=20,requested_output_tokens=10,retry_count=0,run_id='same-run')
    reservation=budget.reserve_call(**args);budget.mark_request_started(reservation)
    known=lambda:budget.finalize_call(reservation,usage={'prompt_tokens':8,'completion_tokens':4},http_status=200,status='FAILED')
    unknown=lambda:budget.finalize_call(reservation,usage=None,http_status=None,status='INTERRUPTED_UNKNOWN')
    if usage_first:known();unknown()
    else:unknown();known()
    row=json.loads((tmp_path/'ledger.json').read_text())['calls'][0]
    assert row['status']=='INTERRUPTED_UNKNOWN' and row['submission_outcome_unknown']
    assert row['input_tokens']==8 and row['output_tokens']==4
    with pytest.raises(budget.ProviderBudgetExhausted,match='ALREADY_UNKNOWN'):budget.reserve_call(**args)


@pytest.mark.parametrize('mode',['unknown','completed_cache'])
def test_local_gateway_reopen_in_new_process_never_resubmits(tmp_path,monkeypatch,mode):
    configure(monkeypatch,tmp_path)
    if mode=='completed_cache':
        monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','read_write')
        monkeypatch.setenv('CGKN_PROVIDER_RESPONSE_CACHE_DIR',str(tmp_path/'responses'))
    hits=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            hits.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if mode=='unknown':
                # A real incomplete connection, not the removed generation total timer.
                self.close_connection=True
                return
            raw=json.dumps({'id':'synthetic-upstream','model':'qwen','status':'completed','output_text':'{"ok":true}','usage':{'input_tokens':8,'output_tokens':4}}).encode()
            try:
                from tests.providers.stream_fixtures import send_gateway
                send_gateway(self,hits[-1],json.loads(raw))
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    code="""import json
from cgkn.providers.gateway_client import GatewayCompletionClient,GatewayCompletionError
from cgkn.providers import ModelRoleConfig
from scripts.provider_api_budget import ProviderBudgetExhausted
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from pathlib import Path
from tests.providers.authority_fixtures import authorized_transport
scopes=ExitStack()
scopes.enter_context(authorized_transport(Path(scopes.enter_context(TemporaryDirectory())),calls=1))
c=GatewayCompletionClient('http://127.0.0.1:PORT','synthetic-local-token',run_id='fixed-run',case_id='reopen')
try:
 r=c.complete(system='fixed',user='fixed-run-decision-1',schema_name='fixed',schema={'type':'object'},config=ModelRoleConfig('agent','qwen',timeout_seconds=1,max_output_tokens=32))
 print(json.dumps({'result':'COMPLETED','attempts':r.attempts,'usage':dict(r.usage)}))
except GatewayCompletionError as e:print(json.dumps({'result':e.category,'unknown':e.outcome_unknown}))
except ProviderBudgetExhausted:print(json.dumps({'result':'BLOCKED_IDENTITY'}))
scopes.close()
""".replace('PORT',str(server.server_port))
    try:
        def run():
            p=subprocess.run([sys.executable,'-X','utf8','-c',code],capture_output=True,text=True,timeout=10)
            assert p.returncode==0,p.stderr
            return json.loads(p.stdout)
        first=run();second=run()
        assert len(hits)==1
        if mode=='unknown':
            assert first=={'result':'outcome_unknown','unknown':True}
            assert second['result']=='BLOCKED_IDENTITY'
        else:
            assert first['attempts']==1 and second['attempts']==0
            assert first['usage']==second['usage']
        (tmp_path/'cross-process-evidence.json').write_text(json.dumps({'scope':'LOCAL_SYNTHETIC_GATEWAY_ZERO_MODEL_CALLS','first':first,'second':second,'server_posts':len(hits)},indent=2))
    finally:server.shutdown();server.server_close()


@pytest.mark.boundary
@pytest.mark.happy_path
def test_stable_guid_recognizes_new_index_and_dhcp_address():
    base=dict(guid=GUID,index=14,status='Up',hardware=True,addresses=['192.168.1.100'],name='WLAN')
    assert validate_snapshot(GUID,base)['index']==14
    current=validate_snapshot(GUID,{**base,'index':28,'addresses':['192.168.1.123'],'name':'renamed-WLAN'})
    assert current['index']==28 and current['source']=='192.168.1.123'
    for changed in [dict(status='Disconnected'),dict(hardware=False),dict(addresses=[]),dict(addresses=['192.168.1.1','192.168.1.2']),dict(guid='00000000-0000-0000-0000-000000000000')]:
        with pytest.raises(ValueError):validate_snapshot(GUID,{**base,**changed})


@pytest.mark.skipif(os.name!='nt',reason='Windows bound transport')
@pytest.mark.boundary
@pytest.mark.negative
def test_changed_binding_stops_before_dns_or_any_request(monkeypatch):
    from cgkn.providers.direct_transport import PhysicalDirectTransport
    from cgkn.providers import windows_interface
    transport=PhysicalDirectTransport(interface_index=14,local_address='192.168.1.100',dns_servers=['119.29.29.29'],allowed_hosts=['api.deepseek.com'],interface_guid=GUID)
    monkeypatch.setattr(windows_interface,'resolve_interface',lambda guid:dict(index=28,source='192.168.1.123'))
    monkeypatch.setattr(transport.resolver,'resolve',lambda *a:pytest.fail('must stop before DNS'))
    try:
        with pytest.raises(httpx.ConnectError,match='RESTART_GATEWAY'):transport.handle_request(httpx.Request('GET','https://api.deepseek.com/v1/models'))
    finally:transport.close()


@pytest.mark.skipif(not Path('D:/cgkn-provider-api-lab/src').exists(),reason='existing Lab dependency')
def test_gateway_records_upstream_identity_instead_of_config_alias():
    from cgkn.providers.domestic_gateway import DomesticGateway
    from cgkn.providers.network_transport import NetworkClients,Route
    events=[]
    def handler(req):
        from tests.providers.stream_fixtures import upstream_wire
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=upstream_wire('actual-model-from-upstream','{"ok":true}'))

    network=NetworkClients({'q':Route('q',None),'d':Route('d',None)}, {'qwen':'q','deepseek':'d'},version='LOCAL_SYNTHETIC',transports={r:httpx.MockTransport(handler) for r in ['q','d']})
    class Secrets:
        def resolve(self,p):return 'synthetic-never-log-this'
    gateway=DomesticGateway('D:/cgkn-provider-api-lab','unused',network=network,secret_manager=Secrets(),log=events.append)
    try:
        from cgkn_provider_lab.gateway import GatewayError
        with pytest.raises(GatewayError,match='unknown'):
            gateway.application.invoke({'model':'qwen','input':'Return JSON'},'responses')
        assert 'synthetic-never-log-this' not in json.dumps(events)
    finally:gateway.close()


def test_prepared_task_runs_through_real_runtime_and_reopens_without_model_calls(tmp_path,monkeypatch):
    """Synthetic decisions only: proves harness mechanics, never real task success."""
    from scripts import domestic_task_acceptance as acceptance
    from cgkn.providers import ProviderCompletion
    root=tmp_path/'run';prepare_fixture(root)
    plan=json.loads((root/'plan.json').read_text())
    from tests.session_authority_support import authorization
    auth=authorization(acceptance.PROJECT_ID,tuple(acceptance.CATALOG),acceptance.GOAL,calls=3)
    monkeypatch.setattr(acceptance,'validate_authorization',lambda *a:(plan,{'max_cost_cny':2,'execution_authorization':auth}))
    calls=[]
    class FakeGateway:
        def __init__(self,*args,**kwargs):pass
        def start(self):
            from types import SimpleNamespace
            return SimpleNamespace(base_url='http://127.0.0.1:1',access_token='dummy-not-live')
        def close(self):pass
    class FakeClient:
        def __init__(self,*args,**kwargs):pass
        def complete(self,**kwargs):
            config=kwargs['config'];calls.append(config.model)
            if config.role=='worker':
                value=dict(schema_version='1.0',node_id='fix',summary='synthetic fixture repair',
                    actions=[dict(action='write_file',path='math_utils.py',content='def add(a: int, b: int) -> int:\n    return a + b\n')],
                    expected_outputs=['math_utils.py'],confidence=1,needs_escalation=False,escalation_reason='')
            else:
                number=json.loads(kwargs['user'])['decision_number'];edits=[]
                if number==1:
                    for name,ref,deps in [('inspect','repo.inspect@1',[]),('fix','code.modify@1',['inspect']),('test','test.python@1',['fix'])]:
                        edits.append(dict(edit_id=name,operation='add_node',node_id=name,payload=dict(capability_ref=ref,parent_id='',depends_on=deps,config=acceptance.CATALOG[ref]),provenance={'actor':'synthetic-test-agent'}))
                value=dict(schema_version='1.0',decision_id='synthetic-'+str(number),summary='synthetic',reason='local harness only',edits=edits,
                    request_run=number==1,finish=number==2,needs_escalation=False,escalation_reason='')
                value['decision_audit']={'alternatives_considered':['inspect','repair','verify'],
                    'expected_outcome':'Independent arithmetic verification','capability_claim':{
                        'target_capability_id':'code.modify@1','target_gap_id':'code.modify@1',
                        'strategy_capabilities':list(acceptance.CATALOG)}}
            return ProviderCompletion(json.dumps(value),'synthetic-model','synthetic-id',{'prompt_tokens':1,'completion_tokens':1},1)
    monkeypatch.setattr(acceptance,'DomesticGateway',FakeGateway);monkeypatch.setattr(acceptance,'GatewayCompletionClient',FakeClient)
    assert acceptance.execute(root,'never-read',phase='execute')['state']=='PAUSED_BEFORE_FINAL_AGENT_DECISION'
    assert calls==['qwen','deepseek']
    assert acceptance.execute(root,'never-read',phase='finish')['state']=='FINISHED'
    assert calls==['qwen','deepseek','qwen']
    assert acceptance.reopen(root)['state']=='PASS'
    assert calls==['qwen','deepseek','qwen']
    assert not (root/'budget-ledger.json').exists()  # not actual Provider calls


def test_tampered_fixture_cannot_be_attributed_to_a_future_model_run(tmp_path):
    from scripts import domestic_task_acceptance as acceptance
    prepare_fixture(tmp_path/'run');root=tmp_path/'run';plan=json.loads((root/'plan.json').read_text())
    (root/'project/math_utils.py').write_text('def add(a,b): return a+b\n')
    with pytest.raises(ValueError,match='SEALED_FIXTURE'):acceptance.verify_fixture(root,plan,unmodified_project=True)


def test_candidate_safety_precedes_pytest_but_does_not_judge_correctness():
    from scripts.domestic_task_acceptance import validate_pure_candidate
    validate_pure_candidate('def add(a:int,b:int)->int:\n return a-b\n')
    validate_pure_candidate('def add(a,b):\n return 5\n')
    for source in ['import os\ndef add(a,b): return a+b','def add(a,b): return __import__("os").getcwd()','def add(a,b): return eval("a+b")']:
        with pytest.raises(ValueError):validate_pure_candidate(source)
