"""One authorized API witness, using the original worker/DAG/budget boundary.

No retries, fallback, project generation, publishing, or model activation here.
"""
from pathlib import Path
import argparse
import dataclasses
import hashlib
import json
import os
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'artifacts/api-progress-clock-20261029/live-authorized-01'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    from cgkn.providers.streaming_sse import save_immutable_json
    save_immutable_json(Path(path), value)


def wire(row):
    from cgkn.providers.streaming_sse import configure_streamed_chat_request
    system = row['system']
    fmt = {'type': 'json_schema', 'json_schema': {'name': 'iter119_'+row['provider'], 'strict': True, 'schema': row['schema']}}
    if row['provider'] == 'deepseek':
        system += '\nReturn one JSON object matching this JSON Schema exactly: '+json.dumps(row['schema'], ensure_ascii=False)
        fmt = {'type': 'json_object'}
    body = dict(model=row['model'], messages=[dict(role='system', content=system), dict(role='user', content='user: '+row['user'])],
                temperature=0.0, max_tokens=row['output_limit'], reasoning_effort='none')
    if row['provider'] == 'qwen':
        body.pop('reasoning_effort')
        body['enable_thinking'] = False
        body['max_completion_tokens'] = body.pop('max_tokens')
    body['response_format'] = fmt
    return json.dumps(configure_streamed_chat_request(body), ensure_ascii=False, separators=(',', ':')).encode()


def preflight(plan):
    bounds={'ITER119AuthorizedPair':(.5,(2048,256)), 'ITER120AuthorizedPair':(.2,(2048,2048))}
    if plan.get('kind') not in bounds:raise ValueError('PAIR_AUTHORIZATION_BOUNDS')
    shared_cap, output_caps = bounds[plan['kind']]
    if plan.get('max_posts') != 2 or plan.get('max_cny') != shared_cap:
        raise ValueError('PAIR_AUTHORIZATION_BOUNDS')
    rows = plan['requests']
    if [(r['provider'], r['model'], r['role']) for r in rows] != [('qwen', 'qwen3.8-flash', 'agent'), ('deepseek', 'deepseek-flash', 'worker')]:
        raise ValueError('PAIR_MODELS_OR_COUNT_CHANGED')
    if plan['input_rate'] != 4 or plan['output_rate'] != 16:
        raise ValueError('PAIR_RESERVATION_PRICES_CHANGED')
    estimates = []
    for row, cap in zip(rows, output_caps):
        if row['input_ceiling'] != 8192 or row['output_limit'] != cap:
            raise ValueError('PAIR_TOKEN_BOUNDS_CHANGED')
        data = wire(row)
        if len(data)+1024 > row['input_ceiling']:
            raise ValueError('PAIR_FULL_REQUEST_INPUT_TOO_LARGE')
        estimates.append(dict(provider=row['provider'], wire_sha256=hashlib.sha256(data).hexdigest(),
            wire_bytes=len(data), byte_upper_with_framing=len(data)+1024,
            reserved_input_tokens=row['input_ceiling'], output_limit=cap,
            upper_cost_cny=(row['input_ceiling']*plan['input_rate']+cap*plan['output_rate'])/1_000_000))
    total = sum(r['upper_cost_cny'] for r in estimates)
    if total > shared_cap:raise ValueError('PAIR_TOTAL_BUDGET_EXCEEDED')
    return dict(calls=estimates, combined_upper_cost_cny=total, shared_cap_cny=shared_cap, generation_posts=0)


def validate_authorization(run=None):
    run = Path(run) if run is not None else RUN
    plan = read(run/'plan.json');auth = read(run/'authorization.json')
    if auth.get('authorized') is not True or auth.get('max_posts') != 2 or auth.get('max_cny') != plan.get('max_cny'):
        raise ValueError('PAIR_EXPLICIT_AUTHORIZATION_REQUIRED')
    if auth.get('plan_sha256') != digest(run/'plan.json') or auth.get('pricing_sha256') != digest(run/'pricing.json'):
        raise ValueError('PAIR_FROZEN_PLAN_CHANGED')
    if not 0 <= time.time()-auth['pricing_verified_unix'] <= 86400:
        raise ValueError('PAIR_PRICE_VERIFICATION_EXPIRED')
    for name, expected in auth['source_sha256'].items():
        if digest(ROOT/name) != expected:raise ValueError('PAIR_SOURCE_CHANGED')
    if digest(ROOT/'config/network_routes.json') != plan['network_sha256']:
        raise ValueError('PAIR_NETWORK_BINDING_CHANGED')
    return plan, preflight(plan)


def start(server, project):
    run = project.resolve().parent
    if project.name != 'project':raise ValueError('PAIR_PROJECT_NOT_AUTHORIZED')
    _, _, _, artifact = server._loaded(project)
    validate_authorization() if run == RUN.resolve() else validate_authorization(run)
    # Permanent attempt claim. Even an interrupted launch cannot create another pair.
    with (run/'attempt-claimed.json').open('x', encoding='utf-8') as f:
        json.dump(dict(at=time.time(), plan_sha256=digest(run/'plan.json')), f)
    return server.core.start_generation_job([sys.executable, '-X', 'utf8', '-m',
        'experiments.api_acceptance.iter119_pair', '--run-root', str(run)], cgkn_root=ROOT, artifact_dir=artifact)


def execute_pair(plan, client, run_id):
    from cgkn.providers import ModelRoleConfig
    from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
    from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
    from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
    from cgkn.orchestration.execution_dag import compile_tree
    from cgkn.runtime import DAGRunner
    from cgkn.state import FileRunStore
    from scripts.canonical_goal_spec_compiler import validate_planning_proposal
    registry = ExecutorRegistry()
    class Witness:
        def __init__(self, row):
            self.row = row
            self.descriptor = ExecutorDescriptor(row['provider']+'-witness@1', 'bounded_llm', ('*',))
        def execute(self, req):
            row = self.row;provider = row['provider'];start_time = time.time()
            envelope = dict(project_id=req.project_id, run_id=req.run_id, node_id=req.node_id,
                attempt_id=req.attempt_id, executor_ref=req.executor_ref)
            try:
                start_time = time.time()
                result = client.complete(system=row['system'], user=row['user'], schema_name='iter119_'+provider,
                    schema=row['schema'], config=ModelRoleConfig(row['role'], provider, max_output_tokens=row['output_limit'], model_id=row['model']),
                    call_identity=run_id+'-'+provider)
                value = json.loads(result.text)
                errors = validate_planning_proposal(value) if provider == 'qwen' else []
                save(RUN/(provider+'-result.json'), dict(status='PASS' if not errors else 'CONTRACT_FAILED',
                    started=start_time, ended=time.time(), completion=dataclasses.asdict(result), contract_errors=errors))
                save(RUN/(provider+'-result-saved.json'), dict(phase='witness_result_saved',provider=provider,
                    utc_unix=time.time(),monotonic_ns=time.monotonic_ns(),clock_pid=os.getpid(),run_id=run_id,
                    job_id=os.environ.get('CGKN_MODEL_JOB_ID'),attempt_id=os.environ.get('CGKN_MODEL_ATTEMPT_ID')))
                if errors:raise ValueError('PLANNING_CONTRACT_FAILED')
                return BlockExecutionResult(**envelope, status=BlockStatus.SUCCEEDED, outputs={'result': value}, usage=result.usage)
            except Exception as exc:
                save(RUN/(provider+'-error.json'), dict(started=start_time, ended=time.time(),
                    category=getattr(exc, 'category', type(exc).__name__), outcome_unknown=getattr(exc, 'outcome_unknown', False)))
                return BlockExecutionResult(**envelope, status=BlockStatus.BLOCKED,
                    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, getattr(exc, 'category', type(exc).__name__)))
    for row in plan['requests']:registry.register(Witness(row))
    tree = CapabilityTree('ITER-119 two independent authorized API witnesses', tuple(
        CapabilityNode(r['provider'], capability_ref='bounded-api-witness@1',
            config={'executor_ref':r['provider']+'-witness@1', 'parallel_safe':True}) for r in plan['requests']))
    return DAGRunner(registry, FileRunStore(RUN/'state'), max_parallel=2).run(
        project_id='iter119', run_id=run_id, tree=tree, dag=compile_tree(tree))


def main():
    global RUN
    p = argparse.ArgumentParser();p.add_argument('--result', required=True)
    p.add_argument('--generation-job-state', required=True);p.add_argument('--generation-job-id', required=True)
    p.add_argument('--generation-attempt-id', required=True)
    p.add_argument('--run-root', type=Path, default=RUN);args = p.parse_args()
    RUN = args.run_root.resolve()
    sys.path.insert(0, str(ROOT/'tools/cgkn-agent-kit/src'))
    from cgkn_agent_kit import core
    state_path = Path(args.generation_job_state);artifact = state_path.parent
    def update(**values):
        with core.generation_job_lock(artifact):
            job = core.read_json(state_path)
            if job['job_id'] != args.generation_job_id or job['attempt_id'] != args.generation_attempt_id:
                raise ValueError('PAIR_JOB_IDENTITY_CHANGED')
            job.update(values, updated_at=core.now(), process_id=os.getpid(), revision=job['revision']+1)
            core.write_json(state_path, job)
    run_id = 'api-pair-' + args.generation_attempt_id
    update(state='RUNNING', run_id=run_id, run_dir=str(RUN))
    try:
        plan, check = validate_authorization()
        if not (RUN/'attempt-claimed.json').exists():raise ValueError('PAIR_MCP_CLAIM_REQUIRED')
        with (RUN/'worker-claimed.json').open('x') as f:f.write(args.generation_job_id)
        save(RUN/'worker-preflight.json', check)
        # Shared process environment, established once before either DAG node runs.
        for name in list(os.environ):
            if name.startswith('CGKN_PROVIDER_') and any(x in name for x in ('MAX_', 'BUDGET', 'COST_', 'CACHE')):
                del os.environ[name]
        os.environ.update(CGKN_PROVIDER_BUDGET_LEDGER=str(RUN/'budget.json'), CGKN_PROVIDER_MAX_API_CALLS='2',
            CGKN_PROVIDER_MAX_PLANNING_CALLS='1', CGKN_PROVIDER_MAX_GENERATION_CALLS='1', CGKN_PROVIDER_MAX_REPAIR_CALLS='0',
            CGKN_PROVIDER_MAX_INPUT_TOKENS='16384', CGKN_PROVIDER_MAX_OUTPUT_TOKENS=str(sum(r['output_limit'] for r in plan['requests'])), CGKN_PROVIDER_MAX_ESTIMATED_COST=str(plan['max_cny']),
            CGKN_PROVIDER_INPUT_COST_PER_MILLION='4', CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='16', CGKN_PROVIDER_CACHE_MODE='off',
            CGKN_MODEL_JOB_ID=args.generation_job_id, CGKN_MODEL_ATTEMPT_ID=args.generation_attempt_id)
        from cgkn.providers.application_network import settings, session
        from cgkn.providers.gateway_client import GatewayCompletionClient
        config = settings()
        if not config:raise ValueError('PAIR_DOMESTIC_PROFILE_REQUIRED')
        info, status = session(config, autostart=False)
        if status['session_id'] != read(RUN/'authorization.json')['gateway_session_id']:
            raise ValueError('PAIR_GATEWAY_SESSION_CHANGED')
        client = GatewayCompletionClient(info['base_url'], info['access_token'], api_method='chat_completions',
            input_token_ceiling=8192, authorization_reference=str(RUN/'authorization.json')).bind_run(run_id, 'ITER119-PAIR')
        summary = execute_pair(plan, client, run_id)
        result = dict(status=summary.status, generation_job_id=args.generation_job_id,
            generation_attempt_id=args.generation_attempt_id, run_id=run_id, formal_evidence_status='NOT_EVALUATED',
            scope='API_WITNESS_ONLY', automatic_retry=False)
        save(Path(args.result), result);save(RUN/'execution-summary.json', result)
        update(state='COMPLETE' if summary.status == 'SUCCEEDED' else 'REWORK_BLOCKED', terminal_reason='API_WITNESS_ENDED_NO_RETRY')
    except Exception as exc:
        save(RUN/'worker-error.json', dict(error_type=type(exc).__name__))
        update(state='REWORK_BLOCKED', terminal_reason='PAIR_BLOCKED_NO_RETRY')


if __name__ == '__main__':main()
