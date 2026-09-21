from __future__ import annotations

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
        self.feed_rows: list[dict[str, Any]] = []
        self._outputs: dict[tuple[str, str], ArtifactRef] = {}
        self._seed_existing_outputs()

    def _seed_existing_outputs(self) -> None:
        for node_id, ports in self.graph.node_outputs.items():
            for port in ports:
                artifact = self.store.latest_produced_by_node(node_id, port)
                if artifact:
                    self._outputs[(node_id, port)] = artifact.ref

    def run(
        self,
        flow_inputs: dict[str, ArtifactRef],
        *,
        node_ids: set[str] | None = None,
        output_overrides: dict[tuple[str, str], ArtifactRef] | None = None,
        raw_source_chars: int = 0,
    ) -> dict[str, Any]:
        output_overrides = output_overrides or {}
        self._outputs.update(output_overrides)
        manifest = self._load_manifest()
        manifest["status"] = "running"
        manifest["inputArtifacts"] = [item.as_dict() for item in flow_inputs.values()]
        self._save_manifest(manifest)
        nodes = {node["id"]: node for node in self.flow["nodes"]}
        try:
            for node_id in self.bundle["topological_order"]:
                if node_ids is not None and node_id not in node_ids:
                    continue
                if any(key[0] == node_id for key in output_overrides):
                    self._record_bypass(node_id, output_overrides)
                    continue
                self._run_node(nodes[node_id], flow_inputs, raw_source_chars)
        except (ModuleExecutionError, ArtifactValidationError, EffectConstraintViolation) as exc:
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
        manifest = self._load_manifest()
        manifest["status"] = "completed"
        manifest["outputArtifacts"] = [item.as_dict() for item in outputs.values()]
        self._save_manifest(manifest)
        report = self._write_feed_report()
        return {"outputs": outputs, "feedForwardReport": report, "runManifest": manifest}

    def _run_node(self, node: dict[str, Any], flow_inputs: dict[str, ArtifactRef], raw_source_chars: int) -> None:
        node_id = node["id"]
        module_ref = node["uses"]
        module = self.compiler.modules[module_ref]
        inputs = self._resolve_inputs(node_id, flow_inputs)
        started = _now()
        start_clock = time.perf_counter()
        diagnostics: list[dict[str, Any]] = []
        fingerprint = ""
        cache_status = "miss"
        context_pack: dict[str, Any] = {}
        output_refs: list[ArtifactRef] = []
        try:
            for port, ref in inputs.items():
                expected = module["ports"]["input"][port]["artifact_type"]
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
                if not self.store.verify_artifact_hash(ref):
                    raise ModuleExecutionError(
                        f"node {node_id} input hash is invalid",
                        [{"code": "CGKN_INPUT_HASH_INVALID", "artifactRef": ref.as_dict()}],
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
            fingerprint = execution_fingerprint(module_ref, node.get("config", {}), inputs.values(), prompt_version, self.flow["policy_ref"])
            cached = self.cache.lookup(node_id, fingerprint, self.store) if implementation.get("cacheable", True) else None
            if cached:
                cache_status = "hit"
                output_refs = cached
            else:
                self.effects.consume_declared(module.get("effects", {}), node_id=node_id, phase=str(node.get("config", {}).get("phase", "")), run=self.run_dir.name)
                contents, execution_meta = self._execute(module, inputs, context_pack, node)
                output_refs = self._materialize_outputs(node, module, inputs, contents, execution_meta)
                if implementation.get("cacheable", True):
                    self.cache.record(node_id, fingerprint, output_refs)
            for ref in inputs.values():
                self.store.register_consumer(ref, node_id)
            for ref in output_refs:
                artifact = self.store.resolve_artifact_ref(ref)
                self._outputs[(node_id, artifact.producer.output_port)] = ref
        except Exception as exc:
            diagnostics = exc.diagnostics if isinstance(exc, ModuleExecutionError) else [{"code": "CGKN_MODULE_EXECUTION_FAILED", "message": str(exc)}]
            checkpoint = self._checkpoint(node_id, started, _now(), "fail", inputs, [], fingerprint, cache_status, diagnostics)
            self._record_checkpoint(checkpoint)
            raise ModuleExecutionError(str(exc), diagnostics) from exc
        duration_ms = int((time.perf_counter() - start_clock) * 1000)
        checkpoint = self._checkpoint(node_id, started, _now(), "pass", inputs, output_refs, fingerprint, cache_status, diagnostics)
        self._record_checkpoint(checkpoint)
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
                "cache": cache_status,
                "durationMs": duration_ms,
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
            return function(payload, {"contextPack": context_pack, "node": node, "module": module, "store": self.store}), {}
        if kind == "script":
            command = implementation.get("command")
            if not isinstance(command, list) or not command:
                raise ModuleExecutionError("script implementation requires a fixed command array")
            completed = subprocess.run(
                [str(item) for item in command],
                cwd=self.root,
                input=json.dumps({"inputs": payload, "contextPack": context_pack}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=int(implementation.get("timeoutSeconds", 60)),
                check=False,
            )
            if completed.returncode != 0:
                raise ModuleExecutionError(f"script module failed with exit code {completed.returncode}")
            return json.loads(completed.stdout), {}
        if kind == "provider":
            if self.provider_executor is None:
                raise ModuleExecutionError("provider implementation has no configured executor")
            request = {
                "moduleRef": f"{module['id']}@{module['version']}",
                "promptVersion": implementation.get("promptVersion"),
                "contextPack": context_pack,
                "inputs": payload,
                "repair": False,
            }
            response = self.provider_executor(request)
            try:
                result = self._provider_payload(response)
                self._validate_output_contents(module, result)
            except (ValueError, ArtifactValidationError) as first_error:
                request["repair"] = True
                request["validationError"] = str(first_error)
                response = self.provider_executor(request)
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

    @staticmethod
    def _provider_payload(response: Any) -> dict[str, Any]:
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            raise ValueError("provider output must be a JSON object")
        return response

    def _validate_output_contents(self, module: dict[str, Any], contents: dict[str, Any]) -> None:
        expected_ports = module.get("ports", {}).get("output", {})
        for port, spec in expected_ports.items():
            if port not in contents:
                raise ArtifactValidationError(f"missing output port: {port}")
            self.compiler.registry.validate_content(spec["artifact_type"], contents[port])
        extra = set(contents) - set(expected_ports)
        if extra:
            raise ArtifactValidationError(f"undeclared output ports: {sorted(extra)}")

    def _materialize_outputs(self, node, module, inputs, contents, execution_meta) -> list[ArtifactRef]:
        self._validate_output_contents(module, contents)
        pending: list[ArtifactInstance] = []
        module_ref = f"{module['id']}@{module['version']}"
        implementation = module["implementation"]
        for port, spec in module["ports"]["output"].items():
            prior = self.store.latest_produced_by_node(node["id"], port, fresh_only=False)
            pending.append(
                ArtifactInstance(
                    id=self.store.allocate_id(spec["artifact_type"]),
                    artifact_type=spec["artifact_type"],
                    run_id=self.run_dir.name,
                    producer=Producer(node["id"], module_ref, port),
                    content=dict(contents[port]),
                    provenance=Provenance(
                        input_artifact_refs=tuple(inputs.values()),
                        source_refs=tuple(str(item) for item in node.get("config", {}).get("sourceRefs", [])),
                        provider=execution_meta.get("provider"),
                        model=execution_meta.get("model"),
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

    @staticmethod
    def _checkpoint(node_id, started, finished, status, inputs, outputs, fingerprint, cache_status, diagnostics):
        return {
            "kind": "GenerationCheckpoint",
            "runId": "",
            "nodeId": node_id,
            "status": status,
            "startedAt": started,
            "finishedAt": finished,
            "inputArtifactRefs": [item.as_dict() for item in inputs.values()],
            "outputArtifactRefs": [item.as_dict() for item in outputs],
            "executionFingerprint": fingerprint,
            "cacheStatus": cache_status,
            "diagnostics": diagnostics,
        }

    def _record_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        checkpoint["runId"] = self.run_dir.name
        path = write_checkpoint(self.run_dir, checkpoint)
        manifest = self._load_manifest()
        row = {"nodeId": checkpoint["nodeId"], "path": path.relative_to(self.run_dir).as_posix(), "status": checkpoint["status"]}
        manifest["nodeCheckpoints"] = [item for item in manifest["nodeCheckpoints"] if item["nodeId"] != checkpoint["nodeId"]]
        manifest["nodeCheckpoints"].append(row)
        self._save_manifest(manifest)

    def _record_bypass(self, node_id: str, overrides: dict[tuple[str, str], ArtifactRef]) -> None:
        refs = [ref for (owner, _), ref in overrides.items() if owner == node_id]
        self.feed_rows.append(
            {"nodeId": node_id, "inputs": [], "outputs": [item.as_dict() for item in refs], "contextChars": 0, "contextTrace": [], "tokenEstimate": 0, "raw_source_chars": 0, "artifact_context_chars": 0, "compression_ratio": None, "cache": "bypass", "durationMs": 0}
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
