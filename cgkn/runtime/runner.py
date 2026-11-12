from __future__ import annotations

from cgkn.telemetry.lean import ACTIVE, OFFLINE_TRIAL, observed, analysis_cost

import importlib
import json
import pathlib
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

from cgkn.artifacts.models import ArtifactInstance, ArtifactRef, Producer, Provenance
from cgkn.artifacts.store import ArtifactStore
from cgkn.artifacts.types import ArtifactValidationError
from cgkn.compiler.artifact_graph import ArtifactFlowCompiler
from cgkn.component import (
    ComponentExecution,
    ComponentResult,
    ExecutionContext,
    ModuleComponentAdapter,
)
from cgkn.component.spec import _thaw

from .cache import ArtifactCache
from .checkpoint import write_checkpoint
from .context import build_context_pack
from .effects import EffectConstraintViolation, EffectCounter
from .fingerprint import execution_fingerprint


class ModuleExecutionError(RuntimeError):
    def __init__(self, message: str, diagnostics: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or [{"code": "CGKN_MODULE_EXECUTION_FAILED", "message": message}]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactModuleRunner:
    """Deterministic orchestration around bounded module implementations."""

    def __init__(
        self,
        root: pathlib.Path,
        run_dir: pathlib.Path,
        flow_ref: str,
        *,
        provider_executor: Callable[[dict[str, Any]], Any] | None = None,
        local_functions: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] | None = None,
        admission_policy=None,
    ):
        self.root = pathlib.Path(root).resolve()
        self.run_dir = pathlib.Path(run_dir).resolve()
        self.flow_ref = flow_ref
        self.compiler = ArtifactFlowCompiler(self.root)
        compiled = self.compiler.compile(flow_ref)
        if not compiled["ok"]:
            raise ModuleExecutionError("artifact flow does not compile", compiled["diagnostics"])
        self.bundle = compiled["compiled_bundle"]
        self.graph = compiled["graph"]
        self.flow = self.bundle["normalized_flow"]
        self.policy = self.compiler.policies[self.flow["policy_ref"]]
        self.store = ArtifactStore(self.run_dir, self.compiler.registry)
        self.cache = ArtifactCache(self.run_dir)
        self.effects = EffectCounter(self.policy.get("effect_constraints", []))
        self.provider_executor = provider_executor
        self.local_functions = local_functions or {}
        self.admission_policy = admission_policy
        self._planned_artifacts = {}
        self.feed_rows: list[dict[str, Any]] = []
        self.component_executions: list[ComponentExecution] = []
        self._outputs: dict[tuple[str, str], ArtifactRef] = {}
        self._seed_existing_outputs()

    def _seed_existing_outputs(self) -> None:
        for node_id, ports in self.graph.node_outputs.items():
            for port in ports:
                artifact = self.store.latest_produced_by_node(node_id, port)
                if artifact:
                    self._outputs[(node_id, port)] = artifact.ref

    @observed(lambda a: a["self"].flow_ref, lambda a: a["self"].run_dir, expose=True)
    def run(
        self,
        flow_inputs: dict[str, ArtifactRef],
        *,
        node_ids: set[str] | None = None,
        output_overrides: dict[tuple[str, str], ArtifactRef] | None = None,
        raw_source_chars: int = 0,
        retry_node: str | None = None,
    ) -> dict[str, Any]:
        output_overrides = output_overrides or {}
        self._outputs.update(output_overrides)
        manifest = self._load_manifest()
        manifest["status"] = "running"
        manifest["inputArtifacts"] = [item.as_dict() for item in flow_inputs.values()]
        self._save_manifest(manifest)
        try:
            self._run_canonical(flow_inputs, node_ids, output_overrides,
                                raw_source_chars, retry_node)
        except Exception as exc:
            manifest = self._load_manifest()
            manifest["status"] = "failed"
            self._save_manifest(manifest)
            if isinstance(exc, ModuleExecutionError):
                raise
            raise ModuleExecutionError(str(exc)) from exc
        outputs: dict[str, ArtifactRef] = {}
        for edge in self.flow.get("edges", []):
            source, target = edge["from"], edge["to"]
            if "flow_output" in target:
                outputs[target["flow_output"]] = self._outputs[(source["node"], source["port"])]
        from cgkn.state import FileRunStore
        from .node_authority import ExecutionAuthority
        canonical=FileRunStore(self.run_dir/'execution')
        authority=ExecutionAuthority(canonical,'artifact-flow','session')
        for ref in outputs.values():
            artifact=self.store.resolve_artifact_ref(ref)
            saved=canonical.load_result('artifact-flow','session',artifact.producer.node_id)
            self.store.resolve_governed(ref,authority=authority,receipt_id=saved.metadata.get('node_commit_receipt_id'))
        manifest = self._load_manifest()
        manifest["status"] = "completed"
        manifest["outputArtifacts"] = [item.as_dict() for item in outputs.values()]
        self._save_manifest(manifest)
        report = self._write_feed_report()
        return {
            "outputs": outputs,
            "componentExecutions": self.component_executions,
            "feedForwardReport": report,
            "runManifest": manifest,
        }

    def _run_canonical(self, flow_inputs, node_ids, overrides, raw_source_chars, retry_node):
        """Translate typed modules; only DAGRunner schedules and commits state.

        ArtifactStore remains the typed value/lineage store, not execution state.
        Its mutable index is not concurrent-safe, so these legacy Components
        explicitly serialize their shared write domain until that is qualified.
        """
        from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
        from cgkn.execution.deliverables import SubjectDeliverableChecker
        from cgkn.executors import ExecutorRegistry
        from cgkn.executors.protocol import ExecutorDescriptor
        from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
        from cgkn.orchestration.execution_dag import compile_tree
        from cgkn.orchestration.leaf_contract import build_leaf_contract
        from cgkn.state import FileRunStore
        from .dag_runner import DAGRunner
        from cgkn.artifacts.hash import content_hash, source_identity
        import hashlib

        owner = self
        nodes = {n['id']: n for n in self.flow['nodes'] if not n.get('structural')}
        selected = set(nodes) if node_ids is None else set(node_ids)
        if not selected <= nodes.keys():
            raise ModuleExecutionError('unknown selected artifact node')
        store = FileRunStore(self.run_dir / 'execution')
        project_id, run_id = 'artifact-flow', 'session'
        leaves = []
        for name in sorted(selected):
            node = nodes[name]
            implementation = self.compiler.modules[node['uses']]['implementation']
            implementation_hash = None
            if implementation['kind'] == 'local_function':
                function = self.local_functions.get(implementation.get('entrypoint')) or self._import_callable(implementation['entrypoint'])
                implementation_hash = source_identity(function)
                if implementation_hash == 'UNKNOWN':
                    raise ModuleExecutionError('local implementation identity unavailable: ' + name)
            ports = self.graph.node_outputs[name]
            if not ports:
                raise ModuleExecutionError('typed module needs explicit deliverable ports: ' + name)
            dependencies = tuple(d for d in self.graph.node_dependencies[name] if d in selected)
            override = any(n == name for n, _ in overrides)
            contract = build_leaf_contract(goal='Materialize declared typed outputs for ' + node['uses'],
                kind='INSPECTION' if override else 'IMPLEMENTATION',
                scope=[name + '/' + port for port in sorted(ports)],
                acceptance=['typed-artifact-integrity'], checker='typed-artifacts',
                output_identity='artifact-module/' + name, effect_domains=['filesystem'],
                executor='artifact.module@1', dependencies=dependencies,
                expected_delta='new typed artifact instances with valid input provenance',
                subject='explicit artifact overrides', expected_observation='fresh schema-valid outputs',
                pass_fail_rule='all declared ports bind current validated artifacts', node_id=name)
            leaves.append(CapabilityNode(name, capability_ref=node['uses'], depends_on=dependencies,
                config={'executor_ref':'artifact.module@1', 'leaf_contract':contract,
                        'parallel_safe':False, 'resources':{'artifact-store':'write'},
                        'module_hash':content_hash(self.compiler.modules[node['uses']]),
                        'implementation_hash':implementation_hash,
                        'input_paths':[str(self.store._path(ref.artifact_instance_id))
                            for key,ref in flow_inputs.items() if any(e['from'].get('flow_input')==key
                            and e['to'].get('node')==name for e in self.flow.get('edges',()))],
                        'node_config':node.get('config', {}),
                        'flow_inputs':{e['from']['flow_input']:flow_inputs[e['from']['flow_input']].as_dict()
                            for e in self.flow.get('edges', ()) if e['to'].get('node') == name
                            and e['from'].get('flow_input') in flow_inputs},
                        'external_dependencies':{d:{p:self._outputs[(d,p)].as_dict()
                            for p in self.graph.node_outputs.get(d,{}) if (d,p) in self._outputs}
                            for d in self.graph.node_dependencies[name] if d not in selected},
                        'overrides':{p:r.as_dict() for (n,p),r in overrides.items() if n == name}}))
        tree = CapabilityTree(self.flow_ref, tuple(leaves))
        # Admission applies additions sequentially; declare each producer before
        # its consumers while retaining the same compiled dependency graph.
        tree = CapabilityTree(tree.goal,tuple(tree.by_id[n] for n in compile_tree(tree).topological_order()))

        def snapshot(contract):
            result = {}
            for subject in contract['target_scope']:
                name, port = subject.split('/', 1)
                ref = owner._outputs.get((name, port))
                if not ref:
                    result[subject] = None
                    continue
                artifact = owner.store.resolve_artifact_ref(ref)
                input_states = [[r.as_dict(), owner.store.resolve_artifact_ref(r).status,
                                 owner.store.verify_artifact_hash(r)]
                                for r in artifact.provenance.input_artifact_refs]
                result[subject] = content_hash([ref.as_dict(), artifact.status,
                                               owner.store.verify_artifact_hash(ref), input_states])
            return result

        def check(request, contract):
            evidence, observations = [], {}
            passed = True
            for subject in contract['target_scope']:
                name, port = subject.split('/', 1)
                ref = owner._outputs.get((name, port))
                if not ref:
                    passed = False; observations[subject] = 'MISSING'; continue
                artifact = owner.store.resolve_artifact_ref(ref)
                owner.store.validate_artifact(artifact)
                valid = (artifact.status == 'fresh' and owner.store.verify_artifact_hash(ref)
                         and artifact.artifact_type == owner.graph.node_outputs[name][port])
                if (name, port) not in overrides:
                    valid = valid and artifact.producer.node_id == name and artifact.producer.output_port == port
                    expected = owner._resolve_inputs(name, flow_inputs)
                    valid = valid and set(artifact.provenance.input_artifact_refs) == set(expected.values())
                passed = passed and valid
                observations[subject] = {'valid':valid, 'ref':ref.as_dict()}
                path = owner.store.artifacts_dir / (artifact.id + '.json')
                evidence.append({'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            # The raw execution receipt exists even when every output is absent.
            if not evidence:
                evidence.append(dict(request.input_values['execution_receipt_ref']))
            return {'passed':passed, 'observed':observations, 'evidence_refs':evidence}

        class ModuleExecutor:
            descriptor = ExecutorDescriptor('artifact.module@1', 'typed_module', tuple(n['uses'] for n in nodes.values()))

            def declared_output_paths(self, request):
                paths=[]
                for port in owner.graph.node_outputs[request.node_id]:
                    artifact_id='ai.'+hashlib.sha256((request.node_id+'|'+request.attempt_id+'|'+port).encode()).hexdigest()
                    owner._planned_artifacts[(request.node_id,port)]=artifact_id
                    paths.append(owner.store._path(artifact_id))
                return paths

            def execute(self, request):
                try:
                    if any(n == request.node_id for n, _ in overrides):
                        owner._record_bypass(request.node_id, overrides)
                    else:
                        owner._run_node(nodes[request.node_id], flow_inputs, raw_source_chars)
                    return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                        node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                        status=BlockStatus.SUCCEEDED,
                        outputs={'artifacts':{p:r.as_dict() for (n,p),r in owner._outputs.items() if n == request.node_id}})
                except ModuleExecutionError as exc:
                    cause = exc
                    unknown = False
                    while cause is not None:
                        unknown = unknown or bool(getattr(cause, 'outcome_unknown', False))
                        cause = cause.__cause__
                    return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                        node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                        status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                            str(exc), {'diagnostics':exc.diagnostics, 'outcome_unknown':unknown}))

        registry = ExecutorRegistry()
        registry.register(ModuleExecutor())
        registry.register(SubjectDeliverableChecker(snapshot, {'typed-artifact-integrity':check}))
        runner = DAGRunner(registry, store, deliverable_checkers={'typed-artifacts':'deliverable.subjects@1'})
        exists = (store.run_dir(project_id, run_id) / 'run_state.json').exists()
        from .node_authority import ExecutionAuthority
        from .governed import admit_declared_tree
        authority=ExecutionAuthority(store,project_id,run_id)
        if retry_node:
            authority.validate_recovery_tree(tree,retry_nodes={retry_node})
        if exists:
            runner._bind_graph(store.load_run(project_id,run_id),compile_tree(tree),
                accept_edits=bool(retry_node),retry_node=retry_node,validate_only=True)
        if self.admission_policy is None:
            if retry_node or not authority.committed_tree():raise ValueError('explicit artifact capability admission policy required')
            authority.validate_tree(tree)
        else:
            admit_declared_tree(authority,tree,policy=self.admission_policy,
                proposal_id='artifact-flow-'+str(len(authority.events())),reason='Explicit typed artifact execution policy',retry_node=retry_node)
        summary = runner.run(project_id=project_id, run_id=run_id, tree=tree, dag=compile_tree(tree),
                             resume=exists, retry_node=retry_node, accept_edits=bool(retry_node))
        for name in summary.reused_nodes:
            self._record_canonical_reuse(nodes[name], flow_inputs, raw_source_chars)
        if summary.status != 'SUCCEEDED':
            failed = [store.load_result(project_id, run_id, n) for n in summary.failed_nodes]
            diagnostics = [d for r in failed if r.error for d in r.error.details.get('diagnostics', ())]
            message = '; '.join(r.error.message for r in failed if r.error) or 'artifact DAG blocked; reconcile or explicitly retry affected node'
            raise ModuleExecutionError(message, diagnostics or None)

    def _record_canonical_reuse(self, node, flow_inputs, raw_source_chars):
        """Compatibility views of a checked canonical reuse; never execute work."""
        inputs = self._resolve_inputs(node['id'], flow_inputs)
        outputs = [self._outputs[(node['id'], p)] for p in self.graph.node_outputs[node['id']]]
        execution = ComponentExecution(node['uses'], node['id'], self.run_dir.name).start(inputs.values())
        module = self.compiler.modules[node['uses']]
        execution.execution_fingerprint = execution_fingerprint(node['uses'], node.get('config', {}), inputs.values(),
            module['implementation'].get('promptVersion'), self.flow['policy_ref'])
        execution.cached(outputs)
        self.component_executions.append(execution)
        self._record_checkpoint(execution.as_checkpoint())
        self.feed_rows.append({'nodeId':node['id'], 'inputs':[r.as_dict() for r in inputs.values()],
            'outputs':[r.as_dict() for r in outputs], 'cache':'hit', 'status':'cached',
            'reuse_authority':'DAGRunner', 'executionId':execution.execution_id})

    def _run_node(self, node: dict[str, Any], flow_inputs: dict[str, ArtifactRef], raw_source_chars: int) -> None:
        node_id = node["id"]
        module_ref = node["uses"]
        module = self.compiler.modules[module_ref]
        component = ModuleComponentAdapter(module, self._execute_component)
        spec = component.spec
        inputs: dict[str, ArtifactRef] = {}
        execution = ComponentExecution(spec.ref, node_id, self.run_dir.name)
        self.component_executions.append(execution)
        context_pack: dict[str, Any] = {}
        output_refs: list[ArtifactRef] = []
        cache_hit = False
        evidence_refs: tuple[str, ...] = ()
        lean_observation = None
        try:
            inputs = self._resolve_inputs(node_id, flow_inputs)
            execution.start(inputs.values())
            missing = [port.name for port in spec.input_ports if port.required and port.name not in inputs]
            if missing:
                raise ModuleExecutionError(
                    f"node {node_id} is missing required inputs: {missing}",
                    [{"code": "CGKN_RUNTIME_REQUIRED_INPUT_MISSING", "ports": missing}],
                )
            for port, ref in inputs.items():
                try:
                    expected = spec.input_port(port).artifact_type
                except KeyError as exc:
                    raise ModuleExecutionError(
                        f"node {node_id} received undeclared input {port}",
                        [{"code": "CGKN_RUNTIME_INPUT_PORT_UNDECLARED", "port": port}],
                    ) from exc
                if not self.store.verify_artifact_hash(ref):
                    raise ModuleExecutionError(
                        f"node {node_id} input hash is invalid",
                        [{"code": "CGKN_INPUT_HASH_INVALID", "artifactRef": ref.as_dict()}],
                    )
                artifact = self.store.resolve_artifact_ref(ref)
                if artifact.artifact_type != expected:
                    raise ModuleExecutionError(
                        f"node {node_id} input {port} expected {expected}, got {artifact.artifact_type}",
                        [{"code": "CGKN_RUNTIME_INPUT_TYPE_MISMATCH", "port": port, "expected": expected, "actual": artifact.artifact_type}],
                    )
                if artifact.status != "fresh" and not node.get("config", {}).get("allow_stale_inputs", False):
                    raise ModuleExecutionError(
                        f"node {node_id} cannot consume {artifact.status} input {artifact.id}",
                        [{"code": "CGKN_STALE_INPUT_BLOCKED", "artifactRef": ref.as_dict(), "status": artifact.status}],
                    )
            context_pack = build_context_pack(
                node,
                module,
                inputs,
                self.store,
                self.policy,
                self._decision_ledger(),
                raw_source_chars=raw_source_chars,
            )
            implementation = module["implementation"]
            prompt_version = implementation.get("promptVersion")
            execution.execution_fingerprint = execution_fingerprint(spec.ref, node.get("config", {}), inputs.values(), prompt_version, self.flow["policy_ref"])
            function = None
            lean_scope=ACTIVE.get()
            if lean_scope and lean_scope.mode!='OFF' and not lean_scope.disabled and implementation.get('lean_input_only') and implementation['kind']=='local_function':
                with analysis_cost():
                    from cgkn.telemetry.lean import artifact_identity
                    from cgkn.telemetry.lean import source_identity
                    function=self.local_functions.get(implementation.get('entrypoint')) or self._import_callable(implementation['entrypoint'])
                    lean_observation={'semantic_identity':artifact_identity(module,node,inputs,function,self.flow['policy_ref']),
                        'pure_inputs':not any(module.get('effects',{}).values()),
                        'implementation_hash':source_identity(function),
                        'component_contract_hash':__import__('cgkn.artifacts.hash',fromlist=['content_hash']).content_hash(module),
                        'protections':module.get('metadata',{}).get('lean_protections',[])}
            # Only DAGRunner can reuse a committed execution. A cache index is
            # not authority to adopt old bytes into a newly issued Permit.
            cached = None
            shared = None
            if not cached and function and lean_observation and (lean_scope.mode == 'AUTO_QUALIFIED' or OFFLINE_TRIAL.get()):
                from cgkn.telemetry.lean_policy import artifact_reuse
                with analysis_cost():
                    shared=artifact_reuse(self,module,node,inputs,lean_observation['semantic_identity'],function)
            if cached:
                output_refs = cached
                cache_hit = True
            elif shared is not None:
                output_refs=self._materialize_outputs(node,spec,module,inputs,ComponentResult(output_contents=shared))
                self.cache.record(node_id,execution.execution_fingerprint,output_refs)
                cache_hit=True
            else:
                self.effects.consume_declared(dict(spec.effects), node_id=node_id, phase=str(node.get("config", {}).get("phase", "")), run=self.run_dir.name)
                execution.effects_summary = dict(spec.effects)
                result = component.execute(
                    ExecutionContext(run_id=self.run_dir.name, node=node, context_pack=context_pack),
                    inputs,
                )
                output_refs = self._materialize_outputs(node, spec, module, inputs, result)
                if implementation.get("cacheable", True):
                    self.cache.record(node_id, execution.execution_fingerprint, output_refs)
                evidence_refs = result.evidence_refs
            for ref in inputs.values():
                self.store.register_consumer(ref, node_id)
            for ref in output_refs:
                artifact = self.store.resolve_artifact_ref(ref)
                self._outputs[(node_id, artifact.producer.output_port)] = ref
            if cache_hit:
                execution.cached(output_refs)
            else:
                execution.succeed(output_refs, evidence_refs=evidence_refs)
        except Exception as exc:
            diagnostics = exc.diagnostics if isinstance(exc, ModuleExecutionError) else [{"code": "CGKN_MODULE_EXECUTION_FAILED", "message": str(exc)}]
            if execution.status.value == "pending":
                execution.start(inputs.values())
            execution.fail(diagnostics)
            self._record_checkpoint(execution.as_checkpoint(), lean_observation)
            raise ModuleExecutionError(str(exc), diagnostics) from exc
        self._record_checkpoint(execution.as_checkpoint(), lean_observation)
        metrics = context_pack.get("metrics", {})
        self.feed_rows.append(
            {
                "nodeId": node_id,
                "inputs": [item.as_dict() for item in inputs.values()],
                "outputs": [item.as_dict() for item in output_refs],
                "contextChars": metrics.get("contextChars", 0),
                "contextTrace": context_pack.get("trace", []),
                "tokenEstimate": metrics.get("tokenEstimate", 0),
                "raw_source_chars": metrics.get("raw_source_chars", 0),
                "artifact_context_chars": metrics.get("artifact_context_chars", 0),
                "compression_ratio": metrics.get("compression_ratio"),
                "executionId": execution.execution_id,
                "componentRef": execution.component_ref,
                "status": execution.status.value,
                "cache": execution.cache_status,
                "durationMs": execution.duration_ms,
            }
        )

    def _resolve_inputs(self, node_id: str, flow_inputs: dict[str, ArtifactRef]) -> dict[str, ArtifactRef]:
        result: dict[str, ArtifactRef] = {}
        for edge in self.flow.get("edges", []):
            target = edge["to"]
            if target.get("node") != node_id:
                continue
            source = edge["from"]
            if "flow_input" in source:
                if source["flow_input"] not in flow_inputs:
                    raise ModuleExecutionError(f"flow input is not bound: {source['flow_input']}")
                result[target["port"]] = flow_inputs[source["flow_input"]]
            else:
                key = (source["node"], source["port"])
                ref = self._outputs.get(key)
                if not ref:
                    artifact = self.store.latest_produced_by_node(*key)
                    ref = artifact.ref if artifact else None
                if not ref:
                    raise ModuleExecutionError(f"upstream artifact is not available: {source['node']}.{source['port']}")
                result[target["port"]] = ref
        return result

    def _execute(self, module, inputs, context_pack, node):
        implementation = module["implementation"]
        kind = implementation["kind"]
        payload = {port: self.store.resolve_artifact_ref(ref).content for port, ref in inputs.items()}
        entrypoint = str(implementation.get("entrypoint", ""))
        if kind in {"local_function", "composite"}:
            function = self.local_functions.get(entrypoint) or self._import_callable(entrypoint)
            context = {} if implementation.get('lean_input_only') else {"contextPack": context_pack, "node": node, "module": module, "store": self.store}
            return function(payload, context), {}
        if kind == "script":
            from cgkn.execution.node_effects import perform_scoped_effect
            command = implementation.get("command")
            if not isinstance(command, list) or not command:
                raise ModuleExecutionError("script implementation requires a fixed command array")
            completed = perform_scoped_effect('EXTERNAL_SUBPROCESS',lambda:subprocess.run(
                [str(item) for item in command],
                cwd=self.root,
                input=json.dumps({"inputs": payload, "contextPack": context_pack}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=int(implementation.get("timeoutSeconds", 60)),
                check=False,
            ))
            if completed.returncode != 0:
                raise ModuleExecutionError(f"script module failed with exit code {completed.returncode}")
            return json.loads(completed.stdout), {}
        if kind == "provider":
            from cgkn.execution.node_effects import perform_scoped_effect
            if self.provider_executor is None:
                raise ModuleExecutionError("provider implementation has no configured executor")
            request = {
                "moduleRef": f"{module['id']}@{module['version']}",
                "promptVersion": implementation.get("promptVersion"),
                "contextPack": context_pack,
                "inputs": payload,
                "repair": False,
            }
            response = perform_scoped_effect('PROVIDER_CALL',lambda:self.provider_executor(request),resource_usage={'calls':1})
            try:
                result = self._provider_payload(response)
                self._validate_output_contents(module, result)
            except (ValueError, ArtifactValidationError) as first_error:
                request["repair"] = True
                request["validationError"] = str(first_error)
                response = perform_scoped_effect('PROVIDER_CALL',lambda:self.provider_executor(request),resource_usage={'calls':1})
                try:
                    result = self._provider_payload(response)
                    self._validate_output_contents(module, result)
                except (ValueError, ArtifactValidationError) as second_error:
                    raise ModuleExecutionError(
                        "provider output remained schema-invalid after one bounded repair",
                        [{"code": "CGKN_PROVIDER_OUTPUT_INVALID", "message": str(second_error)}],
                    ) from second_error
            return result, {
                "provider": str(implementation.get("provider", "configured")),
                "model": implementation.get("model"),
            }
        raise ModuleExecutionError(f"unsupported module implementation kind: {kind}")

    def _execute_component(self, module, inputs, context: ExecutionContext) -> ComponentResult:
        contents, metadata = self._execute(module, inputs, dict(context.context_pack), dict(context.node))
        return ComponentResult(output_contents=contents, metadata=metadata)

    @staticmethod
    def _provider_payload(response: Any) -> dict[str, Any]:
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            raise ValueError("provider output must be a JSON object")
        return response

    def _validate_output_contents(self, module: dict[str, Any], contents: dict[str, Any]) -> None:
        spec = ModuleComponentAdapter(module).spec
        self._validate_component_outputs(spec, contents)

    def _validate_component_outputs(self, spec, contents: dict[str, Any]) -> None:
        expected_ports = {port.name: port for port in spec.output_ports}
        for name, port in expected_ports.items():
            if name not in contents:
                raise ArtifactValidationError(f"missing output port: {name}")
            self.compiler.registry.validate_content(port.artifact_type, contents[name])
        extra = set(contents) - set(expected_ports)
        if extra:
            raise ArtifactValidationError(f"undeclared output ports: {sorted(extra)}")

    def _materialize_outputs(self, node, spec, module, inputs, result: ComponentResult) -> list[ArtifactRef]:
        contents = _thaw(result.output_contents)
        self._validate_component_outputs(spec, contents)
        pending: list[ArtifactInstance] = []
        module_ref = spec.ref
        implementation = module["implementation"]
        for port in spec.output_ports:
            prior = self.store.latest_produced_by_node(node["id"], port.name, fresh_only=False)
            pending.append(
                ArtifactInstance(
                    id=self._planned_artifacts[(node['id'],port.name)],
                    artifact_type=port.artifact_type,
                    run_id='session',
                    producer=Producer(node["id"], module_ref, port.name),
                    content=dict(contents[port.name]),
                    provenance=Provenance(
                        input_artifact_refs=tuple(inputs.values()),
                        source_refs=tuple(str(item) for item in node.get("config", {}).get("sourceRefs", [])),
                        provider=result.metadata.get("provider"),
                        model=result.metadata.get("model"),
                        prompt_version=implementation.get("promptVersion"),
                    ),
                    supersedes=prior.id if prior else None,
                )
            )
        for artifact in pending:
            self.store.validate_artifact(artifact)
        return [self.store.write_artifact(artifact) for artifact in pending]

    @staticmethod
    def _import_callable(entrypoint: str):
        if ":" not in entrypoint:
            raise ModuleExecutionError(f"invalid local function entrypoint: {entrypoint}")
        module_name, function_name = entrypoint.split(":", 1)
        function = getattr(importlib.import_module(module_name), function_name, None)
        if not callable(function):
            raise ModuleExecutionError(f"local function entrypoint is not callable: {entrypoint}")
        return function

    def _record_checkpoint(self, checkpoint: dict[str, Any], lean_observation=None) -> None:
        checkpoint["runId"] = self.run_dir.name
        # Keep each original observation before updating the compatibility view.
        history = self.run_dir / 'component_receipts' / (checkpoint['executionId'] + '.json')
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open('x', encoding='utf-8') as handle:
            json.dump(checkpoint, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        path = write_checkpoint(self.run_dir, checkpoint)
        manifest = self._load_manifest()
        row = {"nodeId": checkpoint["nodeId"], "path": path.relative_to(self.run_dir).as_posix(), "status": checkpoint["status"]}
        manifest["nodeCheckpoints"] = [item for item in manifest["nodeCheckpoints"] if item["nodeId"] != checkpoint["nodeId"]]
        manifest["nodeCheckpoints"].append(row)
        self._save_manifest(manifest)
        try:
            with analysis_cost():
                from cgkn.telemetry.lean import observe_artifact
                observe_artifact(self,checkpoint,lean_observation)
        except Exception as exc:
            __import__('logging').getLogger(__name__).error('LEAN_OBSERVATION_FAILED: %s',type(exc).__name__)

    def _record_bypass(self, node_id: str, overrides: dict[tuple[str, str], ArtifactRef]) -> None:
        refs = [ref for (owner, _), ref in overrides.items() if owner == node_id]
        node = next(item for item in self.flow["nodes"] if item["id"] == node_id)
        execution = ComponentExecution(node["uses"], node_id, self.run_dir.name).bypass(refs)
        self.component_executions.append(execution)
        self._record_checkpoint(execution.as_checkpoint())
        self.feed_rows.append(
            {"nodeId": node_id, "executionId": execution.execution_id, "componentRef": execution.component_ref, "status": execution.status.value, "inputs": [], "outputs": [item.as_dict() for item in refs], "contextChars": 0, "contextTrace": [], "tokenEstimate": 0, "raw_source_chars": 0, "artifact_context_chars": 0, "compression_ratio": None, "cache": "bypass", "durationMs": 0}
        )

    def _manifest_path(self) -> pathlib.Path:
        return self.run_dir / "run_manifest.json"

    def _load_manifest(self) -> dict[str, Any]:
        path = self._manifest_path()
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {
            "kind": "ArtifactFlowRunManifest",
            "runId": self.run_dir.name,
            "flowRef": self.flow_ref,
            "policyRef": self.flow.get("policy_ref", ""),
            "startedAt": _now(),
            "status": "created",
            "inputArtifacts": [],
            "outputArtifacts": [],
            "nodeCheckpoints": [],
        }

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_feed_report(self) -> dict[str, Any]:
        report = {"kind": "FeedForwardReport", "runId": self.run_dir.name, "flowRef": self.flow_ref, "nodes": self.feed_rows}
        (self.run_dir / "feed_forward_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    def _decision_ledger(self) -> dict[str, Any]:
        path = self.run_dir / "decision_ledger.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"decisions": []}
