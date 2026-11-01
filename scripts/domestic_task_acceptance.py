"""Bounded acceptance around the existing CGKN Agent/DAG/state authorities.

prepare and verify are non-billing. execute/finish require a fresh explicit user
authorization file. No project publishing, new planner, or alternate runtime.
"""
from __future__ import annotations
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import ast

from cgkn.agent.composer import AgentComposer,AgentDecisionContext,AGENT_SCHEMA
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.execution import TaskContext
from cgkn.executors import ExecutorRegistry,FileExecutor,LLMExecutor,PythonTestExecutor
from cgkn.executors.llm import BoundedFileActions,WORKER_SCHEMA
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.providers import GatewayCompletionClient,ModelRoleConfig
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.network_health import write_json
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

REPO=Path(__file__).resolve().parents[1]
PROJECT_ID='domestic-final-add'
RUN_ID='domestic-final-same-run'
GOAL='Repair math_utils.add to return a+b for integer inputs. Compose exactly inspect, fix, test, with dependencies inspect -> fix -> test. Use precisely the supplied capability_catalog configs. Only math_utils.py may be changed; do not modify tests. After a successful test run, finish with no additional edits. No repairs, extra nodes or additional model work are authorized in this acceptance.'
CATALOG={
 'repo.inspect@1':dict(executor_ref='local.file@1',action='read_file',path='math_utils.py'),
 'code.modify@1':dict(executor_ref='llm.cheap@1',goal='Correct math_utils.add to return a+b. Only patch/write math_utils.py; do not modify tests.',acceptance=['pytest passes']),
 'test.python@1':dict(executor_ref='local.python-test@1',pytest_args=['-q'])}
from cgkn.application.mvp_qualification import leaf_contract as demo_leaf_contract, install as install_demo_checks
for _node,_ref,_deps in [('inspect','repo.inspect@1',()),('fix','code.modify@1',('inspect',)),('test','test.python@1',('fix',))]:
    CATALOG[_ref]['leaf_contract']=demo_leaf_contract(_node,CATALOG[_ref]['executor_ref'],_deps)
LIMITS=dict(max_model_calls=3,max_planning_calls=2,max_worker_calls=1,max_upstream_body_bytes=16000,
    max_qwen_output_tokens=1200,max_deepseek_output_tokens=512,
    conservative_input_cny_per_million=20,conservative_output_cny_per_million=60,
    conservative_cost_upper_cny=1.13472,recommended_authorization_cny=2)


class AcceptancePause(BaseException):pass


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append(path,row):
    with Path(path).open('a',encoding='utf-8') as f:f.write(json.dumps({'at':time.time(),**row},ensure_ascii=False)+'\n')


def source_fingerprints():
    names=['scripts/domestic_task_acceptance.py','cgkn/agent/composer.py','cgkn/agent/project_loop.py',
        'cgkn/runtime/dag_runner.py','cgkn/state/store.py','cgkn/executors/llm.py',
        'cgkn/providers/gateway_client.py','cgkn/providers/domestic_gateway.py',
        'cgkn/providers/network_transport.py','cgkn/providers/direct_transport.py',
        'cgkn/providers/windows_interface.py','scripts/provider_api_budget.py','config/network_routes.json']
    result={n:digest(REPO/n) for n in names}
    lab=Path('D:/cgkn-provider-api-lab/src/cgkn_provider_lab')
    for name in ['adapters.py','gateway.py','service.py','storage.py','models.py','secrets.py']:
        result['external-api-lab/'+name]=digest(lab/name)
    return result


def provider_identities():
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    return [p.public_dict() for p in ProviderConfigStore().load() if p.provider_id in ('qwen','deepseek')]


def verify_fixture(root,plan,*,unmodified_project=False):
    expected=plan['baseline_files']
    for folder in ['baseline']+(['project'] if unmodified_project else []):
        files={p.name:digest(p) for p in (root/folder).iterdir() if p.is_file()}
        if files!=expected:raise ValueError('SEALED_FIXTURE_CHANGED: '+folder)
    if not unmodified_project:
        for name,value in expected.items():
            if name!='math_utils.py' and digest(root/'project'/name)!=value:raise ValueError('ORIGINAL_TEST_OR_FIXTURE_CHANGED')


def prepare(root):
    if (root/'plan.json').exists():raise ValueError('PREPARATION_ALREADY_EXISTS')
    root.mkdir(parents=True,exist_ok=True)
    shutil.copytree(REPO/'examples/agent_mvp_bugfix',root/'baseline',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    shutil.copytree(root/'baseline',root/'project')
    plan=dict(kind='CGKNDomesticLiveAcceptancePlan',scope='PREPARED_NOT_EXECUTED',project_id=PROJECT_ID,run_id=RUN_ID,
        goal=GOAL,catalog=CATALOG,limits=LIMITS,sources=source_fingerprints(),
        schemas=dict(agent=AGENT_SCHEMA,worker=WORKER_SCHEMA),baseline_files={p.name:digest(p) for p in (root/'baseline').iterdir() if p.is_file()},
        phases=['execute: Qwen planning -> deterministic inspect -> DeepSeek worker -> real pytest -> persist checkpoint -> stop before Qwen decision 2',
                'finish in a new process: reopen same run/goal/ledger -> Qwen finish -> independent oracle -> resume DAG with no new effects'],
        no_paid_calls_before_explicit_authorization=True,
        price_sources=['https://help.aliyun.com/zh/model-studio/qwen3-8-max','https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'])
    plan['provider_identities']=provider_identities()
    oracle=REPO/'artifacts/domestic-final-20261028/independent-review/verify_add.py'
    if not oracle.is_file():raise ValueError('INDEPENDENT_ORACLE_REQUIRED_BEFORE_PREPARATION')
    plan['independent_oracle']=dict(path=str(oracle.resolve()),sha256=digest(oracle))
    write_json(root/'plan.json',plan)
    write_json(root/'authorization-request.json',dict(kind='CGKNDomesticAcceptanceAuthorization',approved=False,
        user_authorization_reference=None,max_cost_cny=None,plan_sha256=digest(root/'plan.json'),max_model_calls=3))
    context=AgentDecisionContext(PROJECT_ID,RUN_ID,GOAL,1,CapabilityTree(GOAL,()),tuple(sorted(CATALOG)),CATALOG,{}, {}, {})
    write_json(root/'input-contract-preview.json',context.as_dict())
    env=os.environ.copy();env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    initial=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=root/'project',capture_output=True,text=True,timeout=30,env=env)
    write_json(root/'baseline-pytest.json',dict(returncode=initial.returncode,stdout=initial.stdout[-4000:],stderr=initial.stderr[-1000:]))
    if initial.returncode==0:raise ValueError('FIXTURE_MUST_FAIL_BEFORE_MODEL_WORK')
    write_json(root/'readiness.json',dict(generation='BLOCKED_AWAITING_EXPLICIT_USER_AMOUNT',model_calls=0,plan_sha256=digest(root/'plan.json')))
    return dict(state='PREPARED',model_calls=0,plan_sha256=digest(root/'plan.json'),limits=LIMITS)


def validate_authorization(root,path):
    plan=json.loads((root/'plan.json').read_text(encoding='utf-8'))
    if plan['sources']!=source_fingerprints():raise ValueError('SOURCE_CHANGED_REPREPARE_AND_REVIEW')
    if plan['provider_identities']!=provider_identities():raise ValueError('PROVIDER_CONFIGURATION_CHANGED')
    verify_fixture(root,plan)
    if digest(plan['independent_oracle']['path'])!=plan['independent_oracle']['sha256']:raise ValueError('INDEPENDENT_ORACLE_CHANGED')
    auth=json.loads(Path(path).read_text(encoding='utf-8'))
    if (auth.get('kind')!='CGKNDomesticAcceptanceAuthorization' or auth.get('approved') is not True
            or not auth.get('user_authorization_reference') or auth.get('plan_sha256')!=digest(root/'plan.json')
            or auth.get('max_model_calls')!=3):raise ValueError('CURRENT_EXPLICIT_USER_AUTHORIZATION_REQUIRED')
    amount=auth.get('max_cost_cny')
    if not isinstance(amount,(int,float)) or isinstance(amount,bool) or not LIMITS['conservative_cost_upper_cny']<=amount<=2:
        raise ValueError('AUTHORIZED_AMOUNT_MUST_COVER_PLAN_AND_NOT_EXCEED_2_CNY')
    return plan,auth


def configure_budget(root,amount):
    values=dict(CGKN_PROVIDER_BUDGET_LEDGER=str(root/'budget-ledger.json'),CGKN_PROVIDER_MAX_API_CALLS='3',
        CGKN_PROVIDER_MAX_PLANNING_CALLS='2',CGKN_PROVIDER_MAX_GENERATION_CALLS='1',
        CGKN_PROVIDER_MAX_INPUT_TOKENS='48000',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='2912',
        CGKN_PROVIDER_MAX_ESTIMATED_COST=str(amount),CGKN_PROVIDER_INPUT_COST_PER_MILLION='20',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='60',
        CGKN_PROVIDER_CACHE_MODE='read_write',CGKN_PROVIDER_RESPONSE_CACHE_DIR=str(root/'responses'))
    os.environ.update(values)


def bounded_request(provider,raw):
    doc=json.loads(raw)
    expected={'qwen':('qwen3.8-max',1200),'deepseek':('deepseek-flash',512)}
    if provider.provider_id not in expected or provider.model!=expected[provider.provider_id][0]:raise ValueError('UNPRICED_PROVIDER_DRIFT')
    if int(doc.get('max_tokens',0))!=expected[provider.provider_id][1]:raise ValueError('OUTPUT_LIMIT_DRIFT')
    if provider.provider_id=='qwen':doc['enable_thinking']=False
    else:doc['thinking']={'type':'disabled'}
    raw=json.dumps(doc,ensure_ascii=False).encode('utf-8')
    if len(raw)>16000:raise ValueError('UPSTREAM_INPUT_BOUND_EXCEEDED_BEFORE_SUBMISSION')
    return raw


class AuditedClient:
    def __init__(self,client,root):self.client,self.root=client,root
    def complete(self,**kwargs):
        config=kwargs['config']
        append(self.root/'model-audit.jsonl',dict(phase='input',role=config.role,provider=config.model,schema_name=kwargs['schema_name'],
            input_sha256=hashlib.sha256((kwargs['system']+kwargs['user']).encode()).hexdigest(),input_chars=len(kwargs['system'])+len(kwargs['user']),max_output_tokens=config.max_output_tokens))
        result=self.client.complete(**kwargs)
        append(self.root/'model-audit.jsonl',dict(phase='output',role=config.role,provider=config.model,request_id=result.request_id,
            output_sha256=hashlib.sha256(result.text.encode()).hexdigest(),output_summary=result.text[:240],usage=dict(result.usage),attempts=result.attempts,
            cache_replay=result.attempts==0))
        return result


class GuardedComposer(AgentComposer):
    def __init__(self,*args,phase,**kwargs):super().__init__(*args,**kwargs);self.phase=phase
    def decide(self,context):
        if (self.phase=='execute' and context.decision_number>=2) or context.decision_number>=3:raise AcceptancePause()
        decision=super().decide(context)
        if context.decision_number==1:
            tree=apply_tree_edits(context.tree,decision.edits,known_capabilities=set(CATALOG));compile_tree(tree)
            if set(tree.by_id)!={'inspect','fix','test'} or not decision.request_run or decision.finish:raise ValueError('UNEXPECTED_ACCEPTANCE_PLAN')
            for name,ref,deps in [('inspect','repo.inspect@1',()),('fix','code.modify@1',('inspect',)),('test','test.python@1',('fix',))]:
                node=tree.by_id[name]
                if node.capability_ref!=ref or tuple(node.depends_on)!=deps or node.as_dict()['config']!=CATALOG[ref]:raise ValueError('ACCEPTANCE_PLAN_CONTRACT_DRIFT')
        elif decision.edits or decision.request_run or not decision.finish or decision.needs_escalation:
            raise ValueError('FINAL_DECISION_MUST_ONLY_FINISH_VERIFIED_TASK')
        return decision


class RestrictedActions(BoundedFileActions):
    def apply(self,action):
        if action.get('action') in ('write_file','patch_file') and action.get('path')!='math_utils.py':
            raise ValueError('ACCEPTANCE_WRITES_ONLY_MATH_UTILS')
        if action.get('action') in ('write_file','patch_file'):
            if action['action']=='write_file':candidate=action['content']
            else:
                current=(self.root/'math_utils.py').read_text()
                if not action.get('find') or current.count(action['find'])!=1:raise ValueError('PATCH_MUST_MATCH_ONCE')
                candidate=current.replace(action['find'],action['replace'],1)
            validate_pure_candidate(candidate)
        return super().apply(action)


def validate_pure_candidate(source):
    """Safety before pytest, not a semantic success oracle. a-b and 5 still pass."""
    if len(source.encode())>4096:raise ValueError('ACCEPTANCE_SOURCE_TOO_LARGE')
    tree=ast.parse(source)
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):raise ValueError('ONLY_PURE_ADD_FUNCTION_ALLOWED')
    fn=tree.body[0]
    if fn.name!='add' or fn.decorator_list or [a.arg for a in fn.args.args]!=['a','b'] or fn.args.defaults or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.posonlyargs:
        raise ValueError('ONLY_PURE_ADD_FUNCTION_ALLOWED')
    if fn.body and isinstance(fn.body[0],ast.Expr) and isinstance(fn.body[0].value,ast.Constant) and isinstance(fn.body[0].value.value,str):fn.body=fn.body[1:]
    if len(fn.body)!=1 or not isinstance(fn.body[0],ast.Return):raise ValueError('ONLY_PURE_RETURN_ALLOWED')
    allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.BinOp,ast.UnaryOp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.USub,ast.UAdd,ast.Name,ast.Load,ast.Constant)
    nodes=list(ast.walk(tree))
    if len(nodes)>80:raise ValueError('PURE_FUNCTION_AST_LIMIT')
    for node in nodes:
        if not isinstance(node,allowed):raise ValueError('UNSAFE_CANDIDATE_AST')
        if isinstance(node,ast.Name) and node.id not in {'a','b','int'}:raise ValueError('UNSAFE_CANDIDATE_NAME')
        if isinstance(node,ast.Constant) and (not isinstance(node.value,int) or isinstance(node.value,bool) or abs(node.value)>1_000_000):raise ValueError('UNSAFE_CANDIDATE_CONSTANT')


def registry(root,client):
    result=ExecutorRegistry();result.register(FileExecutor(root/'project'))
    worker=LLMExecutor(root/'project',client,ModelRoleConfig('worker','deepseek',90,512,0,'none'))
    worker.actions=RestrictedActions(root/'project');result.register(worker);result.register(PythonTestExecutor(root/'project'))
    return result


def execute(root,authorization,phase):
    plan,auth=validate_authorization(root,authorization);configure_budget(root,auth['max_cost_cny'])
    prior=json.loads((root/'phase.json').read_text()) if (root/'phase.json').exists() else None
    if phase=='execute' and prior:raise ValueError('EXECUTION_ALREADY_STARTED_USE_SAME_RUN_FINISH_OR_RECONCILE')
    if phase=='execute':verify_fixture(root,plan,unmodified_project=True)
    if phase=='finish' and (not prior or prior['state']!='PAUSED_BEFORE_FINAL_AGENT_DECISION'):
        raise ValueError('NO_VERIFIED_PAUSE_TO_REOPEN')
    store=FileRunStore(root/'state')
    if phase=='finish':
        state=store.load_run(PROJECT_ID,RUN_ID)
        if not state.nodes or any(n.status!='SUCCEEDED' for n in state.nodes.values()):raise ValueError('CANNOT_FINISH_FAILED_OR_UNKNOWN_NODES')
    write_json(root/'phase.json',dict(state='EXECUTION_STARTED',phase=phase,at=time.time()))
    gateway=DomesticGateway('D:/cgkn-provider-api-lab',REPO/'config/network_routes.json',
        log=lambda row:append(root/'provider-trace.jsonl',row),request_transform=bounded_request)
    try:
        info=gateway.start();base=GatewayCompletionClient(info.base_url,info.access_token,run_id=RUN_ID,case_id=PROJECT_ID)
        client=AuditedClient(base,root);executors=registry(root,client)
        acceptance,checkers=install_demo_checks(executors,store,root/'project',PROJECT_ID,RUN_ID)
        runner=DAGRunner(executors,store,deliverable_checkers=checkers)
        composer=GuardedComposer(client,ModelRoleConfig('agent','qwen',90,1200,0,'none'),phase=phase)
        loop=AgentProjectLoop(composer,runner,store,known_capabilities=set(CATALOG),worker_model='deepseek',capability_catalog=CATALOG,max_decisions=2,continuous=True,acceptance=acceptance)
        try:
            result=loop.run(project_id=PROJECT_ID,run_id=RUN_ID,goal=GOAL,constraints=('Only math_utils.py may change','No model retry or repairs in this acceptance'))
            write_json(root/'task-result.json',result.as_dict());state='FINISHED' if result.status=='GOALS_VERIFIED' else 'BLOCKED'
        except AcceptancePause:
            current=store.load_run(PROJECT_ID,RUN_ID)
            state='PAUSED_BEFORE_FINAL_AGENT_DECISION' if all(n.status=='SUCCEEDED' for n in current.nodes.values()) else 'BLOCKED'
        write_json(root/'phase.json',dict(state=state,phase=phase,at=time.time(),run_id=RUN_ID))
        write_json(root/('persisted-'+phase+'.json'),store.load_run(PROJECT_ID,RUN_ID).as_dict())
        return dict(state=state,run_id=RUN_ID)
    finally:gateway.close()


def verify(root,oracle):
    # Independent process/oracle is sealed by the independent reviewer.
    output=root/'independent-result.json'
    plan=json.loads((root/'plan.json').read_text())
    verify_fixture(root,plan)
    if digest(oracle)!=plan['independent_oracle']['sha256']:raise ValueError('INDEPENDENT_ORACLE_HASH_MISMATCH')
    completed=subprocess.run([sys.executable,'-I','-S',str(oracle),'--project-root',str(root/'project'),
        '--baseline-root',str(root/'baseline'),'--output',str(output)],capture_output=True,text=True,timeout=8)
    write_json(root/'oracle-invocation.json',dict(returncode=completed.returncode,oracle_sha256=digest(oracle),stdout=completed.stdout[-1000:],stderr=completed.stderr[-1000:]))
    return dict(returncode=completed.returncode,result=str(output))


def reopen(root):
    store=FileRunStore(root/'state');prior=store.load_run(PROJECT_ID,RUN_ID)
    if any(n.status!='SUCCEEDED' for n in prior.nodes.values()) or not prior.nodes:raise ValueError('REOPEN_ONLY_KNOWN_SUCCESSFUL_NODES')
    tree=CapabilityTree.from_dict(json.loads((store.run_dir(PROJECT_ID,RUN_ID)/'capability_tree.json').read_text()))
    before={k:list(v.attempts) for k,v in prior.nodes.items()}
    # Historical inspection never invokes the runtime, rewrites a checkpoint or
    # upgrades execution success into a deliverable proof.
    receipts={n.id:store.load_result(PROJECT_ID,RUN_ID,n.id) for n in tree.nodes if n.executable}
    after={k:list(v.attempts) for k,v in store.load_run(PROJECT_ID,RUN_ID).nodes.items()}
    qualified=all(n.config.get('leaf_contract') and receipts[n.id].metadata.get('deliverable_verdict')=='VERIFIED' for n in tree.nodes if n.executable)
    return dict(state='PASS' if before==after else 'FAIL',attempts_before=before,attempts_after=after,
        reused_nodes=list(receipts),new_model_calls=0,actual_executions=[],read_only=True,
        deliverable_projection='EXISTING_PROOF_NOT_REEVALUATED' if qualified else 'LEGACY_UNQUALIFIED_DELIVERABLE')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','execute','finish','verify','reopen'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--authorization',type=Path);p.add_argument('--oracle',type=Path)
    a=p.parse_args();root=a.root.resolve()
    if a.action=='prepare':result=prepare(root)
    elif a.action=='reopen':result=reopen(root)
    elif a.action=='verify':
        if not a.oracle:p.error('--oracle required')
        result=verify(root,a.oracle.resolve())
    else:
        if not a.authorization:p.error('explicit --authorization required; no paid calls made')
        result=execute(root,a.authorization,a.action)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
