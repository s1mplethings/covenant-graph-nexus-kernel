"""Shared route entry point. Formal mode fails closed until full freeze exists."""
import json
import pathlib
from cgkn.providers import ModelRoleConfig
from experiments.product_dev_089.isolation import ContainerBoundary, Policy
from .routes import create_route
from experiments.product_eval_076_v8.sidecar import start_target,close_target

def run_route(*,root,run_id,route,image,client,goal,public_files=None,mode='DEV',max_calls=80,keep_alive=False,initial_files=None,controlled_target=False,formal_seal=None):
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
            path=pathlib.PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe public input name')
            dest=b.public/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(content if isinstance(content,bytes) else content.encode())
        for name,content in (initial_files or {}).items():
            path=pathlib.PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe initial input name')
            dest=b.work/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(content if isinstance(content,bytes) else content.encode())
        b.start()
        if controlled_target:target=start_target(b)
        r=create_route(route,b,client,ModelRoleConfig('agent','qwen',timeout_seconds=300,max_output_tokens=4096),ModelRoleConfig('worker','deepseek',timeout_seconds=300,max_output_tokens=8192))
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
