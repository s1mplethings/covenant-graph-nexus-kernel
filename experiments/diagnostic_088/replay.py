"""Replay unmodified historic model text through actual CGNK route/loop/store."""
import argparse
import json
import traceback
from pathlib import Path
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from experiments.product_eval_076_v8.routes import CGNKRoute
from .capture import ROOT, OLD, save, sha
from .offline import no_provider

class RecordedClient:
    is_replay=True
    def __init__(self, source):
        self.rows=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((source/'provider').glob('*.result.json'))]
        self.calls=0
    def complete(self, **kwargs):
        if self.calls==len(self.rows):raise RuntimeError('RECORDED_ACTIONS_EXHAUSTED_NO_NEW_MODEL')
        row=self.rows[self.calls];self.calls+=1
        return ProviderCompletion(row['text'],row['upstream_model'],row['request_id'],row.get('usage',{}))

class RecordingBoundary:
    """Only records commands; never executes a historic business action."""
    def __init__(self, root, run_id):
        self.root=root;self.work=root/'workspace';self.work.mkdir(parents=True)
        self.run_id=run_id;self.active=True;self.actions=[]
    def record(self, kind, data): self.actions.append({'kind':kind,'data':data})
    def execute(self, action, timeout=120):
        self.actions.append({'kind':'recording_executor','action':action})
        return {'exit_code':0,'status':'SUCCEEDED','stdout':'{"recording_only":true}','stderr':''}

def replay(source, dest):
    dest.mkdir(parents=True,exist_ok=False)
    b=RecordingBoundary(dest/'run',source.name);client=RecordedClient(source)
    route=CGNKRoute(b,client,ModelRoleConfig('agent','qwen'),ModelRoleConfig('worker','deepseek'))
    original=route.runner.run;transitions=[]
    def traced(**kwargs):
        state_path=route.store.run_dir(kwargs['project_id'],kwargs['run_id'])/'run_state.json'
        entry={'tree':kwargs['tree'].as_dict(),'dag':kwargs['dag'].as_dict(),'resume':kwargs.get('resume'),'state_path':str(state_path),'before':json.loads(state_path.read_text()) if state_path.exists() else None,'execution_count_before':sum(x['kind']=='recording_executor' for x in b.actions)}
        transitions.append(entry)
        try:
            r=original(**kwargs);entry['result']=r.as_dict();return r
        except Exception:
            entry['stack']=traceback.format_exc();raise
        finally:
            entry['after']=json.loads(state_path.read_text()) if state_path.exists() else None
    route.runner.run=traced
    try:result=route.run('Offline exact historic action replay; not a product attempt')
    except Exception as e:result={'error':str(e),'stack':traceback.format_exc()}
    save(dest/'replay.json',{'mode':'HARNESS_CONFORMANCE_ONLY','source':str(source),'raw_response_hashes':{p.name:sha(p) for p in sorted((source/'provider').glob('*.result.json'))},'result':result,'transitions':transitions,'actions':b.actions,'paid_calls':0})
    return {'run_id':source.name,'result':result.get('error',result.get('status')),'transitions':len(transitions),'first_mismatch':next(({'index':i,'old_nodes':list(t['before']['nodes']) if t['before'] else [],'new_nodes':[n['id'] for n in t['dag']['nodes']]} for i,t in enumerate(transitions) if 'persisted run state does not match DAG' in t.get('stack','')),None)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--version',required=True);a=p.parse_args()
    out=ROOT/('replay-'+a.version);out.mkdir(exist_ok=False)
    with no_provider(ROOT/'forbidden-provider.jsonl'):
        rows=[replay(d,out/d.name) for d in [OLD/'protocol-v8-r-cgnk',*sorted((OLD/'formal-v8').glob('*cgnk'))]]
    save(out/'index.json',rows);print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
