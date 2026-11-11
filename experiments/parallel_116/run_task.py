"""Small real-task wiring through AgentComposer -> existing DAG -> isolated tools.

No reference business implementation is installed. The main Agent decides work
and dependencies. Network preflight is non-generation; it fails closed.
"""
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from urllib.error import HTTPError

from cgkn.agent.composer import AgentComposer
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry, LLMExecutor
from cgkn.executors.task_evaluation import TaskEvaluationExecutor
from cgkn.providers import ModelRoleConfig
from cgkn.providers.gateway_client import completion_client_from_environment
from cgkn.providers.recording import RecordedCompletionClient
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from experiments.product_eval_076.isolation import ContainerBoundary, Policy, verify_audit
from experiments.product_dev_113.routes import ContainerFileActions, IsolatedExecutor


GOAL = """Build a small offline order-import tool. Deliver app.py and your own executable tests.
CLI: python app.py INPUT.jsonl --out RESULT.json --db STATE.sqlite.
Each nonblank JSON line contains order_id, sku, qty, unit_price. Trim order_id and sku;
both must be nonempty strings. qty must be a positive integer (not bool).
unit_price must be a nonnegative decimal string with at most two decimal places.
Money calculations must be exact. Import a whole valid file atomically into SQLite.
Repeating an identical order_id and identical normalized content is an idempotent no-op;
conflicting content for an existing order_id fails without changing prior state.
Invalid JSON/fields must exit nonzero without partial database changes or overwriting an existing result.
RESULT.json describes all persisted orders as {order_count:int,total_cents:int,by_sku:{sku:{qty:int,total_cents:int}}}.
Independent processes reopening the same database must produce consistent cumulative results.
Provide concise usage instructions and tests of valid input, invalid input, repeated imports and process reopen.

This is a real framework witness: use the three bounded branch Worker configurations for meaningful
independent contributions, including same-Provider distinct models and another Provider. You decide the
decomposition, filenames, interfaces, dependencies, testing and repairs. Branches have separate workspaces.
Use parallel_safe=true only for independent work. The collect capability copies completed dependency files
to the integration workspace and rejects conflicting content; it also exposes versioned branch inputs.
The integration Worker can inspect those inputs and resolve conflicts. Use actual isolated command tests.
After task receipts exist, invoke task.evaluate@1 on a feedback identity, read the advisory result and
candidate experience in the next decision, and decide any necessary next action. Evaluation is not acceptance.
Finish only after your integration tests and required deliverables are ready for independent acceptance.
Do not publish, contact external services, install unapproved dependencies or add unrelated features.
"""


def safe_files(root):
    root = Path(root).resolve()
    files = []
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('artifact symlink refused')
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat().st_mode) or not path.resolve().is_relative_to(root):
            raise ValueError('artifact outside regular workspace files')
        if path.stat().st_size > 2_000_000 or len(files) >= 200:
            raise ValueError('bounded artifact limit exceeded')
        files.append(path)
    return files


class BranchWorker:
    def __init__(self, label, boundary, client, config, snapshots):
        self.boundary, self.snapshots = boundary, snapshots
        self.worker = LLMExecutor(boundary.work, client, config, max_rounds=8)
        self.worker.actions = ContainerFileActions(boundary)
        self.descriptor = dataclasses.replace(self.worker.descriptor, executor_ref='worker.'+label+'@1')
        self.resource_claims = {'workspace:'+str(boundary.work): 'write'}

    def execute(self, request):
        result = self.worker.execute(request)
        if result.status != BlockStatus.SUCCEEDED:
            return result
        snapshot = self.snapshots / request.node_id / request.attempt_id
        snapshot.mkdir(parents=True, exist_ok=False)
        manifest = {}
        for path in safe_files(self.boundary.work):
            relative = path.relative_to(self.boundary.work)
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            manifest[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
        return dataclasses.replace(result, outputs={**dict(result.outputs),
            'artifact_snapshot': {'node_id': request.node_id, 'attempt_id': request.attempt_id, 'files': manifest}})


class Collect:
    descriptor = ExecutorDescriptor('artifact.collect@1', 'deterministic', ('artifact.collect@1',))

    def __init__(self, snapshots, target):
        self.snapshots, self.target = snapshots, target
        self.resource_claims = {'workspace:'+str(target.work): 'write'}

    def execute(self, request):
        collected, conflicts = [], []
        for node_id, output in request.task_context.dependency_results.items():
            snapshot = output.get('artifact_snapshot')
            if not snapshot or snapshot['node_id'] != node_id:
                raise ValueError('dependency lacks an exact artifact snapshot')
            source = self.snapshots / node_id / snapshot['attempt_id']
            for path in safe_files(source):
                relative = path.relative_to(source)
                if hashlib.sha256(path.read_bytes()).hexdigest() != snapshot['files'][relative.as_posix()]:
                    raise ValueError('snapshot hash mismatch')
                public = self.target.public / 'branches' / node_id / snapshot['attempt_id'] / relative
                public.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, public)
                target = self.target.work / relative
                if target.exists() and target.read_bytes() != path.read_bytes():
                    conflicts.append(relative.as_posix())
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    collected.append(relative.as_posix())
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
            node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
            status=BlockStatus.SUCCEEDED, outputs={'copied_files':collected,'unresolved_conflicts':conflicts,
                'public_branch_inputs':'/input/branches','integration_acceptance':'NOT_ASSESSED'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--authorization', type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--witness-followup', action='store_true')
    parser.add_argument('--knowledge', type=Path)
    parser.add_argument('--continuation', type=Path)
    parser.add_argument('--review-candidate', type=Path)
    args = parser.parse_args()
    if args.resume:
        if not (args.root/'state'/'parallel116'/args.root.name/'agent_checkpoint.json').is_file():
            raise ValueError('resume requires the original checkpoint')
    else:
        args.root.mkdir(parents=True, exist_ok=False)
    os.environ['CGKN_APPLICATION_PROFILE'] = str(args.profile.resolve())
    authority = json.loads(args.authorization.read_text(encoding='utf-8'))
    if authority.get('version') != 'GOAL-STAGE-ACV-V3.0' or authority.get('budget_policy') != 'accounting_only':
        raise ValueError('this task requires the recorded V3 authorization')
    (args.root/'public-task.md').write_text(GOAL, encoding='utf-8')
    image = subprocess.check_output(['docker','image','inspect','cgkn-eval076:v3-media','--format','{{.Id}}'],text=True).strip()
    client = completion_client_from_environment()
    inventory = {}
    for provider in ('qwen','deepseek'):
        try:
            inventory[provider] = client.models(provider)
        except HTTPError as exc:
            inventory[provider] = json.loads(exc.read())
    (args.root/('resume-preflight-'+str(time.time_ns())+'.json' if args.resume else 'preflight.json')).write_text(json.dumps({'image':image,'inventory':inventory,'generation_calls':0},indent=2))
    if not all(row.get('ok') and row.get('model_ids') for row in inventory.values()):
        raise RuntimeError('REAL_NETWORK_OR_MODEL_INVENTORY_BLOCKED; no generation sent')
    for row in inventory.values():
        for name, expected in row.get('runtime_source_sha256', {}).items():
            if hashlib.sha256((Path('cgkn/providers')/name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('GATEWAY_SOURCE_CHANGED: restart only this run-specific gateway')
    # Prefer the installed main planning binding; second model must actually be listed.
    import sys
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.storage import ProviderConfigStore
    installed = {p.provider_id:p.model for p in ProviderConfigStore().load()}
    second = next((m for m in ('qwen-plus','qwen-flash') if m in inventory['qwen']['model_ids'] and m != installed['qwen']), None)
    if not second or any(installed[p] not in inventory[p]['model_ids'] for p in ('qwen','deepseek')):
        raise RuntimeError('REQUIRED_CONFIGURED_MODEL_UNAVAILABLE')
    configs = {label:ModelRoleConfig('worker', provider, timeout_seconds=300,
        max_output_tokens=8192, model_id=model) for label,provider,model in
        [('a','qwen',installed['qwen']),('b','qwen',second),('c','deepseek',installed['deepseek'])]}
    (args.root/('resume-role-configs-'+str(time.time_ns())+'.json' if args.resume else 'role-configs.json')).write_text(json.dumps({k:dataclasses.asdict(v) for k,v in configs.items()},indent=2))
    if args.preflight_only:
        print('PREFLIGHT_ONLY; no generation');return
    os.environ.update(CGKN_PROVIDER_BUDGET_LEDGER='F:/CGKN-ITER-076/global-provider-budget.json',
        CGKN_PROVIDER_INPUT_COST_PER_MILLION='20',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='60')
    store = FileRunStore(args.root/'state')
    client = RecordedCompletionClient(dataclasses.replace(client, run_id=args.root.name,
        execution_policy='accounting_only',authorization_reference=str(args.authorization.resolve())),
        store,'parallel116',args.root.name)
    registry = ExecutorRegistry();boundaries=[];catalog={};snapshots=args.root/'snapshots'
    failure = None
    try:
        for label in ('a','b','c','integrate'):
            if args.resume:
                boundary = ContainerBoundary.__new__(ContainerBoundary)
                boundary.root = (args.root/label).resolve()
                boundary.run_id, boundary.route = args.root.name+'-'+label, 'R_CGNK'
                boundary.policy, boundary.name = Policy(image), 'eval076-'+boundary.run_id
                boundary.work, boundary.public = boundary.root/'workspace', boundary.root/'public'
                boundary.audit_path = boundary.root/'audit.jsonl'
                audit = verify_audit(boundary.audit_path)
                boundary.chain, boundary.active = audit['last_hash'], False
                boundary.record('checkpoint_resume', {'original_run':args.root.name,'preserved_workspace':True})
            else:
                boundary = ContainerBoundary(args.root/label,args.root.name+'-'+label,'R_CGNK',Policy(image))
            boundaries.append(boundary)
            if args.review_candidate:
                target = boundary.public/'review-candidate'
                target.mkdir(exist_ok=False)
                for source in safe_files(args.review_candidate):
                    dest = target/source.relative_to(args.review_candidate.resolve())
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,dest)
            (boundary.public/'task.md').write_text(GOAL,encoding='utf-8');boundary.start()
            worker = BranchWorker(label,boundary,client,configs.get(label,configs['a']),snapshots)
            registry.register(worker)
            catalog[worker.descriptor.executor_ref]={'executor_ref':worker.descriptor.executor_ref,
                'goal':'Agent supplies bounded task and file/interface contract', 'parallel_safe':label!='integrate',
                'environment':'/workspace writable; /input/task.md public; integration receives /input/branches'}
        integration = boundaries[-1]
        collector = Collect(snapshots,integration);registry.register(collector)
        catalog['artifact.collect@1']={'executor_ref':'artifact.collect@1','depends_on':'all source branch task IDs'}
        command = IsolatedExecutor(integration,'local.command@1')
        command.resource_claims={'workspace:'+str(integration.work):'write'};registry.register(command)
        catalog['local.command@1']={'executor_ref':'local.command@1','command':['python','-m','pytest','-q'],'timeout_seconds':120}
        evaluation = TaskEvaluationExecutor(store,client,configs['c'],allowed_models=tuple(configs))
        registry.register(evaluation)
        catalog['task.evaluate@1']={'executor_ref':'task.evaluate@1','meta_operation':True,
            'inputs':{'feedback_identity':'copy current TaskFeedback identity'}}
        from cgkn.state.task_feedback import FrozenKnowledge
        knowledge = FrozenKnowledge(json.loads(args.knowledge.read_text(encoding='utf-8'))) if args.knowledge else None
        runner = DAGRunner(registry,store,max_parallel=2,knowledge=knowledge)
        loop = AgentProjectLoop(AgentComposer(client,dataclasses.replace(configs['a'],role='agent')),
            runner,store,known_capabilities=set(catalog),worker_model=configs['c'].model,
            capability_catalog=catalog,max_decisions=8,continuous=True)
        result = loop.run(project_id='parallel116',run_id=args.root.name,goal=GOAL,
            continuation_feedback=(json.loads(args.continuation.read_text(encoding='utf-8')) if args.continuation else {'required': 'Business checks passed but ACV witness is incomplete. Do not finish until the following missing work has been executed and inspected.',
                'evaluation': 'First add task.evaluate@1 with config.inputs.feedback_identity copied exactly from a failed run_tests feedback item, config.meta_operation=true, executor_ref=task.evaluate@1. Then read its result in your next decision, cite its lesson and recommendation when assigning subsequent work. This is advisory, not acceptance.',
                'parallel': 'Earlier branches were serial because config.parallel_safe was absent. Add meaningful independent Worker tasks with config.parallel_safe=true, executor_ref and bounded goal explicitly set. Have worker.a and worker.b independently generate additional boundary-case test modules for exact money and invalid input; separately use worker.a and worker.c for additional idempotence and atomicity tests. Separate each pair by dependencies so max_parallel=2 gives each provider pair an opportunity for real overlap. Preserve existing business files; new uniquely named test files only. You own test design and dependency decisions. Independent tasks must not depend on each other.',
                'integration': 'Collect new versioned test files and run them against the existing integration app through formal Worker/tool capabilities. Repair through Workers as needed. Original successful branches must remain reusable. Return public evidence of evaluation usage and checks.'} if args.witness_followup else None))
        (args.root/'generation-result.json').write_text(json.dumps(result.as_dict(),indent=2))
        print(result.status+'; independent business acceptance remains required')
    except Exception as exc:
        failure = exc
        (args.root/('resume-error-'+str(time.time_ns())+'.json' if args.resume else 'execution-error.json')).write_text(json.dumps({'status':'BLOCKED_OR_ERROR','error_type':type(exc).__name__,'error':str(exc),'candidate_not_accepted':True},indent=2))
    finally:
        for boundary in boundaries:
            boundary.close()
            verify_audit(boundary.audit_path)
    if boundaries:
        frozen = args.root/('frozen-resume-'+str(time.time_ns()) if args.resume else 'frozen')/'candidate';frozen.mkdir(parents=True,exist_ok=False)
        manifest = {}
        for path in safe_files(boundaries[-1].work):
            relative = path.relative_to(boundaries[-1].work)
            dest = frozen/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            manifest[relative.as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
        (frozen.parent/'manifest.json').write_text(json.dumps(manifest,indent=2))
    if failure: raise failure


if __name__ == '__main__':
    main()
