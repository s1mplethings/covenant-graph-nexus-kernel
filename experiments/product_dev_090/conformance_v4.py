import json
from pathlib import Path
from experiments.product_dev_089.conformance import Scripted, IMAGE
from experiments.product_dev_090.runner import run_route
from experiments.product_dev_089.isolation import verify_audit
from experiments.diagnostic_088.offline import no_provider

def act(cap='',config=None,deps=None,op='execute',node=''):
 return {'summary':'Synthetic infrastructure probe','operation':op,'capability':cap,'config':config or {},'depends_on':deps or [],'node_id':node}
def worker(actions):
 return dict(schema_version='1.0',node_id='n0003',summary='Synthetic bounded worker output',actions=actions,expected_outputs=['probe.txt'],confidence=1,needs_escalation=False,escalation_reason='')
def main():
 root=Path('F:/CGKN-ITER-090/conformance-v4');root.mkdir(exist_ok=False)
 private=root/'private-canary';private.write_text('synthetic only')
 rows=[act('invalid'),act('workspace.file@1',{'action':'read_file','path':'/input/probe.txt'}),act('workspace.code@1',{'goal':'Copy the supplied synthetic probe text to probe.txt. This is a transport test, not a product task.','acceptance':['probe.txt contains PROBE']},['n0002']),worker([{'action':'read_file','path':'/input/probe.txt'}]),worker([{'action':'write_file','path':'probe.txt','content':'PROBE'}]),act('workspace.command@1',{'command':['python','-c',"import pathlib,sqlite3,subprocess;assert pathlib.Path('probe.txt').read_text()=='PROBE'; assert not pathlib.Path("+repr(str(private))+").exists(); c=sqlite3.connect('probe.db');c.execute('create table t(v)');c.execute('insert into t values(1)');c.commit();c.close();assert sqlite3.connect('probe.db').execute('select v from t').fetchone()[0]==1; assert subprocess.run(['ffmpeg','-version'],capture_output=True).returncode==0; print('PASS')"]}),act(op='finish')]
 client=Scripted(rows)
 with no_provider(root/'forbidden.jsonl'):
  b,r=run_route(root=root/'run',run_id='diag090-tools',route='R_CGNK',image=IMAGE,client=client,goal='HARNESS_CONFORMANCE_ONLY',public_files={'probe.txt':'PROBE'},mode='HARNESS_CONFORMANCE_ONLY')
 assert r['result']['status']=='SUCCEEDED',r
 assert client.contexts[1]['tree']==[] and 'decision_validation' in client.contexts[1]['failure_details']
 assert 'PROBE' in json.dumps(client.contexts[2]['execution_results'])
 assert client.contexts[4]['observations'][0]['content']=='PROBE'
 assert client.contexts[5]['execution_results']['n0003']['outputs']['modified_files']==['probe.txt']
 assert 'PASS' in client.contexts[6]['execution_results']['n0004']['outputs']['stdout']
 assert r['result']['run_summary']['retry_attempts']==0
 closed=Scripted([])
 with no_provider(root/'forbidden.jsonl'):
  b2,r2=run_route(root=root/'unavailable',run_id='diag090-unavailable',route='R_CGNK',image='sha256:'+'f'*64,client=closed,goal='HARNESS_CONFORMANCE_ONLY',mode='HARNESS_CONFORMANCE_ONLY')
 assert closed.calls==0 and r2['result']['status']=='BLOCKED_OR_ERROR'
 (root/'contexts.json').write_text(json.dumps(client.contexts,indent=2))
 (root/'result.json').write_text(json.dumps({'status':'PASS','mode':'HARNESS_CONFORMANCE_ONLY','calls_paid':0,'receipt':r,'audit':verify_audit(b.audit_path),'fail_closed':r2,'unavailable_audit':verify_audit(b2.audit_path)},indent=2))
 print('PASS real isolated CGNK actions, successful result in next actual request, worker read/write/return, illegal action atomic, no successful replay, backend fail closed')
if __name__=='__main__': main()

