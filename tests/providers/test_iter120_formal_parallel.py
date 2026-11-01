"""Installed MCP -> original background worker/DAG -> Gateway -> TWO TLS servers.

All child sockets are restricted to loopback. Bootstrap injects synthetic secrets,
TLS trust and explicit fault conditions only; no replacement scheduler or client.
"""
import json,os,queue,ssl,subprocess,sys,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from experiments.api_acceptance import iter119_pair as pair
from tests.providers.test_streaming_runtime import runtime
from tests.providers.stream_fixtures import upstream_wire

ROOT=pair.ROOT
OUT=ROOT/'artifacts/provider-parallel-final-20261029'
INSTALLED=Path('C:/Users/sunom/.codex/plugins/cache/personal/cgkn/0.2.0-rc.2+codex.20261001183500')

BOOTSTRAP=r'''
import os,socket,sys,json,time,threading
original=socket.socket.connect
def local(self,address):
    if address[0] not in ('127.0.0.1','::1','localhost'):raise OSError('OFFLINE_EXTERNAL_CONNECTION_REFUSED')
    return original(self,address)
socket.socket.connect=local
def case():return json.load(open(os.environ['CGKN_OFFLINE_CASE']))
if os.environ.get('CGKN_OFFLINE_GATEWAY_SERVER')=='1':
    import ssl,httpx
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    from cgkn_provider_lab.models import ProviderConfig
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn.providers.network_transport import NetworkClients,Route,REQUEST_CONTEXT
    urls=json.loads(os.environ['CGKN_OFFLINE_URLS'])
    ProviderConfigStore.load=lambda self:[ProviderConfig(p,p,urls[p],'qwen3.8-flash' if p=='qwen' else 'deepseek-flash',secret_backend='environment',secret_ref='CGKN_SYNTHETIC_ONLY') for p in urls]
    SecretManager.resolve=lambda self,p:'synthetic-offline'
    def load(cls,path,**kwargs):
        doc=json.load(open(path));guid=doc['transport_profiles'][doc['provider_bindings']['qwen']]['interface_guid']
        routes={p:Route(p,None,deadline=300,read=180,progress=120,first_response=180,interface_guid=guid) for p in urls}
        trust=ssl.create_default_context(cafile=os.environ['CGKN_OFFLINE_CA'])
        class Prepared(httpx.HTTPTransport):
            def __init__(self,p):super().__init__(verify=trust,trust_env=False,retries=0);self.provider=p
            def handle_request(self,request):
                delay=case().get('prep',{}).get(self.provider,0)
                if delay:
                    network.emit(dict(phase='fixture_connection_prepare_begin',provider=self.provider))
                    time.sleep(delay)
                    network.emit(dict(phase='fixture_connection_prepare_end',provider=self.provider))
                return super().handle_request(request)
        network=cls(routes,{p:p for p in routes},version='OFFLINE_ITER120',transports={p:Prepared(p) for p in urls},**kwargs)
        return network
    NetworkClients.load=classmethod(load)
else:
    from cgkn.runtime import DAGRunner
    runner_init=DAGRunner.__init__
    def measured_serial(self,*args,**kwargs):
        if case().get('serial'):kwargs['max_parallel']=1
        return runner_init(self,*args,**kwargs)
    DAGRunner.__init__=measured_serial
    # Explicit failure injections exercise the real budget check / cancel input.
    from scripts import provider_api_budget
    reserve=provider_api_budget.reserve_call
    def limited(**kwargs):
        if case().get('budget')==kwargs.get('provider'):kwargs['requested_output_tokens']=10000000
        return reserve(**kwargs)
    provider_api_budget.reserve_call=limited
    from cgkn.providers.gateway_client import GatewayCompletionClient
    complete=GatewayCompletionClient.complete
    def cancellable(self,**kwargs):
        if case().get('cancel')==kwargs['config'].model:
            event=threading.Event();kwargs['cancel']=event
            threading.Timer(.8,event.set).start()
        return complete(self,**kwargs)
    GatewayCompletionClient.complete=cancellable
'''

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2),encoding='utf-8')

def test_formal_installed_parallel_matrix(runtime):
    from tests.test_general_requirement_compiler import proposal
    temp=runtime['tmp'];support=temp/'bootstrap';support.mkdir()
    (support/'sitecustomize.py').write_text(BOOTSTRAP,encoding='utf-8')
    casefile=temp/'case.json';write(casefile,{})
    state=temp/'gateway';state.mkdir()
    control={'posts':[],'case':{}}
    textq=json.dumps(proposal('Create a local calculator that adds two numbers and displays the sum.',core=['add_numbers']))
    texts={'qwen':textq,'deepseek':'{"status":"ok","result":42,"check":"19+23=42"}'}
    if os.environ.get('CGKN_ITER120_NEW_PLAN'):
        texts['deepseek']=json.dumps(dict(signature='normalize_intervals(intervals)',implementation='def normalize_intervals(intervals):\n    return []',
            tests=[dict(name=str(i),input='[]',expected='[]') for i in range(6)],complexity='fixture only',boundary_notes='Synthetic schema witness, not implementation correctness evidence'))
    servers=[];threads=[];urls={}
    def handler(provider):
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                spec=dict(control['case']);mode=spec.get('fault',{}).get(provider)
                record=dict(provider=provider,case=spec['name'],at=time.time(),peer=self.client_address,model=payload['model'])
                control['posts'].append(record)
                if mode=='503':
                    self.send_response(503);self.send_header('Content-Length','0');self.end_headers();return
                text=texts[provider];count=12;rid='offline-'+uuid.uuid4().hex
                pieces=[text[i*len(text)//count:(i+1)*len(text)//count] for i in range(count)]
                wires=[('data: '+json.dumps(dict(id=rid,model=payload['model'],choices=[dict(index=0,delta={'content':s},finish_reason=None)]))+'\n\n').encode() for s in pieces]
                wires.append(upstream_wire(payload['model'],'',rid))
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(sum(map(len,wires))));self.end_headers()
                duration=spec.get('duration',{}).get(provider,2.4)
                try:
                    for i,wire in enumerate(wires):
                        self.wfile.write(wire);self.wfile.flush()
                        if mode=='eof' and i==2:self.close_connection=True;return
                        if mode=='stall' and i==0:
                            # Real wall-clock >120 seconds; heartbeat never renews meaningful progress.
                            for _ in range(124):
                                time.sleep(1);self.wfile.write(b': heartbeat\n\n');self.wfile.flush()
                            return
                        if i<count:time.sleep(duration/count)
                except OSError:self.close_connection=True
                finally:record['end']=time.time()
        return Handler
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(runtime['cert_path'],str(temp/'key.pem'))
    for p in ('qwen','deepseek'):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(p));server.daemon_threads=True
        server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        servers.append(server);threads.append(thread);urls[p]=f'https://127.0.0.1:{server.server_port}/v1'
    profile=json.loads((ROOT/'config/domestic_application.json').read_text())
    profile.update(network_config=str(ROOT/'config/network_routes.json'),model_routing=str(ROOT/'config/provider_profiles/domestic_model_routing.json'),gateway_state_dir=str(state),gateway_python=sys.executable,auto_start_gateway=False)
    profilepath=temp/'profile.json';write(profilepath,profile)
    env={**os.environ,'CGKN_APPLICATION_PROFILE':str(profilepath),'PYTHONPATH':str(support)+os.pathsep+str(ROOT),
        'CGKN_OFFLINE_URLS':json.dumps(urls),'CGKN_OFFLINE_CA':runtime['cert_path'],'CGKN_OFFLINE_CASE':str(casefile)}
    gatewaylog=(temp/'gateway.log').open('w');mcplog=(temp/'mcp.log').open('w')
    gateway=subprocess.Popen([sys.executable,'-X','utf8','-m','scripts.domestic_gateway','serve','--config',str(ROOT/'config/network_routes.json'),'--state-dir',str(state)],cwd=ROOT,env={**env,'CGKN_OFFLINE_GATEWAY_SERVER':'1'},stdout=gatewaylog,stderr=gatewaylog,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    plugin=None;results=[]
    evidence=OUT/('formal-'+str(time.time_ns()));evidence.mkdir(parents=True)
    try:
        until=time.monotonic()+20
        while not (state/'session.json').exists() and gateway.poll() is None and time.monotonic()<until:time.sleep(.05)
        assert (state/'session.json').exists(),(temp/'gateway.log').read_text()
        config=json.loads((INSTALLED/'.mcp.json').read_text())['mcpServers']['cgkn']
        plugin=subprocess.Popen([config['command'],*config['args']],cwd=INSTALLED,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=mcplog,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=queue.Queue();receipts=[];counter=0
        def reader():
            for line in plugin.stdout:output.put(line)
        threading.Thread(target=reader,daemon=True).start()
        def tool(name,args):
            nonlocal counter
            counter+=1;begin=time.monotonic()
            plugin.stdin.write(json.dumps(dict(jsonrpc='2.0',id=counter,method='tools/call',params=dict(name=name,arguments=args)))+'\n');plugin.stdin.flush()
            row=json.loads(output.get(timeout=35));receipts.append(dict(tool=name,seconds=time.monotonic()-begin,response=row))
            result=row['result'];assert not result.get('isError'),result
            return result.get('structuredContent') or json.loads(result['content'][0]['text'])
        cases=[dict(name='cold-near-simultaneous'),dict(name='reuse-near-simultaneous'),
            dict(name='qwen-slow-prepare',prep={'qwen':1}),dict(name='deepseek-slow-prepare',prep={'deepseek':1}),
            dict(name='qwen-long',duration={'qwen':4,'deepseek':1.5}),dict(name='deepseek-long',duration={'deepseek':4,'qwen':1.5}),
            dict(name='qwen-503',fault={'qwen':'503'}),dict(name='deepseek-eof',fault={'deepseek':'eof'}),
            dict(name='qwen-budget',budget='qwen'),dict(name='qwen-cancel',cancel='qwen'),
            dict(name='measured-serial-baseline',serial=True),dict(name='qwen-stall-120',fault={'qwen':'stall'})]
        if os.environ.get('CGKN_ITER120_QUICK'):cases=cases[:2]
        for spec in cases:
            control['case']=spec;write(casefile,spec)
            run=evidence/spec['name'];run.mkdir();project=run/'project';project.mkdir()
            plan=pair.read(pair.ROOT/'artifacts/api-progress-clock-20261029/live-authorized-01/plan.json')
            if os.environ.get('CGKN_ITER120_NEW_PLAN'):plan=pair.read(OUT/'live-plan-pending/plan.json')
            write(run/'plan.json',plan);write(run/'pricing.json',dict(scope='SYNTHETIC_OFFLINE_NO_CHARGE'))
            write(run/'authorization.json',dict(authorized=True,scope='LOOPBACK_FAKE_PROVIDERS_ONLY',max_posts=2,max_cny=plan['max_cny'],
                plan_sha256=pair.digest(run/'plan.json'),pricing_sha256=pair.digest(run/'pricing.json'),pricing_verified_unix=time.time(),
                source_sha256={'experiments/api_acceptance/iter119_pair.py':pair.digest(Path(pair.__file__))},gateway_session_id=pair.read(state/'session.json')['session_id']))
            tool('cgkn_init',dict(project_root=str(project)))
            launched=tool('cgkn_verify_api_pair',dict(project_root=str(project),confirmation='RUN_AUTHORIZED_API_PAIR'))
            write(run/'mcp-start.json',launched)
            jobpath=project/'.cgkn/agent-kit/generation_job.json'
            clocks=[];until=time.monotonic()+150;begin=time.monotonic()
            while time.monotonic()<until:
                doc=pair.read(jobpath)
                clocks.append(tool('cgkn_get_progress',dict(project_root=str(project),job_id=doc['job_id'],attempt_id=doc['attempt_id'])))
                if doc['state'] not in ('STARTING','RUNNING','VALIDATING','PUBLISHING'):break
                time.sleep(.12)
            wall=time.monotonic()-begin
            write(run/'progress-observations.json',clocks)
            events=[json.loads(line) for line in (state/'generation-events.jsonl').read_text().splitlines()]
            events=[e for e in events if e.get('client_job_id')==doc['job_id']]
            write(run/'gateway-events.json',events)
            ledger=pair.read(run/'budget.json');posts=[p for p in control['posts'] if p['case']==spec['name']]
            write(run/'tls-posts.json',posts)
            intervals={}
            for provider in ('qwen','deepseek'):
                pe=[e for e in events if e.get('provider')==provider]
                sends=[e['monotonic_ns']/1e9 for e in pe if e.get('phase')=='provider_submitted']
                ends=[e['monotonic_ns']/1e9 for e in pe if e.get('phase')=='attempt_end']
                meaningful=[e['monotonic_ns']/1e9 for e in pe if e.get('phase')=='model_progress' and e.get('meaningful_events',0)>0]
                if sends and ends:intervals[provider]=dict(start=min(sends),end=max(ends),first=min(meaningful) if meaningful else None,last=max(meaningful) if meaningful else None)
            overlap=max(0,min(i['end'] for i in intervals.values())-max(i['start'] for i in intervals.values())) if len(intervals)==2 else 0
            failed=spec.get('fault') or spec.get('budget') or spec.get('cancel')
            row=dict(case=spec,job=doc,wall_seconds=wall,intervals=intervals,http_overlap_seconds=overlap,
                sequential_http_service_sum_seconds=sum(i['end']-i['start'] for i in intervals.values()),
                ledger_calls=len(ledger['calls']),tls_posts=len(posts),progress_queries=len(clocks),status='PENDING')
            results.append(row);write(evidence/'matrix.json',results)
            assert doc['state']==('REWORK_BLOCKED' if failed else 'COMPLETE'),doc
            assert len(posts)==(1 if spec.get('budget') else 2)
            assert all(s['generation_posts']==0 for s in clocks)
            assert all(c['job_id']==doc['job_id'] and c['attempt_id']==doc['attempt_id'] for s in clocks for c in s['calls'])
            assert all(c['job_id']==doc['job_id'] and c['attempt_id']==doc['attempt_id'] for c in ledger['calls'])
            assert all(e['client_attempt_id']==doc['attempt_id'] for e in events)
            assert all(e['client_call_id'] in {c['call_id'] for c in ledger['calls']} for e in events)
            if spec['name']=='reuse-near-simultaneous':
                assert not any(e['phase']=='connection.connect_tcp.started' for e in events)
            if spec.get('prep'):
                slow=next(iter(spec['prep']));other='deepseek' if slow=='qwen' else 'qwen'
                done=next(e['monotonic_ns']/1e9 for e in events if e['phase']=='fixture_connection_prepare_end')
                assert intervals[other]['start']<done
            if spec.get('fault',{}).get('qwen')=='stall':
                stalled=next(c for c in clocks[-1]['calls'] if c['provider']=='qwen')
                assert stalled['status']=='STALLED' and stalled['meaningful_event_count']==1
                assert stalled['seconds_since_meaningful_output']>=120
            if not failed:
                assert overlap==0 if spec.get('serial') else overlap>.5,row
                assert len(clocks[-1]['calls'])==2
                assert all(c['status']=='COMPLETED' and c['usage_complete'] for c in clocks[-1]['calls'])
                assert all(pair.read(run/(p+'-result.json'))['status']=='PASS' for p in ('qwen','deepseek'))
                if not spec.get('serial'):
                    assert any(len([c for c in s['calls'] if c['meaningful_event_count']>1 and c['status'] not in ('COMPLETED','UNKNOWN')])==2 for s in clocks)
            else:
                other='qwen' if spec.get('fault',{}).get('deepseek') else 'deepseek'
                assert pair.read(run/(other+'-result.json'))['status']=='PASS'
            row['status']='PASS';write(evidence/'matrix.json',results)
        write(evidence/'mcp-transcript.json',receipts)
        write(evidence/'environment.json',dict(installed_mcp_sha256=pair.digest(INSTALLED/'scripts/cgkn_mcp_server.py'),gateway_pid=gateway.pid,tls_urls=urls,real_provider_posts=0,loopback_only=True))
    finally:
        write(evidence/'matrix.json',results)
        if plugin:
            plugin.stdin.close()
            try:plugin.wait(10)
            except subprocess.TimeoutExpired:plugin.terminate();plugin.wait(10)
        (state/'stop').touch()
        try:gateway.wait(10)
        except subprocess.TimeoutExpired:gateway.terminate();gateway.wait(10)
        gatewaylog.close();mcplog.close()
        for name in ('gateway.log','mcp.log'):(evidence/name).write_text((temp/name).read_text())
        for server in servers:server.shutdown();server.server_close()
