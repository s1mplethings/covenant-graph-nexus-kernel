import dataclasses
import json
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from cgkn.providers.progress_clock import ProgressClock, read_progress
from cgkn.providers.streaming_sse import StreamLimits, sse_events, collect_chat_completions, MeaningfulProgressWatchdog
from cgkn.providers import ModelRoleConfig
from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityTree
from tests.qualification_support import probe_node as CapabilityNode, measurement_runner
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from tests.providers.test_streaming_runtime import runtime


def evidence(name, value):
    if os.environ.get('ITER119_EVIDENCE_DIR'):
        root=Path(os.environ['ITER119_EVIDENCE_DIR']);root.mkdir(parents=True,exist_ok=True)
        (root/(name+'.json')).write_text(json.dumps(value,indent=2),encoding='utf-8')


def make_clock(tmp_path, **kwargs):
    return ProgressClock(tmp_path,identity='sha256:original',call_id='original-call',
        job_id='job',attempt_id='attempt',provider='qwen',model='fixture',phase='PLANNING',**kwargs)


@pytest.mark.parametrize('duration',[86,301,3601,36001])
def test_long_progress_uses_same_events_without_total_timeout(tmp_path,duration):
    now=[0.0]
    clock=make_clock(tmp_path,monotonic=lambda:now[0],wall=lambda:100000+now[0])
    watch=MeaningfulProgressWatchdog(clock=lambda:now[0])
    watch.submitted();clock.observe({'phase':'submitted'})
    for sequence,t in enumerate(range(0,duration+1,30),1):
        now[0]=t;watch.progress(sequence)
        clock.observe({'meaningful_events':sequence,'text_bytes':sequence})
        assert clock.snapshot()['status']=='GENERATING'
        watch.check()
    clock.finish('COMPLETED')
    assert read_progress(tmp_path,'job',now=999999)['calls'][0]['status']=='COMPLETED'


def test_heartbeat_and_duplicate_delivery_do_not_refresh(tmp_path):
    delta=lambda s:json.dumps({'id':'same-request','model':'fixture','choices':[{'index':0,'delta':{'content':s}}]})
    wire=(f'id: 1\ndata: {delta("x")}\n\nid: 1\ndata: {delta("x")}\n\n'
          f'id: 2\ndata: {delta("x")}\n\n: pulse\n\ndata: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode()
    beats=[];events=list(sse_events(wire.splitlines(keepends=True),limits=StreamLimits(),on_heartbeat=lambda:beats.append(1)))
    seen=[];result=collect_chat_completions(events,on_progress=seen.append)
    assert result.text=='xx' and max(r['meaningful_events'] for r in seen)==2 and len(beats)==1
    now=[0.0];clock=make_clock(tmp_path,monotonic=lambda:now[0])
    clock.observe({'phase':'submitted'});clock.observe({'meaningful_events':1})
    now[0]=10;clock.observe({'phase':'heartbeat','heartbeat_count':100,'meaningful_events':1})
    assert clock.snapshot()['seconds_since_meaningful_output']==10
    assert clock.snapshot()['meaningful_event_count']==1
    clock.finish('UNKNOWN')


def test_query_death_session_change_and_terminal_are_readonly(tmp_path):
    clock=make_clock(tmp_path)
    clock.observe({'phase':'submitted'});clock.observe({'meaningful_events':1})
    clock._save()
    clock.finish('UNKNOWN')
    before=clock.path.read_bytes()
    for _ in range(10):assert read_progress(tmp_path,'job')['calls'][0]['status']=='UNKNOWN'
    assert clock.path.read_bytes()==before and not read_progress(tmp_path,'other')['found']
    row=json.loads(before);row.update(status='GENERATING',_pid=99999999)
    clock.path.write_text(json.dumps(row))
    before=clock.path.read_bytes()
    assert read_progress(tmp_path,'job')['calls'][0]['status']=='UNKNOWN'
    assert clock.path.read_bytes()==before


def test_gateway_replacement_and_slow_writer_are_observation_only(tmp_path,monkeypatch):
    import threading
    state=tmp_path/'gateway';state.mkdir()
    (state/'status.json').write_text(json.dumps({'session_id':'new','running':True}))
    clock=make_clock(tmp_path/'progress',gateway_state=state)
    clock.observe({'phase':'gateway_started','session_id':'old'})
    clock.observe({'phase':'submitted'})
    clock._save()
    assert read_progress(tmp_path/'progress','job',gateway_state=state)['calls'][0]['status']=='UNKNOWN'
    with clock.write_lock:
        assert str(state) not in clock.path.read_text()
    entered=threading.Event();release=threading.Event();save=clock._save
    def slow_save():
        entered.set();release.wait(2);save()
    monkeypatch.setattr(clock,'_save',slow_save)
    clock.observe({'meaningful_events':1});assert entered.wait(2)
    start=time.monotonic()
    for n in range(2,200):clock.observe({'meaningful_events':n,'reasoning_chars':n})
    assert time.monotonic()-start<.5
    release.set();clock.finish('UNKNOWN')


def test_canonical_adapter_uses_saved_concrete_role(runtime,monkeypatch):
    from cgkn.providers import canonical_gateway_adapter as adapter
    from cgkn.providers.gateway_client import GatewayCompletionClient
    from cgkn.providers import ProviderCompletion
    routing=json.loads(Path('config/provider_profiles/domestic_model_routing.json').read_text())
    routing['roles']['agent']['model_id']='qwen3.8-flash'
    path=runtime['tmp']/'routing.json';path.write_text(json.dumps(routing))
    monkeypatch.setattr('cgkn.providers.application_network.settings',lambda:{'model_routing':str(path)})
    calls=[]
    def complete(self,**kwargs):
        calls.append(kwargs);return ProviderCompletion('{}','fixture')
    monkeypatch.setattr(GatewayCompletionClient,'complete',complete)
    adapter.provider_text([{'role':'user','content':'planning'}],'qwen',90,max_tokens=100,
        stage='requirements_planning',client=runtime['client'])
    assert calls[0]['config'].model_id=='qwen3.8-flash'
    assert calls[0]['config'].model=='qwen'


def execute_pair(runtime, monkeypatch, name, parallel):
    root=runtime['tmp']/name
    monkeypatch.setenv('CGKN_MODEL_JOB_ID',name)
    monkeypatch.setenv('CGKN_MODEL_ATTEMPT_ID',name+'-attempt')
    monkeypatch.setenv('CGKN_PROGRESS_ROOT',str(root/'api-progress'))
    registry=ExecutorRegistry()
    class Work:
        def __init__(self,provider):
            self.provider=provider
            self.descriptor=ExecutorDescriptor(provider+'@1','bounded_llm',('*',))
        def execute(self,req):
            try:
                result=runtime['client'].complete(system='offline fixture',user=name+' '+self.provider,
                    schema_name='fixture',schema={'type':'object'},config=ModelRoleConfig('worker',self.provider,
                        max_output_tokens=100,model_id=self.provider+'-fixture'))
                return BlockExecutionResult(project_id=req.project_id,run_id=req.run_id,node_id=req.node_id,
                    attempt_id=req.attempt_id,executor_ref=req.executor_ref,status=BlockStatus.SUCCEEDED,
                    outputs={'result':json.loads(result.text)},usage=result.usage)
            except Exception as exc:
                return BlockExecutionResult(project_id=req.project_id,run_id=req.run_id,node_id=req.node_id,
                    attempt_id=req.attempt_id,executor_ref=req.executor_ref,status=BlockStatus.BLOCKED,
                    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,str(exc)))
    for p in ('qwen','deepseek'):registry.register(Work(p))
    nodes=tuple(CapabilityNode(p,capability_ref='stream@1',config={'executor_ref':p+'@1','parallel_safe':True}) for p in ('qwen','deepseek'))
    tree=CapabilityTree('two independent bounded tasks',nodes)
    runner=measurement_runner(registry,FileRunStore(root/'state'),
        {p:lambda out:out.get('result')=={'ok':True} for p in ('qwen','deepseek')},max_parallel=parallel)
    def run():return runner.run(project_id='p',run_id=name,tree=tree,dag=compile_tree(tree))
    return root,run


def test_tls_dag_parallel_clocks_and_sequential_comparison(runtime,monkeypatch):
    runtime.update(steps=8,step_delay=.18,mode='valid')
    for p,r in list(runtime['gateway'].network.routes.items()):
        runtime['gateway'].network.routes[p]=dataclasses.replace(r,first_response=3,progress=3)
    root,run=execute_pair(runtime,monkeypatch,'parallel',2)
    from tests.test_cgkn_mcp_plugin import load_server_module
    module=load_server_module();server=module.CGKNPluginServer(Path.cwd())
    project=runtime['tmp']/'project';project.mkdir()
    server.core.initialize_project(project,Path.cwd())
    progress_root=project/'.cgkn/agent-kit/api-progress'
    monkeypatch.setenv('CGKN_PROGRESS_ROOT',str(progress_root))
    import subprocess
    installed=Path('C:/Users/sunom/.codex/plugins/cache/personal/cgkn/0.2.0-rc.2+codex.20261001183500')
    config=json.loads((installed/'.mcp.json').read_text())['mcpServers']['cgkn']
    plugin=subprocess.Popen([config['command'],str(installed/'scripts/cgkn_mcp_server.py'),'--cgkn-root',str(Path.cwd())],
        cwd=installed,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def query():
        plugin.stdin.write(json.dumps(dict(id=1,method='tools/call',params=dict(name='cgkn_get_progress',
            arguments={'project_root':str(project),'job_id':'parallel'})))+'\n');plugin.stdin.flush()
        value=json.loads(plugin.stdout.readline())['result']
        assert not value.get('isError'),value
        return value['structuredContent']
    observations=[];start=time.time()
    try:
        with ThreadPoolExecutor(1) as pool:
            task=pool.submit(run)
            while not task.done():
                observations.append(query())
                time.sleep(.05)
            assert task.result().status=='SUCCEEDED'
    finally:
        plugin.stdin.close()
        try:plugin.wait(timeout=10)
        except subprocess.TimeoutExpired:plugin.terminate();plugin.wait(timeout=10)
    parallel_seconds=time.time()-start
    assert any(len(o['calls'])==2 and all(c['status']=='GENERATING' for c in o['calls']) for o in observations)
    for provider in ('qwen', 'deepseek'):
        samples=[c for o in observations for c in o['calls'] if c['provider']==provider]
        assert len({c['meaningful_event_count'] for c in samples})>1
        assert max(c['elapsed_seconds'] for c in samples)>min(c['elapsed_seconds'] for c in samples)
    final=read_progress(progress_root,'parallel')
    assert all(c['status']=='COMPLETED' and c['usage_complete'] for c in final['calls'])
    assert len({c['call_id'] for c in final['calls']})==2
    intervals=list(runtime['intervals']);a,b=intervals
    overlap=min(a['end'],b['end'])-max(a['start'],b['start']);assert overlap>0
    # Read current job through the actual MCP handler, never cgkn_status reconciliation.
    before=len(runtime['posts']);notices=[]
    response=module.handle(server,dict(id=1,method='tools/call',params=dict(name='cgkn_get_progress',
        arguments={'project_root':str(project),'job_id':'parallel'},_meta={'progressToken':'observe'})),notify=notices.append)
    assert len(runtime['posts'])==before and len(notices)==1
    assert response['result']['structuredContent']['generation_posts']==0
    root2,run2=execute_pair(runtime,monkeypatch,'sequential',1)
    start=time.time();assert run2().status=='SUCCEEDED';serial_seconds=time.time()-start
    assert len(runtime['posts'])==4
    ledger=json.loads((runtime['tmp']/'budget.json').read_text());assert len(ledger['calls'])==4
    assert all(c['status']=='SUCCEEDED' for c in ledger['calls'])
    evidence('parallel-test-results',dict(scope='OFFLINE_TLS_PRODUCTION_DAG',status='OFFLINE_PARALLEL_PASS',
        intervals=runtime['intervals'],overlap_seconds=overlap,parallel_seconds=parallel_seconds,
        sequential_seconds=serial_seconds,measured_ratio=serial_seconds/parallel_seconds,
        observations=observations,final=final,post_count=4,ledger_call_count=4))
    evidence('mcp-progress-demo',dict(response=response,notifications=notices))


def test_flash_payload_and_original_planning_contract(runtime,monkeypatch):
    from tests.test_general_requirement_compiler import proposal
    from scripts import canonical_goal_spec_compiler as compiler
    # Controlled output is explicitly fixture evidence, never Flash capability.
    value=proposal('Create a local calculator that adds two numbers.',core=['add_numbers'])
    runtime.update(text=json.dumps(value))
    runtime['gateway'].available_models['qwen'].add('qwen3.8-flash')
    result=runtime['client'].complete(system='Return PlanningProposal JSON',user='fixture planning',
        schema_name='PlanningProposal',schema=json.loads(Path('contracts/requirements_planning_proposal_v1.schema.json').read_text()),
        config=ModelRoleConfig('agent','qwen',max_output_tokens=2000,model_id='qwen3.8-flash'))
    assert json.loads(result.text)==value
    assert compiler.validate_planning_proposal(json.loads(result.text)) == []
    payload=runtime['posts'][0]
    assert payload['model']=='qwen3.8-flash' and payload['enable_thinking'] is False
    assert payload['stream'] and payload['max_completion_tokens']==2000
    assert payload['response_format']['type']=='json_schema'


@pytest.mark.parametrize('mode',['stalled','eof','heartbeat','http_error'])
def test_one_provider_failure_or_idle_does_not_block_other(runtime,monkeypatch,mode):
    runtime.update(mode_by_model={'qwen-fixture':mode})
    if mode=='stalled':
        import threading
        runtime['independent_finished']=threading.Event()
        for p,r in list(runtime['gateway'].network.routes.items()):
            runtime['gateway'].network.routes[p]=dataclasses.replace(r,progress=6,first_response=6)
    root,run=execute_pair(runtime,monkeypatch,mode,2)
    run()
    rows={r['provider']:r for r in read_progress(root/'api-progress',mode)['calls']}
    assert rows['deepseek']['status']=='COMPLETED'
    assert rows['qwen']['status']==('COMPLETED' if mode=='stalled' else 'UNKNOWN' if mode in ('eof','http_error') else 'STALLED')
    if mode=='stalled':assert rows['deepseek']['ended_unix']<rows['qwen']['ended_unix']
    if mode=='heartbeat':
        assert rows['qwen']['meaningful_event_count']==0
        assert rows['qwen']['heartbeat_count']>0
    assert len(runtime['posts'])==2
    evidence('isolation-'+mode,rows)


def test_observation_creation_failure_cannot_leave_reservation_open(runtime,monkeypatch):
    def fail(*args,**kwargs):raise OSError('synthetic disk error')
    monkeypatch.setattr('cgkn.providers.progress_clock.ProgressClock',fail)
    from cgkn.providers.gateway_client import GatewayCompletionError
    with pytest.raises(GatewayCompletionError):
        runtime['client'].complete(system='offline',user='disk fail',schema_name='fixture',schema=None,
            config=ModelRoleConfig('agent','qwen',max_output_tokens=100,model_id='qwen-fixture'))
    assert not runtime['posts']
    ledger=json.loads((runtime['tmp']/'budget.json').read_text())
    assert len(ledger['calls'])==1 and ledger['calls'][0]['status']=='CANCELLED_BEFORE_SEND'
