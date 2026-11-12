from __future__ import annotations

import pathlib
import time
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object

from .protocol import ExecutorDescriptor


ALLOWED_ACTIONS = {"read_file", "list_files", "write_file", "patch_file"}
PROTECTED_PARTS = {".git", ".hg", ".svn", ".cgkn-publication.lock"}

WORKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "node_id", "summary", "actions", "expected_outputs", "confidence", "needs_escalation", "escalation_reason"],
    "properties": {
        "schema_version": {"const": "1.0"}, "node_id": {"type": "string"}, "summary": {"type": "string"},
        "actions": {"type": "array", "items": {"oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "read_file"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "list_files"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "content"], "properties": {"action": {"const": "write_file"}, "path": {"type": "string"}, "content": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "find", "replace"], "properties": {"action": {"const": "patch_file"}, "path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}}},
        ]}}, "expected_outputs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"},
    },
}


class ProposalError(ValueError):
    pass


class BoundedFileActions:
    def __init__(self, root: pathlib.Path | str):
        self.root = pathlib.Path(root).resolve()

    def _path(self, value: object) -> pathlib.Path:
        raw = str(value or ".")
        candidate = (self.root / raw).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path escapes project root")
        relative = candidate.relative_to(self.root)
        if any(part.lower() in PROTECTED_PARTS for part in relative.parts):
            raise PermissionError("protected path rejected")
        return candidate

    def apply(self, action: Mapping[str, Any]) -> dict[str, Any]:
        kind = str(action.get("action", ""))
        allowed_fields = {
            "read_file": {"action", "path"}, "list_files": {"action", "path"},
            "write_file": {"action", "path", "content"}, "patch_file": {"action", "path", "find", "replace"},
        }
        if kind not in ALLOWED_ACTIONS or set(action) != allowed_fields.get(kind):
            raise ProposalError(f"invalid or over-broad worker action: {kind}")
        path = self._path(action["path"])
        if kind == "read_file":
            return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "content": path.read_text(encoding="utf-8")}
        if kind == "list_files":
            return {"action": kind, "files": sorted(str(item.relative_to(self.root)).replace("\\", "/") for item in path.rglob("*") if item.is_file())}
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "write_file":
            content = str(action["content"])
        else:
            before = path.read_text(encoding="utf-8")
            find = str(action["find"])
            if not find or before.count(find) != 1:
                raise ProposalError("patch find text must occur exactly once")
            content = before.replace(find, str(action["replace"]), 1)
        path.write_text(content, encoding="utf-8")
        return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "bytes": len(content.encode("utf-8"))}


def validate_worker_proposal(value: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    required = set(WORKER_SCHEMA["required"])
    if set(value) != required or value.get("schema_version") != "1.0" or value.get("node_id") != node_id:
        raise ProposalError("worker proposal has invalid envelope")
    if not isinstance(value.get("actions"), list) or not isinstance(value.get("expected_outputs"), list):
        raise ProposalError("worker proposal arrays are invalid")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ProposalError("worker confidence is invalid")
    for action in value["actions"]:
        if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
            raise ProposalError("worker proposal contains a forbidden action")
        fields = {"read_file": {"action", "path"}, "list_files": {"action", "path"}, "write_file": {"action", "path", "content"}, "patch_file": {"action", "path", "find", "replace"}}
        if set(action) != fields[action["action"]] or any(not isinstance(v, str) for v in action.values()):
            raise ProposalError("worker action fields are invalid; no actions applied")
    if bool(value["needs_escalation"]) and value["actions"]:
        raise ProposalError("escalation proposal cannot contain actions")
    return dict(value)



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

    def __init__(self, project_root: pathlib.Path | str, client: CompletionClient, config: ModelRoleConfig, *, max_rounds: int = 1, capability_ledger=None, semantic_protocol=False, protocol_trace=None, patch_policy=None):
        if config.role != "worker":
            raise ValueError("LLMExecutor requires worker model config")
        if semantic_protocol:
            if not callable(protocol_trace):raise ValueError("semantic protocol requires an audit sink")
            from cgkn.protocol.adapters import SemanticWorkerClient
            client=SemanticWorkerClient(client,protocol_trace)
        self.actions, self.client, self.config = BoundedFileActions(project_root), client, config
        self.resource_claims = {"workspace:" + str(pathlib.Path(project_root).resolve()): "write"}
        self.max_rounds = max_rounds
        self.patch_policy = patch_policy
        self.model_configs = {}
        self.capability_ledger = capability_ledger

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
        try:
            observations = []
            contract=context['node_config'].get('leaf_contract',{})
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
            for _ in range(self.max_rounds):
                raw_prompt = json.dumps({**prompt, "observations": observations}, ensure_ascii=False, sort_keys=True)
                from cgkn.providers.recording import recorded_execution
                with recorded_execution(request):
                    completion = self.client.complete(system="You are a bounded CGKN worker executing the Agent's assigned task. Propose only read/list/write/patch actions, including implementation or test files requested by the Agent. Read actions return observations for your next response. A batch containing writes ends this delegation; return precise outputs for the coordinator to test. Do not redefine the project goal or DAG. Return JSON only.", user=raw_prompt, schema_name="cgkn_worker_proposal", schema=WORKER_SCHEMA, config=call_config)
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
                if self.max_rounds == 1 or proposal["needs_escalation"] or not proposal["actions"] or any(a["action"] in {"write_file", "patch_file"} for a in proposal["actions"]):
                    break
                for action in proposal["actions"]:
                    try:
                        observations.append(self.actions.apply(action))
                    except PermissionError:
                        raise
                    except (OSError, RuntimeError) as exc:
                        # Read/list failures are observations for the next
                        # bounded decision. Never retry a write this way.
                        observations.append({"action":action['action'],"path":action['path'],
                            "status":"FAILED","error_type":type(exc).__name__,"error":str(exc)})
            else:
                return self._result(request, BlockStatus.BLOCKED, started, clock, outputs={"action_results": observations}, error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, "worker observation resource bound reached"),usage=usage)
            usage.update(context_chars=len(raw_prompt),dependency_count=len(context['dependency_results']))
            from dataclasses import asdict
            from cgkn.state.task_feedback import digest
            usage.update(config_hash=digest(asdict(call_config)),context_hash=digest(raw_prompt),route_decision=route_decision)
            proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
            if proposal["needs_escalation"]:
                return self._result(request, BlockStatus.BLOCKED, started, clock, error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, str(proposal["escalation_reason"]), {"needs_escalation": True}), usage=usage, metadata={"proposal": proposal})
            contract = request.task_context.node_config.get('leaf_contract')
            if not contract:
                raise ProposalError('INVALID_CONTRACT: worker requires ExecutionLeafContract')
            scope = set(contract['target_scope'])
            protected = request.metadata.get('verified_partial_artifacts',{})
            current_protected = request.metadata.get('protected_existing_artifacts',{})
            for action in proposal['actions']:
                if action['action'] in {'write_file','patch_file'}:
                    normalized = self.actions._path(action['path']).relative_to(self.actions.root).as_posix()
                    if normalized not in scope:
                        raise PermissionError('write outside leaf target_scope')
                    if normalized in protected and not request.task_context.node_config.get('verified_artifact_change_reason'):
                        raise PermissionError('verified partial artifact requires explicit Agent change reason')
                    if normalized in current_protected and not request.task_context.node_config.get('verified_artifact_change_reason'):
                        raise PermissionError('current predecessor artifact requires explicit Agent change reason')
            # Validate every write before applying any; rollback action failures.
            originals = {name:(self.actions._path(name).read_bytes() if self.actions._path(name).is_file() else None) for name in scope}
            results = list(observations)
            bounded_receipts = []
            bounded_outputs = None
            if self.patch_policy:
                bounded_outputs, bounded_receipts = plan_bounded_patches(proposal['actions'], self.actions.root, self.patch_policy)
            try:
                if bounded_outputs is not None:
                    for name, content in bounded_outputs.items():
                        self.actions._path(name).write_bytes(content)
                        results.append({'action':'patch_file','path':name,'bytes':len(content)})
                else:
                    for action in proposal['actions']: results.append(self.actions.apply(action))
            except Exception:
                for name, content in originals.items():
                    path = self.actions._path(name)
                    if content is None: path.unlink(missing_ok=True)
                    else: path.write_bytes(content)
                raise
            modified = [item["path"] for item in results if item["action"] in {"write_file", "patch_file"}]
            from cgkn.providers.finish_reason import finish_disposition
            return self._result(request, BlockStatus.SUCCEEDED, started, clock, outputs={"summary": proposal["summary"], "action_results": results, "modified_files": modified, "expected_outputs": proposal["expected_outputs"]}, usage=usage, metadata={"proposal": proposal,"bounded_patch_receipts":bounded_receipts,**finish_disposition(completion.raw_finish_reason)})
        except TimeoutError as exc:
            return self._result(request, BlockStatus.TIMED_OUT, started, clock, error=ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), usage=usage, retryable=True)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
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
                return self._result(request,BlockStatus.FAILED,started,clock,
                    error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,str(exc),
                        {'failure_class':'schema','failure_domain':'MODEL_OUTPUT','category':exc.category,'outcome_unknown':False}),
                    usage={**usage,**measured},retryable=False,
                    metadata={**finish_disposition('schema_incomplete'),'provider_error_category':exc.category,
                        'raw_provider_response':completed})
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
