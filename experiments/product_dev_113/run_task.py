"""Task-neutral driver for the same CGKN route; no business planner or patches."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from .network_client import NetworkClient
from .runner import run_route
from .packet import IMAGE, save
from .budget_policy import ledger_cost
from experiments.product_dev_089.isolation import verify_audit


def main():
    p=argparse.ArgumentParser()
    for flag in ('packet','output','authorization','resources','transport-config','freeze'):
        p.add_argument('--'+flag,required=True,type=Path)
    p.add_argument('--run-id',required=True)
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    seal=json.loads(a.freeze.read_text())
    for name,digest in seal['files'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise RuntimeError('FREEZE_MISMATCH '+name)
    if not a.execute:print('LOCAL_CONFIG_VALID; no Provider calls');return
    a.output.mkdir(parents=True,exist_ok=False)
    public={p.name:p.read_bytes() for p in (a.packet/'public').iterdir() if p.is_file()}
    task=json.loads(public['task.json'])
    previous=json.loads(a.resources.read_text())
    with zipfile.ZipFile(a.packet/'initial.zip') as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    client=NetworkClient('D:/cgkn-provider-api-lab','F:/CGKN-ITER-076/global-provider-budget.json',
        a.output/'provider',a.run_id,run_cap_cny=None,honor_reasoning_none=True,
        authorization=a.authorization,transport_config=a.transport_config)
    client.calls=previous['calls'];client.tokens=previous['tokens'];client.run_cost=previous['cost']
    client.started=time.monotonic()-previous['development_seconds'];client.transport_retries=previous['transport_retries']
    client.goal_requirements={r['id']:r for r in task['public_requirements']}
    goal='Complete this public vertical task. Independently understand, plan phases and goals, delegate implementation and tests to CGKN workers, inspect real results and correct failures. The initial scaffold contains no scored business implementation. Keep scope to these public requirements: '+json.dumps(task,ensure_ascii=False)
    try:
        b,receipt=run_route(root=a.output/'run',run_id=a.run_id,route='R_CGNK',image=IMAGE,
            client=client,goal=goal,public_files=public,initial_files=files,mode='DEV')
    finally:client.close()
    resources={'calls':client.calls,'tokens':client.tokens,'cost':client.run_cost,
        'development_seconds':time.monotonic()-client.started,'transport_retries':client.transport_retries,
        'ledger_cost':str(ledger_cost(client.ledger))}
    save(a.output/'resources.json',resources)
    save(a.output/'dev-result.json',{'receipt':receipt,'resources':resources,'audit':verify_audit(b.audit_path),
        'source_version':seal['version'],'task_id':task['task_id'],'initial':str(a.packet/'initial.zip'),
        'baseline_resources':str(a.resources),'counter_scope':'branch counters include referenced baseline; concurrent branches must be reconciled by per-call records, not added raw totals','classification':'REAL_PROVIDER_VERTICAL_DEV_NOT_HOST_FIXTURE'})
    cmd=[sys.executable,'experiments/product_eval_076_v8/freeze_candidate.py','--dev-root',str(a.output),
         '--output',str(a.output/'frozen'),'--image',IMAGE]
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=150)
    save(a.output/'freeze-command.json',{'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    print(json.dumps({'result':receipt['result']['status'],'resources':resources,'freeze_exit':result.returncode}))


if __name__=='__main__':main()
