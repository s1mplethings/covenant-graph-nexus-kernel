"""Shared route entry point. Formal mode fails closed until full freeze exists."""
import json
import pathlib
from cgkn.providers import ModelRoleConfig
from experiments.product_dev_089.isolation import ContainerBoundary, Policy
from .routes import create_route
from .paths import safe_member
from experiments.product_eval_076_v8.sidecar import start_target,close_target

def run_route(*,root,run_id,route,image,client,goal,public_files=None,mode='DEV',max_calls=80,keep_alive=False,initial_files=None,controlled_target=False,formal_seal=None,state_snapshot=None):
    if mode not in {'DEV','HARNESS_CONFORMANCE_ONLY'}:raise ValueError('Unknown mode')
    if mode!='HARNESS_CONFORMANCE_ONLY' and getattr(client,'is_replay',True):raise RuntimeError('LIVE_PROVIDER_REQUIRED')
    if mode=='FORMAL':
        from .live_provider import LiveClient
        if type(client) is not LiveClient:raise RuntimeError('FORMAL_REQUIRES_REAL_LIVECLIENT')
        if formal_seal is None:raise RuntimeError('FORMAL_FREEZE_NOT_YET_AVAILABLE')
        from .formal_contract import validate
        seal,row=validate(formal_seal,run_id,route)
        if image!=seal['image']:raise RuntimeError('FORMAL_IMAGE_MISMATCH')
    b=ContainerBoundary(pathlib.Path(root),run_id,route,Policy(image))
    target=None
    try:
        for name,content in (public_files or {}).items():
            path=safe_member(name)
            dest=b.public/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(content if isinstance(content,bytes) else content.encode())
        for name,content in (initial_files or {}).items():
            path=safe_member(name)
            dest=b.work/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(content if isinstance(content,bytes) else content.encode())
        if state_snapshot is not None:
            import shutil
            source=pathlib.Path(state_snapshot)
            if any(p.is_symlink() for p in source.rglob('*')):raise ValueError('unsafe state snapshot link')
            shutil.copytree(source,b.root/'cgkn-state')
            # This run's immutable original receipts are development evidence,
            # not host summaries or external acceptance.
            for p in (source/'product-eval076'/run_id/'node_results').glob('*.json'):
                dest=b.work/'.cgkn-results'/run_id/p.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
        b.start()
        if controlled_target:target=start_target(b)
        auth=getattr(client,'authorization',{})
        agent_model=getattr(client,'resume_agent_model',None) or auth.get('agent_models',['deepseek'])[0]
        if auth.get('agent_models') and agent_model not in auth['agent_models']:raise ValueError('resumed agent role not authorized')
        worker_model=auth.get('worker_models',['grok'])[0]
        b.record('role_binding',{'source':'explicit task authorization' if auth.get('agent_models') else 'legacy experiment defaults','agent':agent_model,'worker':worker_model,'fallback':'explicit suitable agent alternatives only'})
        r=create_route(route,b,client,ModelRoleConfig('agent',agent_model,timeout_seconds=300,max_output_tokens=7000),ModelRoleConfig('worker',worker_model,timeout_seconds=300,max_output_tokens=8192))
        result=r.run(goal,max_calls=max_calls)
    except Exception as e:
        result={'status':'BLOCKED_OR_ERROR','error_type':type(e).__name__,'error':str(e)}
        b.record('runner_error',result)
    finally:
        if not keep_alive:
            if target:close_target(b,target)
            b.close()
    receipt={'mode':mode,'route':route,'run_id':run_id,'result':result,'model_calls':getattr(client,'calls',None),'formal_run_count':0 if mode!='FORMAL' else 1}
    (b.root/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return b,receipt
