from __future__ import annotations

import pathlib
import json
import time
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object

from .protocol import ExecutorDescriptor


from cgkn.execution.file_actions import (
    ALLOWED_ACTIONS, PROTECTED_PARTS, ProposalError, BoundedFileActions)

from cgkn.execution.file_actions import WORKER_SCHEMA, validate_worker_proposal, scoped_worker_schema


def repair_worker_envelope(value: Mapping[str, Any], node_id: str) -> tuple[dict[str, Any], list[str]]:
    """Repair only the protocol envelope, never the business actions.

    The gateway can reject a semantically valid proposal because it omitted
    non-business metadata. Fill only those fields, record exactly what was
    filled, and leave actions untouched. A missing ``actions`` array is not
    repairable here.
    """
    required = list(WORKER_SCHEMA["required"])
    repaired = dict(value)
    missing = [name for name in required if name not in repaired]
    write_paths = []
    actions = repaired.get("actions")
    if isinstance(actions, list):
        write_paths = [str(item.get("path")) for item in actions
                       if isinstance(item, Mapping) and item.get("action") in {"write_file", "patch_file"}]
    defaults = {
        "schema_version": "1.0",
        "node_id": node_id,
        "summary": "protocol repair: worker omitted a non-business envelope field",
        "expected_outputs": write_paths,
        "confidence": 0.5,
        "needs_escalation": False,
        "escalation_reason": "",
    }
    for name in missing:
        if name == "actions":
            continue
        repaired[name] = defaults[name]
    return repaired, missing


def _missing_envelope_fields(completed: Mapping[str, Any]) -> list[str]:
    raw = completed.get("output_text") or (completed.get("cgkn_raw_defer") or {}).get("raw_text")
    if not raw:
        return []
    try:
        value = parse_json_object(raw)
    except Exception:
        return []
    if not isinstance(value, Mapping):
        return []
    return [name for name in WORKER_SCHEMA["required"] if name not in value]


def plan_bounded_patches(actions, root, policy):
    """Pure preflight; no effects until every patch satisfies the frozen policy."""
    import difflib, hashlib, io, re
    if not isinstance(policy, Mapping) or policy.get('mode') != 'patch_only':
        raise ProposalError('INVALID_PATCH_POLICY')
    specs = policy.get('files', {})
    if not isinstance(specs, Mapping) or not specs:
        raise ProposalError('INVALID_PATCH_POLICY')
    planned = {}; receipts = []
    for action in actions:
        if action['action'] in {'read_file', 'list_files'}:
            continue
        name = BoundedFileActions(root)._path(action['path']).relative_to(root).as_posix()
        if action['action'] != 'patch_file' or name not in specs:
            raise ProposalError('PATCH_SCOPE_EXCEEDED: only authorized patch_file actions')
        planned.setdefault(name, []).append(action)
    if not planned:
        raise ProposalError('NO_IMPLEMENTATION_DELTA: no patch actions')
    outputs = {}
    for name, patches in planned.items():
        raw = (root / name).read_bytes(); original = raw.decode('utf8')
        before_hash = hashlib.sha256(raw).hexdigest(); spec = specs[name]
        if before_hash != spec.get('source_sha256'):
            raise ProposalError('OBJECT_VERSION_MISMATCH: patch policy source changed')
        # Universal-newline view matches read_file; map every character back to
        # original bytes so an exact patch cannot rewrite unrelated line endings.
        normalized = []; offsets = []; position = 0
        for match in re.finditer(r'\r\n|\r|\n|[^\r\n]', original):
            offsets.append(match.start())
            normalized.append('\n' if match.group() in {'\r\n','\r','\n'} else match.group())
        offsets.append(len(original)); text = ''.join(normalized)
        ranges = spec.get('ranges', [])
        if not ranges or any(not isinstance(r, (list,tuple)) or len(r)!=2
                or any(type(x) is not int for x in r) or not 0<=r[0]<r[1]<=len(text) for r in ranges):
            raise ProposalError('INVALID_PATCH_POLICY: source-bound character ranges required')
        changes = []
        for action in patches:
            find = io.StringIO(action['find'], newline=None).read()
            replacement = io.StringIO(action['replace'], newline=None).read()
            anchor_limit = spec.get('max_anchor_chars')
            if anchor_limit is not None:
                if type(anchor_limit) is not int or anchor_limit <= 0:
                    raise ProposalError('INVALID_PATCH_POLICY: positive anchor limit required')
                if len(find) > anchor_limit:
                    raise ProposalError('PATCH_SCOPE_EXCEEDED: anchor length budget exceeded')
            if not find or text.count(find) != 1:
                raise ProposalError('PATCH_SCOPE_EXCEEDED: ambiguous patch anchor')
            start = text.index(find); end = start + len(find)
            if not any(a<=start and end<=b for a,b in ranges):
                raise ProposalError('PATCH_SCOPE_EXCEEDED: patch outside authorized region')
            if find == replacement:
                raise ProposalError('NO_IMPLEMENTATION_DELTA: unchanged patch')
            if any(start < old_end and old_start < end for old_start,old_end,_ in changes):
                raise ProposalError('PATCH_SCOPE_EXCEEDED: overlapping patches')
            changes.append((start,end,replacement))
        changed_chars = sum((end-start)+len(replacement) for start,end,replacement in changes)
        limit = spec.get('max_changed_chars')
        if type(limit) is not int or limit<=0 or changed_chars>limit:
            raise ProposalError('PATCH_SCOPE_EXCEEDED: change budget exceeded')
        result = original
        newline = '\r\n' if '\r\n' in original else '\n'
        for start,end,replacement in sorted(changes,reverse=True):
            result = result[:offsets[start]] + replacement.replace('\n',newline) + result[offsets[end]:]
        result = result.encode('utf8')
        after_hash = hashlib.sha256(result).hexdigest()
        if after_hash == before_hash:
            raise ProposalError('NO_IMPLEMENTATION_DELTA')
        outputs[name] = result
        receipts.append({'path':name,'before_sha256':before_hash,'after_sha256':after_hash,
            'policy_source_sha256':spec['source_sha256'],'changed_ranges':[
                {'start_char':start,'end_char':end,'start_line':text.count('\n',0,start)+1,
                 'end_line':text.count('\n',0,end)+1,'replacement_sha256':hashlib.sha256(replacement.encode()).hexdigest()}
                for start,end,replacement in changes], 'verdict':'BOUNDED_PATCH_WITH_SOURCE_DELTA'})
    return outputs, receipts


class LLMExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "bounded_llm", ("*",), ("filesystem.read", "filesystem.write"))

    def __init__(self, project_root: pathlib.Path | str, client: CompletionClient, config: ModelRoleConfig, *, max_rounds: int = 4, capability_ledger=None, semantic_protocol=False, protocol_trace=None, patch_policy=None):
        if config.role != "worker":
            raise ValueError("LLMExecutor requires worker model config")
        if semantic_protocol:
            if not callable(protocol_trace):raise ValueError("semantic protocol requires an audit sink")
            from cgkn.protocol.adapters import SemanticWorkerClient
            client=SemanticWorkerClient(client,protocol_trace)
        self.actions, self.client, self.config = BoundedFileActions(project_root), client, config
        self.resource_claims = {"workspace:" + str(pathlib.Path(project_root).resolve()): "write"}
        self.max_rounds = max_rounds
        self._cancelled=set()
        self.patch_policy = patch_policy
        self.model_configs = {}
        self.capability_ledger = capability_ledger

    def _apply_proposal(self, request: BlockExecutionRequest, proposal: dict[str, Any],
                        observations: list[dict[str, Any]], started: str, clock: float,
                        usage: Mapping[str, Any], metadata: Mapping[str, Any]) -> BlockExecutionResult:
        if proposal["needs_escalation"]:
            return self._result(request, BlockStatus.BLOCKED, started, clock,
                error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,
                    str(proposal["escalation_reason"]), {"needs_escalation": True}),
                usage=usage, metadata={"proposal": proposal, **dict(metadata)})
        contract = request.task_context.node_config.get('leaf_contract')
        if not contract:
            raise ProposalError('INVALID_CONTRACT: worker requires ExecutionLeafContract')
        from cgkn.execution.file_actions import writable_path, candidate_files
        scope = set(candidate_files(self.actions.root,contract))
        scope.update(a['path'] for a in proposal['actions'] if a['action'] in {'write_file','patch_file'})
        protected = request.metadata.get('verified_partial_artifacts', {})
        current_protected = request.metadata.get('protected_existing_artifacts', {})
        for action in proposal['actions']:
            if action['action'] in {'write_file', 'patch_file'}:
                from cgkn.execution.node_effects import guard_effect
                guard_effect(request,'PERSISTENT_ARTIFACT_WRITE')
                normalized = self.actions._path(action['path']).relative_to(self.actions.root).as_posix()
                if not writable_path(contract,normalized):
                    raise PermissionError('write outside leaf target_scope: '+json.dumps({'requested_path':normalized,'allowed_paths':sorted(scope),'legal_action':'write only admitted targets or escalate to Agent for a new bounded capability'}))
                if normalized in protected and not request.task_context.node_config.get('verified_artifact_change_reason'):
                    raise PermissionError('verified partial artifact requires explicit Agent change reason')
                if normalized in current_protected and not request.task_context.node_config.get('verified_artifact_change_reason'):
                    raise PermissionError('current predecessor artifact requires explicit Agent change reason')
        if len(scope)>contract.get('max_candidate_files',128):
            raise PermissionError('candidate file bound exceeded before write')
        if any(len(str(a.get('content',a.get('replace',''))).encode('utf-8'))>2_000_000 for a in proposal['actions']):
            raise PermissionError('candidate action exceeds byte bound')
        originals = {name: (self.actions._path(name).read_bytes() if self.actions._path(name).is_file() else None) for name in scope}
        results = list(observations)
        bounded_receipts = []
        bounded_outputs = None
        if self.patch_policy and any(a['action'] in {'write_file','patch_file'} for a in proposal['actions']):
            bounded_outputs, bounded_receipts = plan_bounded_patches(proposal['actions'], self.actions.root, self.patch_policy)
        try:
            if bounded_outputs is not None:
                for name, content in bounded_outputs.items():
                    self.actions._path(name).write_bytes(content)
                    results.append({'action': 'patch_file', 'path': name, 'bytes': len(content)})
            else:
                for action in proposal['actions']:
                    try:
                        results.append(self.actions.apply(action))
                    except PermissionError:
                        raise
                    except (OSError,RuntimeError) as exc:
                        if action['action'] not in {'read_file','list_files'}:raise
                        results.append({'action':action['action'],'path':action['path'],
                            'status':'FAILED','error_type':type(exc).__name__,'error':str(exc)})
        except Exception:
            for name, content in originals.items():
                path = self.actions._path(name)
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            raise
        modified = [item["path"] for item in results if item["action"] in {"write_file", "patch_file"}]
        return self._result(request, BlockStatus.SUCCEEDED, started, clock,
            outputs={"summary": proposal["summary"], "action_results": results,
                     "modified_files": modified, "expected_outputs": proposal["expected_outputs"]},
            usage=usage,
            metadata={"proposal": proposal, "bounded_patch_receipts": bounded_receipts,
                      **dict(metadata)})

    def cancel(self, project_id, run_id, node_id):
        self._cancelled.add((project_id,run_id,node_id))

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        try:
            from cgkn.orchestration.capability_tree import CapabilityNode
            from cgkn.orchestration.leaf_contract import validate_leaf
            validate_leaf(CapabilityNode(request.node_id,capability_ref=request.component_ref,
                depends_on=request.dependency_result_refs,config=dict(request.task_context.node_config)))
            if not isinstance(self.actions,BoundedFileActions):
                raise ValueError('UNQUALIFIED_MATERIALIZATION_ADAPTER: bounded file contract required')
        except ValueError as exc:
            return self._result(request,BlockStatus.BLOCKED,started,clock,
                error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,str(exc)))
        selected = request.task_context.node_config.get('model_config_id', request.task_context.node_config.get('provider', self.config.model))
        if self.model_configs and selected not in self.model_configs:
            return self._result(request, BlockStatus.FAILED, started, clock, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, 'Unregistered worker provider'))
        route_decision=None
        if self.capability_ledger and self.model_configs:
            cfg=request.task_context.node_config
            route_decision=self.capability_ledger.route(str(cfg.get('task_class',request.component_ref)),self.model_configs,selected,
                operation=cfg.get('operation'),capability_scope={k:cfg.get(k,'UNKNOWN') for k in ('artifact_domain','environment','tool_identity')})
            selected=route_decision['selected_config']
        call_config = self.model_configs.get(selected, self.config)
        context = request.task_context.as_dict()
        prompt = {"node_id": request.node_id, "goal": request.task_context.node_goal, "config": context["node_config"], "dependency_results": context["dependency_results"], "constraints": list(request.task_context.project_constraints), "acceptance": list(request.task_context.acceptance), "allowed_actions": sorted(ALLOWED_ACTIONS)}
        import json
        raw_prompt = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        usage: dict[str, Any] = {}
        completion_calls=[]
        observations: list[dict[str, Any]] = []
        try:
            observations = []
            contract=context['node_config'].get('leaf_contract',{})
            if 'local_process' not in contract.get('effect_domains',()):prompt['allowed_actions'].remove('run_tests')
            # Materialized, verified inputs are real Component inputs, not a
            # suggestion that the model guess upstream storage or interfaces.
            # The existing context envelope still enforces the total budget.
            for name,expected in sorted(contract.get('read_subjects',{}).items()):
                if name not in contract.get('read_scope',()) or name in contract.get('target_scope',()):
                    raise PermissionError('declared dependency input must be read-only and scoped')
                raw=self.actions._path(name).read_bytes()
                import hashlib
                actual=hashlib.sha256(raw).hexdigest()
                if actual!=expected:
                    raise PermissionError('OBJECT_VERSION_MISMATCH: declared dependency input changed')
                try:content=raw.decode('utf-8')
                except UnicodeDecodeError as exc:
                    raise PermissionError('declared source dependency is not UTF-8 text') from exc
                observations.append({'action':'read_file','path':name,'content':content,
                    'sha256':actual,'input_origin':'verified_milestone_dependency'})
            if self.patch_policy:
                import hashlib
                prompt['bounded_patch_policy'] = self.patch_policy
                for name, spec in self.patch_policy.get('files', {}).items():
                    target = self.actions._path(name)
                    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != spec.get('source_sha256'):
                        raise ProposalError('OBJECT_VERSION_MISMATCH: patch policy source changed before dispatch')
                if not set(contract.get('target_scope', ())) <= set(self.patch_policy.get('files', {})):
                    raise ProposalError('PATCH_SCOPE_EXCEEDED: target not authorized before dispatch')
            repair=context['node_config'].get('repair_contract',{})
            if (context['node_config'].get('action_version')==2
                    and (repair.get('strategy_semantics',{}).get('full_file_write') is True or self.patch_policy)):
                # A complete replacement needs the current scoped target as a
                # real input. Existing bounds and path confinement still apply.
                for name in sorted(contract.get('target_scope',())):
                    target=self.actions._path(name)
                    if not target.exists():
                        continue  # New targets have no prior implementation.
                    raw=target.read_bytes()
                    try:content=raw.decode('utf-8')
                    except UnicodeDecodeError as exc:
                        raise PermissionError('repair target is not UTF-8 text') from exc
                    import hashlib
                    observations.append({'action':'read_file','path':name,'content':content,
                        'sha256':hashlib.sha256(raw).hexdigest(),'input_origin':'existing_repair_target'})
            import hashlib
            local_patch_receipts=[]
            last_observation_fingerprint = None
            no_progress_rounds = 0
            for _ in range(self.max_rounds):
                if (request.project_id,request.run_id,request.node_id) in self._cancelled:
                    return self._result(request,BlockStatus.BLOCKED,started,clock,usage=usage,
                        outputs={'action_results':observations},
                        error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,'delegation cancelled; candidate retained'))
                if time.perf_counter()-clock >= request.timeout_seconds:
                    raise TimeoutError('worker delegation deadline reached')
                raw_prompt = json.dumps({**prompt, "observations": observations}, ensure_ascii=False, sort_keys=True)
                from cgkn.providers.recording import recorded_execution
                with recorded_execution(request):
                    from cgkn.execution.node_effects import guard_effect
                    guard_effect(request,'PROVIDER_CALL',resource_usage={'calls':1})
                    from cgkn.protocol.adapters import SemanticWorkerClient
                    from cgkn.protocol.adaptive_context import public_role_resolver
                    from cgkn.protocol.exchange import complete_with_context
                    complete=self.client.complete if isinstance(self.client,SemanticWorkerClient) else lambda **kw:complete_with_context(self.client,resolver=public_role_resolver(json.loads(raw_prompt)),**kw)
                    completion = complete(system="You are a bounded CGKN worker executing the Agent's assigned task. Propose only read/list/write/patch/run_tests actions. Organize implementation and local tests within the admitted component roots or exact target files. Read actions return observations for your next response. Writes continue this delegation. When local_process is granted, use run_tests with a relative candidate test path to obtain real local results, inspect failures, and repair within the admitted scope. Submit a candidate using an empty actions array only when ready; local tests never establish independent acceptance. Do not redefine the project goal or DAG. Return JSON only.", user=raw_prompt, schema_name="cgkn_worker_proposal", schema=scoped_worker_schema(contract,request.node_id), config=call_config)
                completion_calls.append({'model':completion.model,'request_id':completion.request_id,'usage':dict(completion.usage),'routing':dict(completion.routing),'attempts':completion.attempts,'raw_finish_reason':completion.raw_finish_reason})
                usage=dict(completion.usage) | {'model':completion.model,'routing':dict(completion.routing),'request_id':completion.request_id,'completion_calls':completion_calls,'provider_attempts':sum(x['attempts'] for x in completion_calls)}
                for key,alias in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens')]:
                    samples=[x['usage'].get(key,x['usage'].get(alias)) for x in completion_calls]
                    if any(v is not None for v in samples):usage[key]=sum(samples) if all(isinstance(v,(int,float)) for v in samples) else None
                semantic_calls=[call for row in completion_calls for call in row['usage'].get('semantic_calls',[])]
                if semantic_calls:
                    usage.update(semantic_calls=semantic_calls,
                        semantic_decision_attempts=sum(c.get('call_kind')=='semantic_decision_attempt' for c in semantic_calls),
                        schema_repair_attempts=sum(c.get('call_kind')=='schema_repair_attempt' for c in semantic_calls),
                        admission_correction_attempts=sum(c.get('call_kind')=='admission_correction_attempt' for c in semantic_calls))
                proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
                if proposal["needs_escalation"]:
                    from cgkn.providers.finish_reason import finish_disposition
                    return self._apply_proposal(request, proposal, observations, started, clock, usage,
                                                {**finish_disposition(completion.raw_finish_reason),'bounded_patch_receipts':local_patch_receipts})
                if not proposal["actions"]:
                    # A completed no-op is an executor observation, never proof
                    # of a delivered change. The Host's independent progress and
                    # deliverable checks reject writing tasks with no delta and
                    # retain that evidence for the next planning decision.
                    from cgkn.providers.finish_reason import finish_disposition
                    usage.update(context_chars=len(raw_prompt), dependency_count=len(context['dependency_results']))
                    from dataclasses import asdict
                    from cgkn.state.task_feedback import digest
                    usage.update(config_hash=digest(asdict(call_config)), context_hash=digest(raw_prompt),
                                 route_decision=route_decision)
                    return self._apply_proposal(request, proposal, observations, started, clock, usage,
                                                {**finish_disposition(completion.raw_finish_reason),'bounded_patch_receipts':local_patch_receipts})
                before = len(observations)
                file_actions = [a for a in proposal['actions'] if a['action'] != 'run_tests']
                if file_actions:
                    applied = self._apply_proposal(request, {**proposal, 'actions':file_actions},
                        observations, started, clock, usage, {})
                    if not applied.succeeded: return applied
                    observations = applied.as_dict()['outputs']['action_results']
                    local_patch_receipts.extend(applied.metadata.get('bounded_patch_receipts',()))
                for action in proposal['actions']:
                    if action['action'] != 'run_tests': continue
                    from cgkn.execution.file_actions import writable_path
                    target=self.actions._path(action['path'])
                    name=target.relative_to(self.actions.root).as_posix()
                    allowed=(writable_path(contract,name) or name in contract.get('component_roots',()))
                    if not allowed or not target.exists() or name.startswith('-'):
                        raise PermissionError('local test subject must exist within admitted candidate scope')
                    if 'local_process' not in contract['effect_domains']:
                        raise PermissionError('local test subprocess not admitted')
                    from dataclasses import replace
                    from cgkn.executors.local import PythonTestExecutor
                    test_config={'pytest_args':['-q','-p','no:cacheprovider',str(target)], 'cwd':'.'}
                    test_context=replace(request.task_context,node_config=test_config)
                    test_request=replace(request,task_context=test_context,
                        timeout_seconds=max(1,request.timeout_seconds-(time.perf_counter()-clock)))
                    tested=PythonTestExecutor(self.actions.root).execute(test_request)
                    for source,expected in contract.get('read_subjects',{}).items():
                        if hashlib.sha256(self.actions._path(source).read_bytes()).hexdigest()!=expected:
                            raise PermissionError('local test mutated a read-only input')
                    observations.append({'action':'run_tests' ,'path':name,'status':tested.status.value,
                        'outputs':tested.as_dict()['outputs'],'error':tested.error.as_dict() if tested.error else None,
                        'acceptance':'LOCAL_OBSERVATION_ONLY'})
                    if tested.status is BlockStatus.TIMED_OUT or (tested.error and tested.error.details.get('outcome_unknown')):
                        return self._result(request,BlockStatus.BLOCKED,started,clock,usage=usage,
                            outputs={'action_results':observations},
                            error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'local subprocess outcome requires reconciliation',{'outcome_unknown':True}),retryable=False)
                from cgkn.execution.file_actions import candidate_files
                state_hashes={n:hashlib.sha256(self.actions._path(n).read_bytes()).hexdigest()
                    for n in candidate_files(self.actions.root,contract) if self.actions._path(n).is_file()}
                fingerprint = hashlib.sha256(json.dumps({'observations':observations[before:],'files':state_hashes}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                if fingerprint == last_observation_fingerprint:
                    no_progress_rounds += 1
                else:
                    no_progress_rounds = 0
                    last_observation_fingerprint = fingerprint
                if no_progress_rounds >= 2:
                    return self._result(request, BlockStatus.BLOCKED, started, clock,
                        outputs={"action_results": observations},
                        error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,
                                              "NO_LOCAL_PROGRESS: repeated local observations without artifact delta"),
                        usage=usage)
            else:
                return self._result(request, BlockStatus.BLOCKED, started, clock, outputs={"action_results": observations}, error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, "worker observation resource bound reached"),usage=usage)
        except TimeoutError as exc:
            return self._result(request, BlockStatus.TIMED_OUT, started, clock, error=ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), usage=usage, retryable=True)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("PROVIDER_BUDGET_EXHAUSTED"):
                return self._result(request, BlockStatus.BLOCKED, started, clock, usage=usage,
                    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc),
                        {"failure_domain": "BUDGET", "budget_blocked": True,
                         "category": "budget", "outcome_unknown": False}),
                    retryable=False, metadata={"finish_reason": "budget_blocked"})
            from cgkn.protocol.normalization import ContractError
            if isinstance(exc,ContractError):
                calls=[call for row in completion_calls for call in row['usage'].get('semantic_calls',[])]+getattr(exc,'semantic_calls',[])
                measured={'semantic_calls':calls,'semantic_decision_attempts':sum(c.get('call_kind')=='semantic_decision_attempt' for c in calls),
                    'schema_repair_attempts':sum(c.get('call_kind')=='schema_repair_attempt' for c in calls),
                    'admission_correction_attempts':sum(c.get('call_kind')=='admission_correction_attempt' for c in calls),
                    'provider_attempts':sum(c.get('provider_attempts',0) for c in calls)}
                for key,alias in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')]:
                    values=[x['usage'].get(key,x['usage'].get(alias)) for x in calls]
                    measured[key]=sum(values) if values and all(type(v) in (int,float) for v in values) else None
                return self._result(request,BlockStatus.FAILED,started,clock,usage={**usage,**measured},
                    error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,exc.code,{'failure_domain':exc.details.get('failure_domain','HARNESS' if exc.code=='WORKER_REQUIRED_CONTRACT_MISSING' else 'MODEL_OUTPUT'),'protocol_error':exc.as_dict(),'outcome_unknown':False}),
                    metadata={'semantic_protocol':'v1','acceptance':'NOT_INFERRED'},retryable=False)
            from cgkn.providers.gateway_client import GatewayCompletionError
            from cgkn.providers.streaming_sse import StreamError
            from cgkn.providers.finish_reason import finish_disposition
            if isinstance(exc,StreamError):
                return self._result(request,BlockStatus.BLOCKED,started,clock,usage=usage,
                    metadata={**finish_disposition(exc.code,outcome_unknown=exc.outcome_unknown),
                        'raw_partial_response':exc.response},
                    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,exc.code,
                        {'outcome_unknown':exc.outcome_unknown,'failure_domain':'TRANSPORT'}),retryable=False)
            if isinstance(exc,GatewayCompletionError) and exc.category=='schema_validation_failed' and not exc.outcome_unknown:
                completed=getattr(exc,'completed_response',{}) or {}
                measured=dict(completed.get('usage',{}))
                if completed.get('model'):measured['model']=completed['model']
                if completed.get('cgkn_model_identity'):measured['routing']=completed['cgkn_model_identity']
                raw_text = completed.get('output_text') or (completed.get('cgkn_raw_defer') or {}).get('raw_text')
                if raw_text:
                    try:
                        repaired, filled = repair_worker_envelope(parse_json_object(raw_text), request.node_id)
                        proposal = validate_worker_proposal(repaired, request.node_id)
                        if proposal['actions']:
                            raise ProposalError('schema repair cannot terminate a development delegation; preserve candidate and return protocol evidence')
                        return self._apply_proposal(
                            request, proposal, list(observations), started, clock,
                            {**usage, **measured},
                            {**finish_disposition('schema_repair'),
                             'provider_error_category': exc.category,
                             'protocol_repair': {'filled_fields': filled,
                                                 'business_actions_preserved': True},
                             'raw_provider_response': completed})
                    except (ValueError, ProposalError, PermissionError):
                        pass
                return self._result(request,BlockStatus.FAILED,started,clock,
                    error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,str(exc),
                        {'failure_class':'schema','failure_domain':'MODEL_OUTPUT','category':exc.category,'outcome_unknown':False,
                         'missing_fields': _missing_envelope_fields(completed)}),
                    usage={**usage,**measured},retryable=False,
                    metadata={**finish_disposition('schema_incomplete'),'provider_error_category':exc.category,
                        'raw_provider_response':completed})
            if isinstance(exc,GatewayCompletionError) and exc.category=='provider_request_rejected_before_send' and getattr(exc,'provider_dispatched',None) is False:
                return self._result(request,BlockStatus.BLOCKED,started,clock,
                    error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,str(exc),
                        {'failure_class':'input_bound','failure_domain':'HARNESS','category':exc.category,'outcome_unknown':False,'provider_dispatched':False}),
                    usage=usage,retryable=False,metadata={**finish_disposition('local_input_bound'),'provider_error_category':exc.category})
            if isinstance(exc,GatewayCompletionError):
                return self._result(request,BlockStatus.BLOCKED,started,clock,
                    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'NetworkUnavailable',
                        {'failure_class':'network','failure_domain':'TRANSPORT','category':exc.category,'outcome_unknown':exc.outcome_unknown}),
                    usage=usage,retryable=False,metadata={**finish_disposition(
                        exc.category if exc.category.startswith('stream_') else 'provider_error',
                        outcome_unknown=exc.outcome_unknown),'provider_error_category':exc.category})
            code = ExecutionErrorCode.POLICY_BLOCKED if isinstance(exc, PermissionError) else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, (ValueError, ProposalError)) else ExecutionErrorCode.EXECUTION_ERROR
            return self._result(request, BlockStatus.FAILED, started, clock, error=ExecutionError(code, str(exc)), usage=usage, retryable=isinstance(exc, RuntimeError))

    @staticmethod
    def _result(request: BlockExecutionRequest, status: BlockStatus, started: str, clock: float, *, outputs: Mapping[str, Any] | None = None, error: ExecutionError | None = None, usage: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None, retryable: bool = False) -> BlockExecutionResult:
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=outputs or {}, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage or {}, metadata=metadata or {}, retryable=retryable)
