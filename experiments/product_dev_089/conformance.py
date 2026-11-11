"""No model, no product credit: real runner and container fault probes."""
import json
from pathlib import Path
from unittest.mock import patch
from cgkn.providers import ProviderCompletion
from experiments.diagnostic_088.offline import no_provider
from .runner import run_route
from .isolation import ContainerBoundary, Policy, verify_audit

ROOT=Path('F:/CGKN-ITER-089')
IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'

class Scripted:
    is_replay=True
    def __init__(self,rows):self.rows=iter(rows);self.calls=0;self.contexts=[]
    def complete(self,**kw):
        self.contexts.append(json.loads(kw['user']));self.calls+=1
        row=next(self.rows)
        return ProviderCompletion(row if isinstance(row,str) else json.dumps(row),'HARNESS_ONLY','fixed',{})

def direct(action):return {'done':False,'action':action}
def cmd(script,timeout=15):return {'action':'command','argv':['python','-c',script],'timeout_seconds':timeout}
def edit(i,op,node,payload):return dict(edit_id=i,operation=op,node_id=node,payload=payload,provenance={'source':'synthetic probe'})
def decision(edits,finish=False):return dict(schema_version='1.0',decision_id='probe',summary='probe',reason='probe',edits=edits,request_run=not finish,finish=finish,needs_escalation=False,escalation_reason='')

def main():
    out=ROOT/'conformance-v1';out.mkdir(exist_ok=False);rows=[]
    private=out/'private-canary.txt';private.write_text('SYNTHETIC_PRIVATE')
    probe="""import pathlib,subprocess,sqlite3,os
p=pathlib.Path('/workspace/probe.txt');p.write_text('persisted')
c=sqlite3.connect('/workspace/probe.db');c.execute('create table if not exists t(v)');c.execute('insert into t values(1)');c.commit();c.close()
assert pathlib.Path('/input/probe.txt').read_text()=='PUBLIC'
assert not pathlib.Path(PRIVATE).exists()
try:pathlib.Path('/input/probe.txt').write_text('bad');raise AssertionError('readonly bypass')
except PermissionError:pass
os.symlink(PRIVATE,'/workspace/link')
assert not pathlib.Path('/workspace/link').exists()
assert subprocess.run(['python','-c','print(123)'],capture_output=True).stdout.strip()==b'123'
assert subprocess.run(['ffmpeg','-version'],capture_output=True).returncode==0
assert pathlib.Path('/opt/asr/ggml-tiny.en.bin').is_file()
print('LEGAL_AND_DENIED_PASS')
""".replace('PRIVATE',repr(str(private)))
    hang="import subprocess,time; subprocess.Popen(['python','-c',\"import time,pathlib;time.sleep(5);pathlib.Path('/workspace/leaked').write_text('BAD')\"]); print('BEFORE_TIMEOUT',flush=True);time.sleep(60)"
    verify="import pathlib,sqlite3,time;time.sleep(5);assert not pathlib.Path('/workspace/leaked').exists();assert pathlib.Path('/workspace/probe.txt').read_text()=='persisted';assert sqlite3.connect('/workspace/probe.db').execute('select count(*) from t').fetchone()[0]==1;print('RECOVERY_PASS')"
    server="import subprocess; f=open('/workspace/server.log','w');subprocess.Popen(['python','-m','http.server','5000','--bind','127.0.0.1','--directory','/workspace'],stdout=f,stderr=f,start_new_session=True);print('LAUNCHED')"
    with no_provider(ROOT/'forbidden-provider.jsonl'):
        client=Scripted([direct(cmd(probe)),direct(cmd(hang,2)),direct(cmd(verify)),direct(cmd(server)),direct({'action':'browser','url':'http://127.0.0.1:5000/probe.txt','javascript':'document.body.innerText','wait_seconds':1}),{'done':True,'action':{}}])
        b,r=run_route(root=out/'direct',run_id='diag089-direct',route='R_DIRECT',image=IMAGE,client=client,goal='Generic infrastructure probe',public_files={'probe.txt':'PUBLIC'},mode='HARNESS_CONFORMANCE_ONLY')
        assert r['result']['status']=='SUBMITTED',r
        history=client.contexts[-1]['history'];assert history[1]['tool_result']['status']=='TIMEOUT_ENV_RECREATED'
        assert 'RECOVERY_PASS' in history[2]['tool_result']['stdout']
        assert 'persisted' in history[4]['tool_result']['stdout']
        rows.append({'route':'R_DIRECT','receipt':r,'audit':verify_audit(b.audit_path),'checks':['legal read/write/subprocess/media','readonly and synthetic private denial','timeout kills descendant','persistent data survives recreation','background service/browser reachable']})
        old=Path('F:/CGKN-ITER-088/dev-pair-v1/dev088-video-cgnk/provider')
        raw=[json.loads((old/f'call-{i:03}.response.json').read_text())['choices'][0]['message']['content'] for i in [1,2]]
        correction=decision([edit('fix','update_config','n_read_task',{'config':{'executor_ref':'local.file@1'}}),edit('new','add_node','probe',{'capability_ref':'workspace.command@1','parent_id':'','depends_on':['n_read_task'],'config':{'executor_ref':'local.command@1','command':['python','-c',probe]}})])
        client=Scripted([*raw,correction,decision([],True)])
        b,r=run_route(root=out/'cgnk',run_id='diag089-cgnk',route='R_CGNK',image=IMAGE,client=client,goal='Generic infrastructure probe',public_files={'task.json':'{}','scoring-contract.json':'{}','execution-policy.json':'{}','probe.txt':'PUBLIC'},mode='HARNESS_CONFORMANCE_ONLY')
        assert 'at most one' in client.contexts[2]['failure_details']['decision_validation']['error']
        assert len(client.contexts[2]['tree']['nodes'])==3
        assert 'LEGAL_AND_DENIED_PASS' in b.audit_path.read_text()
        rows.append({'route':'R_CGNK','receipt':r,'audit':verify_audit(b.audit_path),'checks':['exact old responses 1 and 2 retained','raw contract feedback reaches decision 3','invalid decision does not modify tree','synthetic correction executes actual tool; no product credit']})
        for route in ['R_DIRECT','R_CGNK']:
            client=Scripted([])
            b,r=run_route(root=out/('unavailable-'+route),run_id='diag089-unavailable-'+route.lower().replace('_','-'),route=route,image='sha256:'+'f'*64,client=client,goal='No execution allowed',mode='HARNESS_CONFORMANCE_ONLY')
            assert client.calls==0 and r['result']['status']=='BLOCKED_OR_ERROR'
            assert not any(json.loads(l)['kind']=='tool' for l in b.audit_path.read_text().splitlines())
            rows.append({'route':route,'check':'backend unavailable fails closed before model/tool','audit':verify_audit(b.audit_path)})
        b=ContainerBoundary(out/'recreate-failure','diag089-recreate-fail','R_DIRECT',Policy(IMAGE));b.start()
        with patch.object(b,'start',side_effect=RuntimeError('synthetic recreation failure')):
            result=b.execute(cmd(hang,1))
        assert result['status']=='BLOCKED_ENV' and not b.active
        denied=b.execute(cmd("raise AssertionError('must not execute')"));assert denied['status']=='BLOCKED_ENV'
        rows.append({'check':'recreation failure remains closed','result':result,'audit':verify_audit(b.audit_path)})
    assert not (ROOT/'forbidden-provider.jsonl').exists()
    (out/'results.json').write_text(json.dumps({'mode':'HARNESS_CONFORMANCE_ONLY','paid_calls':0,'rows':rows,'status':'PASS'},indent=2))
    print('HARNESS_CONFORMANCE_ONLY PASS; zero paid calls')
if __name__=='__main__':main()
