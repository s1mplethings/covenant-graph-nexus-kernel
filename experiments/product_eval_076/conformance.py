"""Fixed tool playback through the shared runner. Never product evidence."""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from cgkn.providers import ProviderCompletion
from experiments.product_eval_076.runner import run_route
from experiments.product_eval_076.isolation import verify_audit, Policy, ContainerBoundary
from experiments.product_eval_076.routes import create_route,TOOL_POLICY
from cgkn.providers import ModelRoleConfig
from experiments.product_eval_076.sidecar import close_target

class Replay:
    is_replay=True
    def __init__(self,actions):self.actions=actions;self.calls=0;self.agent_calls=0
    def complete(self,**kw):
        self.calls+=1
        context=json.loads(kw['user'])
        if kw['schema_name']=='direct_tool_action':assert context['tool_policy']==TOOL_POLICY
        elif kw['schema_name']=='cgkn_agent_decision':assert TOOL_POLICY in context['goal']
        if kw['schema_name']=='cgkn_worker_proposal':
            node=json.loads(kw['user'])['node_id']
            value={'schema_version':'1.0','node_id':node,'summary':'fixed file probe','actions':[{'action':'write_file','path':'/workspace/worker-probe.txt','content':'WORKER-PROBE'}],'expected_outputs':['file'],'confidence':1,'needs_escalation':False,'escalation_reason':''}
        elif kw['schema_name']=='direct_tool_action':
            i=self.calls-1
            value={'done':i>=len(self.actions),'action':self.actions[i] if i<len(self.actions) else {}}
        else:
            self.agent_calls+=1
            edits=[]
            if self.agent_calls==1:
                for i,a0 in enumerate(self.actions):
                    a=dict(a0);kind=a.pop('action');timeout=a.pop('timeout_seconds',120)
                    if kind=='worker_probe':ref='llm.cheap@1';cap='workspace.code@1';cfg={'goal':'Fixed file probe'}
                    elif kind=='command':ref='local.command@1';cap='workspace.command@1';cfg={'command':a['argv'],'stdin':a.get('stdin','')}
                    elif kind=='browser':ref='isolated.browser@1';cap='workspace.browser@1';cfg=a
                    else:ref='local.file@1';cap='workspace.file@1';cfg={'action':kind,**a}
                    cfg.update(executor_ref=ref,timeout_seconds=timeout)
                    edits.append({'edit_id':f'e{i}','operation':'add_node','node_id':f'n{i:03}','payload':{'capability_ref':cap,'parent_id':'','depends_on':[f'n{i-1:03}'] if i else [],'config':cfg},'provenance':{'source':'HARNESS_CONFORMANCE_ONLY'}})
            value={'schema_version':'1.0','decision_id':f'd{self.calls}','summary':'fixed protocol replay','reason':'HARNESS_CONFORMANCE_ONLY','edits':edits,'request_run':self.agent_calls==1,'finish':self.agent_calls>1,'needs_escalation':False,'escalation_reason':''}
        return ProviderCompletion(json.dumps(value),'REPLAY-NOT-A-MODEL',f'replay-{self.calls}',{})

APP="""from flask import Flask,request
import sqlite3
app=Flask(__name__)
@app.get('/')
def home():return '''<button id="b" onclick="fetch('/increment',{method:'POST'}).then(r=>r.text()).then(t=>document.getElementById('v').textContent=t)">Increment</button><div id="v">ready</div>'''
@app.post('/increment')
def increment():
 with sqlite3.connect('/workspace/probe.sqlite') as c:
  c.execute('create table if not exists events(v text)');c.execute('insert into events values (?)',('clicked',))
 return 'saved'
app.run(host='127.0.0.1',port=8000)
"""

def actions(private,sibling):
    checks=f'''import pathlib,subprocess,sqlite3,socket,os,json
assert pathlib.Path('/input/canary.txt').read_text()=='PUBLIC'
assert pathlib.Path('/workspace/note.txt').read_text()=='changed'
assert subprocess.check_output(['python','-c','print(17)']).strip()==b'17'
for p in {repr([str(private),str(sibling),'/private/canary.txt','../private/canary.txt','/audit.jsonl','/policy.json','/budget.json','/var/run/docker.sock'])}:
 assert not pathlib.Path(p).exists(),p
link=pathlib.Path('/workspace/escape');link.symlink_to('/private/canary.txt')
try:link.read_text();raise AssertionError('symlink readable')
except FileNotFoundError:pass
for p in ['/input/canary.txt','/opt/evaltools/browser.py','/policy.json','/budget.json','/audit.jsonl']:
 try:pathlib.Path(p).write_text('tamper');raise AssertionError('write allowed '+p)
 except OSError:pass
for host in ['1.1.1.1','host.docker.internal']:
 try:socket.create_connection((host,443),timeout=.5).close();raise AssertionError('external network')
 except OSError:pass
for argv in [['ffmpeg','-version'],['node','--version'],['chromium','--version']]:
 p=subprocess.run(argv,capture_output=True);assert p.returncode==0;print(p.stdout.decode().splitlines()[0])
print('ALLOW_AND_DENY_ASSERTIONS_PASSED')
'''
    return [
        {'action':'read_file','path':'/input/canary.txt'},
        {'action':'write_file','path':'/workspace/note.txt','content':'initial'},
        {'action':'patch_file','path':'/workspace/note.txt','find':'initial','replace':'changed'},
        {'action':'list_files','path':'/workspace'},
        {'action':'command','argv':['python','-c',checks]},
        {'action':'write_file','path':'/workspace/probe_app.py','content':APP},
        {'action':'command','argv':['python','-c',"import subprocess,time; subprocess.Popen(['python','probe_app.py'],stdout=open('/workspace/app.log','w'),stderr=subprocess.STDOUT,start_new_session=True); time.sleep(1)"]},
        {'action':'browser','url':'http://127.0.0.1:8000','javascript':"(async()=>{document.querySelector('#b').click();await new Promise(r=>setTimeout(r,500));return document.querySelector('#v').textContent})()",'screenshot':'/workspace/gui.png'},
        {'action':'command','argv':['python','-c',"import sqlite3; c=sqlite3.connect('probe.sqlite');assert c.execute('select count(*) from events').fetchone()[0]==1;c.close(); c=sqlite3.connect('probe.sqlite');assert c.execute('select v from events').fetchone()[0]=='clicked';print('PERSISTED_AFTER_REOPEN')"]},
        {'action':'browser','url':'file:///private/canary.txt','javascript':'document.body.innerText'},
        {'action':'read_file','path':'/private/canary.txt'},
    ]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--image',required=True);args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    private=out/'private';private.mkdir();(private/'canary.txt').write_text('PRIVATE-SYNTHETIC')
    sibling=out/'sibling';sibling.mkdir();(sibling/'canary.txt').write_text('SIBLING-SYNTHETIC')
    results=[]
    for short,route in [('direct','R_DIRECT'),('cgnk','R_CGNK')]:
        acts=actions(private/'canary.txt',sibling/'canary.txt')
        target_probe="""import urllib.request,json
base='http://127.0.0.1:9001'
account=json.load(urllib.request.urlopen(base+'/health'))['account']
payload={'account':account,'text':'synthetic publication','media':'synthetic.png','version':1,'correlation':'conformance'}
r=urllib.request.urlopen(urllib.request.Request(base+'/posts',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}));assert r.status==201
rows=json.load(urllib.request.urlopen(base+'/receipts?correlation=conformance'));assert len(rows)==1 and rows[0]['account']==account
payload['account']='forbidden-other-run'
try:urllib.request.urlopen(urllib.request.Request(base+'/posts',data=json.dumps(payload).encode()));raise AssertionError('wrong namespace accepted')
except urllib.error.HTTPError as e:assert e.code==400
try:urllib.request.urlopen(base+'/private/canary.txt');raise AssertionError('private read accepted')
except urllib.error.HTTPError as e:assert e.code==404
print('RUN_LOCAL_TARGET_AND_NAMESPACE_DENIAL_PASSED')"""
        acts.insert(-1,{'action':'command','argv':['python','-c',target_probe]})
        if route=='R_CGNK':acts.insert(-1,{'action':'worker_probe'})
        b,receipt=run_route(root=out/short,run_id=out.name.lower()+'-'+short,route=route,image=args.image,client=Replay(acts),goal='Fixed infrastructure probe; not a business problem',public_files={'canary.txt':'PUBLIC'},mode='HARNESS_CONFORMANCE_ONLY',keep_alive=True,controlled_target=True)
        rows=[json.loads(s) for s in b.audit_path.read_text().splitlines()]
        close_target(b,b.name+'-target')
        b.close()
        tool=[r['data'] for r in rows if r['kind']=='tool']
        assert len(tool)==len(acts),(route,receipt,len(tool))
        assert all(r['result'].get('exit_code')==0 for r in tool[:-1]),tool
        assert tool[-1]['result']['exit_code']!=0
        assert 'saved' in tool[7]['result']['stdout']
        assert 'PRIVATE-SYNTHETIC' not in tool[9]['result']['stdout']
        assert (b.work/'gui.png').is_file()
        # Same run, fresh processes have already reopened sqlite. Kill all app/browser
        # processes, then verify no container remains before moving to the next run.
        b.close()
        after=b.execute({'action':'command','argv':['python','-c',"open('/workspace/fallback-marker','w').write('bad')"]})
        assert after['status']=='BLOCKED_ENV' and not (b.work/'fallback-marker').exists()
        gone=subprocess.run(['docker','inspect',b.name],capture_output=True,text=True)
        assert gone.returncode!=0
        # Timeout traverses the identical runner/route/executor chain; stop whole
        # container, including the independently spawned child.
        timeout_action={'action':'command','argv':['python','-c',"import subprocess,time;subprocess.Popen(['python','-c',\"import time,pathlib;time.sleep(3);pathlib.Path('/workspace/late').write_text('leak')\"]);time.sleep(20)"],'timeout_seconds':1}
        t,tr=run_route(root=out/(short+'-timeout'),run_id=out.name.lower()+'-'+short+'-timeout',route=route,image=args.image,client=Replay([timeout_action]),goal='Timeout lifecycle canary',mode='HARNESS_CONFORMANCE_ONLY')
        time.sleep(3)
        assert not (t.work/'late').exists()
        timeout_rows=[json.loads(s) for s in t.audit_path.read_text().splitlines()]
        assert any(r['kind']=='tool' and r['data']['result']['status']=='TIMEOUT_CONTAINER_TERMINATED' for r in timeout_rows)
        # Invalid backend through the shared entrypoint must never call Provider.
        fake=Replay(acts)
        bad,br=run_route(root=out/(short+'-missing'),run_id=out.name.lower()+'-'+short+'-missing',route=route,image='sha256:'+'0'*64,client=fake,goal='Missing backend canary',mode='HARNESS_CONFORMANCE_ONLY')
        assert fake.calls==0 and br['result']['status']=='BLOCKED_OR_ERROR'
        results.append({'route':route,'status':'PASS','positive_and_negative_tools':len(tool),'timeout':'PASS','missing_backend':'PASS','post_cancel_no_fallback':'PASS','audit':verify_audit(b.audit_path),'timeout_audit':verify_audit(t.audit_path),'missing_audit':verify_audit(bad.audit_path),'gui_sha256':hashlib.sha256((b.work/'gui.png').read_bytes()).hexdigest()})
    files=[p for p in pathlib.Path(__file__).parent.glob('*.py')]+[pathlib.Path(__file__).parent/'Dockerfile']
    receipt={'mode':'HARNESS_CONFORMANCE_ONLY','formal_count':0,'paid_calls':0,'image':args.image,'source_hashes':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files},'results':results,'asr':'NOT_YET_PROVISIONED','formal_freeze':False}
    (out/'conformance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
