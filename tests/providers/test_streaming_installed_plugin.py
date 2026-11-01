"""Installed MCP and its real child worker; only the upstream network is fake."""
import json,os,queue,subprocess,sys,threading,time
from pathlib import Path
import pytest
from tests.providers.test_streaming_runtime import runtime

ROOT=Path(__file__).resolve().parents[2]
INSTALLED=Path('C:/Users/sunom/.codex/plugins/cache/personal/cgkn/0.2.0-rc.2+codex.20261001183500')


def test_installed_mcp_actual_worker_streaming_contract(runtime):
    from tests.test_cgkn_mcp_plugin import ready_draft
    from tests.test_general_requirement_compiler import proposal
    temp=runtime['tmp'];state=temp/'process-gateway';state.mkdir();support=temp/'bootstrap';support.mkdir()
    goal='Create a local calculator that adds two numbers.'
    stages=[]
    def produce(payload):
        prompt='\n'.join(x['content'] for x in payload['messages'])
        stages.append(prompt)
        if 'cgkn_probe' in prompt:
            sample={'cgkn_probe':'ok','goal':'x','capabilities':['y']}
            schema=(payload.get('response_format') or {}).get('json_schema',{}).get('schema',{})
            return json.dumps({k:v for k,v in sample.items() if not schema or k in schema.get('properties',{})})
        if 'Reply with exactly: pong' in prompt:return 'pong'
        if 'requirements_planning' in prompt:
            if not runtime.get('long_planning_scheduled'):
                runtime['next_stream_seconds']=91
                runtime['long_planning_scheduled']=True
            return json.dumps(proposal(goal,core=['add_numbers']))
        return '{}'  # Unknown fixture stage must fail the real contract, never fabricate PASS.
    runtime['produce']=produce
    (support/'sitecustomize.py').write_text('''import os,socket,sys
original=socket.socket.connect
def local(self,address):
    if address[0] not in ('127.0.0.1','::1','localhost'):raise OSError('OFFLINE_EXTERNAL_CONNECTION_REFUSED')
    return original(self,address)
socket.socket.connect=local
if os.environ.get('CGKN_OFFLINE_GATEWAY_SERVER')=='1':
    import json,ssl,httpx
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    from cgkn_provider_lab.models import ProviderConfig
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn.providers.network_transport import NetworkClients,Route
    ProviderConfigStore.load=lambda self:[ProviderConfig(p,p,os.environ['CGKN_OFFLINE_PROVIDER_URL'],p+'-fixture',secret_backend='environment',secret_ref='CGKN_SYNTHETIC_ONLY') for p in ('qwen','deepseek')]
    SecretManager.resolve=lambda self,p:'synthetic-offline'
    def load(cls,path,**kwargs):
        doc=json.load(open(path));guid=doc['transport_profiles'][doc['provider_bindings']['qwen']]['interface_guid']
        routes={p:Route(p,None,deadline=30,read=10,interface_guid=guid) for p in ('qwen','deepseek')}
        trust=ssl.create_default_context(cafile=os.environ['CGKN_OFFLINE_CA'])
        return cls(routes,{p:p for p in routes},version='OFFLINE_INSTALLED_MCP',transports={p:httpx.HTTPTransport(verify=trust,trust_env=False,retries=0) for p in routes},**kwargs)
    NetworkClients.load=classmethod(load)
''')
    profile=json.loads((ROOT/'config/domestic_application.json').read_text())
    profile.update(network_config=str(ROOT/'config/network_routes.json'),model_routing=str(ROOT/'config/provider_profiles/domestic_model_routing.json'),gateway_state_dir=str(state),gateway_python=sys.executable,auto_start_gateway=False)
    path=temp/'profile.json';path.write_text(json.dumps(profile))
    env=dict(os.environ);env.update(CGKN_APPLICATION_PROFILE=str(path),PYTHONPATH=str(support)+os.pathsep+str(ROOT),CGKN_PROVIDER_CACHE_MODE='off',CGKN_OFFLINE_PROVIDER_URL=runtime['upstream_url'],CGKN_OFFLINE_CA=runtime['cert_path'])
    # All inherited budgets are replaced with isolated synthetic ledger/limits.
    env.update(CGKN_PROVIDER_BUDGET_LEDGER=str(temp/'plugin-budget.json'),CGKN_PROVIDER_MAX_API_CALLS='20',CGKN_PROVIDER_MAX_INPUT_TOKENS='1000000',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='500000',CGKN_PROVIDER_MAX_ESTIMATED_COST='10',CGKN_PROVIDER_INPUT_COST_PER_MILLION='1',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='1')
    gateway_env={**env,'CGKN_OFFLINE_GATEWAY_SERVER':'1'}
    log=(temp/'gateway-process.log').open('w')
    gateway=subprocess.Popen([sys.executable,'-X','utf8','-m','scripts.domestic_gateway','serve','--config',str(ROOT/'config/network_routes.json'),'--state-dir',str(state)],cwd=ROOT,env=gateway_env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    plugin=None;worker_pid=None
    try:
        until=time.monotonic()+15
        while not (state/'session.json').exists() and gateway.poll() is None and time.monotonic()<until:time.sleep(.05)
        assert (state/'session.json').exists(),(temp/'gateway-process.log').read_text()
        config=json.loads((INSTALLED/'.mcp.json').read_text())['mcpServers']['cgkn']
        plugin=subprocess.Popen([config['command'],*config['args']],cwd=INSTALLED,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(temp/'mcp-stderr.log').open('w'),text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=queue.Queue()
        def reader():
            for line in plugin.stdout:output.put(line)
        threading.Thread(target=reader,daemon=True).start();next_id=0;receipts=[]
        def tool(name,args):
            nonlocal next_id
            next_id+=1;plugin.stdin.write(json.dumps(dict(jsonrpc='2.0',id=next_id,method='tools/call',params=dict(name=name,arguments=args)))+'\n');plugin.stdin.flush()
            row=json.loads(output.get(timeout=35));receipts.append(row)
            result=row['result'];assert not result.get('isError'),result
            return result.get('structuredContent') or json.loads(result['content'][0]['text'])
        project=temp/'plugin-project';project.mkdir();(project/'README.md').write_text('Offline fixture only')
        tool('cgkn_init',dict(project_root=str(project)))
        tool('cgkn_doctor',dict(project_root=str(project)))
        tool('cgkn_prepare',dict(project_root=str(project),goal=goal,gap='implementation',category='planning_gap'))
        tool('cgkn_seal_brief',dict(project_root=str(project),draft=ready_draft()))
        result=tool('cgkn_generate',dict(project_root=str(project),goal=goal,confirmation='RUN_REVIEWED_PROVIDER',provider_mode='live'))
        worker_pid=result.get('job',{}).get('process_id')
        job=project/'.cgkn/agent-kit/generation_job.json'
        until=time.monotonic()+300
        clocks=[];next_clock=0
        while time.monotonic()<until:
            doc=json.loads(job.read_text()) if job.exists() else {}
            if doc.get('job_id') and time.monotonic()>=next_clock:
                clocks.append(tool('cgkn_get_progress',dict(project_root=str(project),job_id=doc['job_id'])))
                next_clock=time.monotonic()+1
            if doc.get('state') not in ('STARTING','RUNNING','VALIDATING','PUBLISHING',''):break
            time.sleep(.1)
        tool('cgkn_status',dict(project_root=str(project)))
        assert runtime['posts'],'Installed worker did not reach streaming upstream'
        assert runtime.get('long_streams') and runtime['long_streams'][0]['seconds']>90
        assert any(c['elapsed_seconds']>85 and c['meaningful_event_count']>1 and c['status'] in ('GENERATING','IDLE_WAITING') for snapshot in clocks for c in snapshot['calls'])
        assert all(s['generation_posts']==0 for s in clocks)
        ledger=json.loads((temp/'plugin-budget.json').read_text())
        assert len(ledger['calls'])==len(runtime['posts'])
        assert all(p['stream'] for p in runtime['posts'])
        assert doc.get('state') == 'REWORK_BLOCKED', doc
        assert all(row.get('job_id') == doc['job_id'] and row.get('attempt_id') == doc['attempt_id'] for row in ledger['calls'])
        evidence=Path(os.environ.get('CGKN_STREAMING_EVIDENCE_DIR',temp/'evidence'));evidence.mkdir(parents=True,exist_ok=True)
        (evidence/'installed-worker-progress.json').write_text(json.dumps(dict(scope='INSTALLED_MCP_REAL_BACKGROUND_WORKER_FAKE_TLS',snapshots=clocks,post_count=len(runtime['posts']),ledger_call_count=len(ledger['calls'])),indent=2))
        (evidence/'installed-plugin.json').write_text(json.dumps(dict(scope='INSTALLED_MCP_REAL_WORKER_REAL_GATEWAY_FAKE_TLS_PROVIDER',full_business_success=False,job=doc,
            long_streams=runtime['long_streams'],requests=len(runtime['posts']),worker_pid=worker_pid,gateway_pid=gateway.pid,stages=stages,ledger=ledger,receipts=receipts),ensure_ascii=False,indent=2))
    finally:
        if worker_pid:
            import psutil
            try:
                worker=psutil.Process(worker_pid)
                if str(temp) in ' '.join(worker.cmdline()):worker.terminate();worker.wait(10)
            except psutil.NoSuchProcess:pass
        if plugin:
            plugin.stdin.close()
            try:plugin.wait(10)
            except subprocess.TimeoutExpired:plugin.terminate();plugin.wait(10)
        (state/'stop').touch()
        try:gateway.wait(10)
        except subprocess.TimeoutExpired:gateway.terminate();gateway.wait(10)
        log.close()
