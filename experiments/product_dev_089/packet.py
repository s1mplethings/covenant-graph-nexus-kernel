"""New DEV version, unchanged business task and initial snapshot; explicit budget."""
import json, hashlib, shutil, zipfile
from decimal import Decimal
from pathlib import Path
from .routes import TOOL_POLICY
from .budget_policy import ledger_cost

ROOT=Path('F:/CGKN-ITER-089')
OLD=Path('F:/CGKN-ITER-076')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    prior=Path('F:/CGKN-ITER-088/dev-packet');out=ROOT/'dev-packet';out.mkdir(exist_ok=False)
    for name in ['public','private']:shutil.copytree(prior/name,out/name)
    shutil.copyfile(prior/'initial.zip',out/'initial.zip')
    # No task-specific repair hints or prior model products are included.
    policy=out/'public/execution-policy.json'
    doc=json.loads(policy.read_text(encoding='utf-8'));doc['continuation_version']='ITER089-DEV-v1';doc['tool_policy']=TOOL_POLICY
    # Old rule statements are retained only in immutable prior packet, not in new public policy.
    def replace(v):
        if isinstance(v,str):
            if 'timeout' in v.lower() and ('container' in v.lower() or 'terminate' in v.lower()): return TOOL_POLICY
            return v
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        if isinstance(v,list):return [replace(x) for x in v]
        return v
    save(policy,replace(doc))
    task=out/'public/task.json';doc=json.loads(task.read_text(encoding='utf-8'))
    doc['dependencies']=doc['dependencies'].replace('Tool lifecycle unchanged: timeout kills container; agent arranges background services.','Tool lifecycle v9: timeout kills all processes and recreates same isolated environment; no command replay; agent arranges background services.')
    doc['continuation_version']='ITER089-DEV-v1';save(task,doc)
    total=ledger_cost(OLD/'global-provider-budget.json');assert total==Decimal('51.08948')
    remaining=Decimal('89.43242')-total;per=remaining/2
    doc=json.loads(policy.read_text(encoding='utf-8'));doc['version']='ITER089-DEV-v1';doc['route_cap_cny']=float(per);save(policy,doc)
    plan={'stage':'ITER-089-DEV-PAIR','approved':True,'user_authorization_reference':'Continue zero-fee lifecycle/contract repair; after validation version and run one real DEV pair within approved cumulative 89.43242 CNY; preserve all records.', 'cumulative_cap_cny':89.43242,'prior_cost_cny':float(total),'pair_hard_cap_cny':float(remaining),'route_cap_cny':float(per),'acceptance_reserve_cny':0,'same_ledger':str(OLD/'global-provider-budget.json'),'extra_attempts_authorized':False}
    save(out/'cost-plan.json',plan);save(ROOT/'authorization.json',plan)
    priorseal=json.loads((prior/'freeze.json').read_text(encoding='utf-8'))
    files={p:sha(p) for p in priorseal['files'] if not p.lower().startswith(str(prior).lower())}
    for folder in [out,Path('experiments/product_dev_089')]:
        for p in folder.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:files[str(p.resolve())]=sha(p)
    for f in ['cgkn/agent/composer.py','cgkn/agent/project_loop.py','tests/agent/test_project_loop_boundaries.py','docs/00_kernel_contract.md']:files[str(Path(f).resolve())]=sha(f)
    save(out/'freeze.json',{'version':'ITER089-DEV-v1','files':files,'reference_validation':'PASS','reference_evidence':'F:/CGKN-ITER-088/reference-validation-v2/validation.json','reference_scope':'unchanged business task/initial/media/oracle; no product credit','order':['R_DIRECT','R_CGNK'],'seed':8801,'prior':'ITER088-DEV-v1.1-report-only','exposure':'Known DEV scenario, not new holdout. Host has prior acceptance; no private feedback supplied to clean model sessions.','lifecycle_validation':str(ROOT/'conformance-v1/results.json'),'cgnk_lifecycle_validation':str(ROOT/'cgnk-lifecycle-result.json')})
    with zipfile.ZipFile(ROOT/'source-v1.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:
            if p.startswith('D:'):z.write(p,p[3:])
    print(json.dumps({'cost_plan':plan,'freeze_sha256':sha(out/'freeze.json')}))
if __name__=='__main__':main()
