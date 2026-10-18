from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import pathlib
import shutil
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.application.materialization import materialize_json

from .contracts import CapabilityBuildReceipt, CapabilityPackage, CapabilityRisk, CapabilitySpec
from .lifecycle_contracts import ActionDecision, FailureDomain, ProviderAttemptReceipt, RecommendedAction
from .public_network import PublicNetworkClient


def _slug(ref: str) -> str:
    return ref.replace("@", "-").replace(".", "-")


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class CapabilityStore:
    def __init__(self, root: pathlib.Path | str):
        self.root = pathlib.Path(root).resolve()

    def put(self, package: CapabilityPackage) -> pathlib.Path:
        source = pathlib.Path(package.candidate_path).resolve()
        admission = json.loads((source / "admission.json").read_text(encoding="utf-8"))
        if admission.get("status") != "ADMITTED" or admission.get("source_hash") != package.source_hash:
            raise ValueError("only an admitted, hash-matched capability package may enter the store")
        target = self.root / _slug(package.spec.ref)
        if target.exists():
            raise FileExistsError(f"capability package already stored: {package.spec.ref}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        return target

    def path_for(self, capability_ref: str) -> pathlib.Path:
        return self.root / _slug(capability_ref)

    def contains(self, capability_ref: str) -> bool:
        path = self.path_for(capability_ref)
        if not (path / "admission.json").is_file() or not (path / "capability.json").is_file():
            return False
        admission = json.loads((path / "admission.json").read_text(encoding="utf-8"))
        return admission.get("status") == "ADMITTED" and admission.get("capability_ref") == capability_ref

    def package_metadata(self, capability_ref: str) -> dict[str, Any]:
        path = self.path_for(capability_ref)
        if not self.contains(capability_ref) or not (path / "executor.py").is_file():
            raise ValueError(f"CAPABILITY_DEPENDENCY_MISSING: {capability_ref}")
        spec = CapabilitySpec.from_dict(json.loads((path / "capability.json").read_text(encoding="utf-8")))
        admission = json.loads((path / "admission.json").read_text(encoding="utf-8"))
        package_hash = "sha256:" + hashlib.sha256((path / "executor.py").read_bytes()).hexdigest()
        if admission.get("source_hash") != package_hash:
            raise ValueError(f"DEPENDENCY_HASH_DRIFT: {capability_ref}")
        contract_hash = _canonical_hash({"input_schema": dict(spec.input_schema), "output_schema": dict(spec.output_schema)})
        return {
            "capability_ref": capability_ref,
            "version_constraint": f"=={spec.version}",
            "resolved_version": spec.version,
            "package_hash": package_hash,
            "contract_hash": contract_hash,
            "risk": spec.risk.value,
            "dependencies": list(spec.allowed_dependencies),
        }

    def resolve_dependency_manifest(self, spec: CapabilitySpec) -> list[dict[str, Any]]:
        self.validate_dependency_graph(spec)
        return [self.package_metadata(ref) for ref in spec.allowed_dependencies]

    def validate_dependency_graph(self, prospective: CapabilitySpec, *, enforce_risk: bool = True) -> tuple[str, ...]:
        graph: dict[str, tuple[str, ...]] = {prospective.ref: prospective.allowed_dependencies}
        risks: dict[str, CapabilityRisk] = {prospective.ref: prospective.risk}

        def load(ref: str) -> None:
            if ref in graph:
                return
            metadata = self.package_metadata(ref)
            graph[ref] = tuple(str(item) for item in metadata["dependencies"])
            risks[ref] = CapabilityRisk(str(metadata["risk"]))
            for child in graph[ref]:
                load(child)

        for dependency in prospective.allowed_dependencies:
            load(dependency)

        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(ref: str) -> None:
            if ref in visiting:
                raise ValueError(f"DEPENDENCY_CYCLE: {ref}")
            if ref in visited:
                return
            visiting.add(ref)
            for child in graph.get(ref, ()):
                visit(child)
            visiting.remove(ref)
            visited.add(ref)
            if ref != prospective.ref:
                ordered.append(ref)

        visit(prospective.ref)
        network_risks = {CapabilityRisk.READ_ONLY_PUBLIC_NETWORK, CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE}
        if enforce_risk and any(risks.get(ref) in network_risks for ref in ordered) and prospective.risk is not CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE:
            raise ValueError("INVALID_COMPOSITE_RISK: dependency graph includes public-network capability")
        return tuple(ordered)


@dataclass(frozen=True)
class CapabilityRuntimeContext:
    network_public: Any
    capabilities: Any


class _BoundCapabilityInvoker:
    def __init__(self, runtime: "StoredCapabilityRuntime", allowed: tuple[str, ...], stack: tuple[str, ...]):
        self._runtime, self._allowed, self._stack = runtime, frozenset(allowed), stack

    def invoke(self, capability_ref: str, value: Any) -> Any:
        if capability_ref not in self._allowed:
            raise PermissionError(f"undeclared capability dependency: {capability_ref}")
        return self._runtime.invoke(capability_ref, value, self._stack)

    def execute(self, capability_ref: str, value: Any) -> Any:
        return self.invoke(capability_ref, value)


class StoredCapabilityRuntime:
    """Loads only admitted, hash-matched packages and binds declared dependencies."""

    def __init__(self, store: CapabilityStore, *, provider_id: str, network_public: Any | None = None):
        self.store = store
        self.provider_id = provider_id
        self.network_public = network_public or PublicNetworkClient()

    def context_for(self, spec: CapabilitySpec, stack: tuple[str, ...] = ()) -> CapabilityRuntimeContext:
        return CapabilityRuntimeContext(self.network_public, _BoundCapabilityInvoker(self, spec.allowed_dependencies, stack))

    def invoke(self, capability_ref: str, value: Any, stack: tuple[str, ...] = ()) -> Any:
        if capability_ref in stack:
            raise RuntimeError("capability dependency cycle detected")
        root = self.store.path_for(capability_ref)
        admission = json.loads((root / "admission.json").read_text(encoding="utf-8"))
        spec = CapabilitySpec.from_dict(json.loads((root / "capability.json").read_text(encoding="utf-8")))
        source_hash = "sha256:" + hashlib.sha256((root / "executor.py").read_bytes()).hexdigest()
        if admission.get("status") != "ADMITTED" or admission.get("source_hash") != source_hash:
            raise ValueError("stored capability admission or source hash mismatch")
        for pinned in admission.get("dependency_manifest", []):
            current = self.store.package_metadata(str(pinned.get("capability_ref", "")))
            if current["package_hash"] != pinned.get("package_hash") or current["contract_hash"] != pinned.get("contract_hash"):
                raise ValueError(f"BLOCK_REVALIDATION_REQUIRED: {pinned.get('capability_ref', '')}")
        package = CapabilityPackage(spec, str(root), spec.ref, f"generated.{spec.ref}", source_hash, ("tests/test_capability.py",))
        executor = GeneratedCapabilityExecutor(package, runtime_context=self.context_for(spec, stack + (capability_ref,)))
        request = BlockExecutionRequest("capability-runtime", "nested", "attempt-1", spec.ref, package.component_ref, package.executor_ref, TaskContext(f"Invoke {spec.ref}", acceptance=spec.acceptance), {"value": value}, timeout_seconds=10)
        result = executor.execute(request)
        if not result.succeeded:
            raise RuntimeError(result.error.message if result.error else "capability execution failed")
        return materialize_json(result.outputs.get("result"))


class GeneratedCapabilityExecutor:
    def __init__(self, package: CapabilityPackage, *, runtime_context: CapabilityRuntimeContext | None = None):
        self.package = package
        self.runtime_context = runtime_context
        self.descriptor = ExecutorDescriptor(package.executor_ref, "generated_python", (package.component_ref,), (), True, False, "candidate_sandbox")
        module_path = pathlib.Path(package.candidate_path) / "executor.py"
        module_spec = importlib.util.spec_from_file_location("cgkn_candidate_" + _slug(package.spec.ref), module_path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot load candidate executor: {module_path}")
        self.module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.module)
        if not callable(getattr(self.module, "execute", None)):
            raise TypeError("candidate must expose execute(value)")

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        try:
            value = materialize_json(request.input_values.get("value"))
            parameter_count = len(inspect.signature(self.module.execute).parameters)
            if parameter_count == 1:
                output = self.module.execute(value)
            elif parameter_count == 2 and self.runtime_context is not None:
                output = self.module.execute(value, self.runtime_context)
            else:
                raise TypeError("candidate execute must accept value or value plus bounded runtime context")
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs={"result": output}, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))


class _ExampleNetwork:
    def __init__(self, response: Any):
        self.response = response

    def get(self, url: str) -> Any:
        return self.response

    def head(self, url: str) -> Any:
        return self.response


class _ExampleDependencies:
    def __init__(self, results: Any):
        self.results = dict(results or {})
        self.offsets: dict[str, int] = {}

    def invoke(self, capability_ref: str, value: Any) -> Any:
        result = self.results[capability_ref]
        if isinstance(result, list):
            if not result:
                return result
            index = self.offsets.get(capability_ref, 0)
            if index >= len(result):
                raise IndexError(f"no example dependency result remaining: {capability_ref}")
            self.offsets[capability_ref] = index + 1
            return result[index]
        return result

    def execute(self, capability_ref: str, value: Any) -> Any:
        return self.invoke(capability_ref, value)


@dataclass(frozen=True)
class CandidateGenerationResult:
    source_path: str | None
    provider_receipt: ProviderAttemptReceipt
    failure_domain: FailureDomain | None = None
    error: str = ""


class CapabilityBuilderService:
    """Compatibility facade plus bounded Provider generation/repair adapters.

    Validation, action selection, admission, installation, and resume are owned by
    CapabilityBuildLifecycleService.  This class never turns validation failure
    directly into a Provider call.
    """

    def __init__(self, client: CompletionClient, config: ModelRoleConfig, *, provider_id: str, mode: str, store: CapabilityStore):
        if config.role != "worker" or config.model != provider_id or mode not in {"SELECTED", "SINGLE_PROVIDER_MODE"}:
            raise ValueError("capability builder requires one frozen worker route")
        self.client, self.config, self.provider_id, self.mode, self.store = client, config, provider_id, mode, store

    def build(self, candidate_root: pathlib.Path | str, spec: CapabilitySpec) -> CapabilityBuildReceipt:
        from .lifecycle import CapabilityBuildLifecycleService

        return CapabilityBuildLifecycleService(self, self.store).build(candidate_root, spec)

    def generate_candidate(
        self,
        staging_root: pathlib.Path | str,
        spec: CapabilitySpec,
        *,
        route_snapshot_hash: str,
        operation: str = "GENERATION",
        failure_evidence: Mapping[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        """Perform exactly one Provider operation and return an unpersisted source tree."""
        root = pathlib.Path(staging_root).resolve()
        if root.exists():
            raise FileExistsError(f"generation staging path already exists: {root}")
        self._scaffold(root, spec)
        started_at, attempt_id = utc_now(), f"provider.{uuid.uuid4().hex}"
        try:
            completion = self.client.complete(
                system="You implement one bounded Python capability. Patch only executor.py, use only the standard library and the supplied runtime contract, preserve the required execute signature, and return JSON only.",
                user=json.dumps(self._prompt(root, spec, json.dumps(dict(failure_evidence or {}), ensure_ascii=False, sort_keys=True)), ensure_ascii=False, sort_keys=True),
                schema_name="capability_candidate_patch", schema=WORKER_SCHEMA, config=self.config,
            )
            proposal = validate_worker_proposal(parse_json_object(completion.text), spec.ref)
            if proposal["needs_escalation"]:
                raise ValueError(str(proposal["escalation_reason"]))
            transaction = ScopedFileTransaction(root, WorkerScope(("executor.py", "tests/test_capability.py", "capability.json"), ("executor.py",), protected_paths=("admission.json",), max_actions=1, max_write_files=1, allow_create=False, allow_patch=True))
            transaction.apply(proposal["actions"])
            usage = dict(completion.usage)
            receipt = ProviderAttemptReceipt(
                attempt_id, operation, self.provider_id, str(completion.model), str(completion.request_id),
                str(completion.request_id), route_snapshot_hash, started_at, utc_now(), "PASS", "", False,
                {}, usage, usage.get("estimated_cost", "UNKNOWN"), False,
            )
            return CandidateGenerationResult(str(root), receipt)
        except Exception as exc:
            name = type(exc).__name__.upper()
            domain = FailureDomain.PROVIDER_TIMEOUT if "TIMEOUT" in name or "TIMEOUT" in str(exc).upper() else FailureDomain.PROVIDER_SCHEMA_FAILURE if isinstance(exc, (ValueError, json.JSONDecodeError)) else FailureDomain.PROVIDER_TRANSPORT_FAILURE
            shutil.rmtree(root, ignore_errors=True)
            receipt = ProviderAttemptReceipt(
                attempt_id, operation, self.provider_id, self.config.model, "", "", route_snapshot_hash,
                started_at, utc_now(), "FAIL", domain.value, True, {}, {}, "UNKNOWN", False,
            )
            return CandidateGenerationResult(None, receipt, domain, f"{type(exc).__name__}: {exc}")

    def repair_candidate(
        self,
        parent_source: pathlib.Path | str,
        staging_root: pathlib.Path | str,
        spec: CapabilitySpec,
        *,
        route_snapshot_hash: str,
        failure_evidence: Mapping[str, Any],
        decision: ActionDecision,
    ) -> CandidateGenerationResult:
        if decision.action is not RecommendedAction.REPAIR_CANDIDATE:
            raise PermissionError("ACTION_POLICY_IS_THE_ONLY_REPAIR_AUTHORITY")
        source = pathlib.Path(parent_source).resolve()
        staging = pathlib.Path(staging_root).resolve()
        if staging.exists():
            raise FileExistsError(staging)
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "admission.json"))
        return self._complete_existing(staging, spec, route_snapshot_hash, failure_evidence)

    def _complete_existing(self, root: pathlib.Path, spec: CapabilitySpec, route_snapshot_hash: str, failure_evidence: Mapping[str, Any]) -> CandidateGenerationResult:
        started_at, attempt_id = utc_now(), f"provider.{uuid.uuid4().hex}"
        try:
            completion = self.client.complete(
                system="Repair one bounded Python capability. Patch only executor.py and return JSON only.",
                user=json.dumps(self._prompt(root, spec, json.dumps(dict(failure_evidence), ensure_ascii=False, sort_keys=True)), ensure_ascii=False, sort_keys=True),
                schema_name="capability_candidate_patch", schema=WORKER_SCHEMA, config=self.config,
            )
            proposal = validate_worker_proposal(parse_json_object(completion.text), spec.ref)
            if proposal["needs_escalation"]:
                raise ValueError(str(proposal["escalation_reason"]))
            transaction = ScopedFileTransaction(root, WorkerScope(("executor.py", "tests/test_capability.py", "capability.json"), ("executor.py",), protected_paths=("admission.json",), max_actions=1, max_write_files=1, allow_create=False, allow_patch=True))
            transaction.apply(proposal["actions"])
            usage = dict(completion.usage)
            receipt = ProviderAttemptReceipt(attempt_id, "REPAIR", self.provider_id, str(completion.model), str(completion.request_id), str(completion.request_id), route_snapshot_hash, started_at, utc_now(), "PASS", "", False, {}, usage, usage.get("estimated_cost", "UNKNOWN"), False)
            return CandidateGenerationResult(str(root), receipt)
        except Exception as exc:
            name = type(exc).__name__.upper()
            domain = FailureDomain.PROVIDER_TIMEOUT if "TIMEOUT" in name or "TIMEOUT" in str(exc).upper() else FailureDomain.PROVIDER_SCHEMA_FAILURE if isinstance(exc, (ValueError, json.JSONDecodeError)) else FailureDomain.PROVIDER_TRANSPORT_FAILURE
            shutil.rmtree(root, ignore_errors=True)
            receipt = ProviderAttemptReceipt(attempt_id, "REPAIR", self.provider_id, self.config.model, "", "", route_snapshot_hash, started_at, utc_now(), "FAIL", domain.value, True, {}, {}, "UNKNOWN", False)
            return CandidateGenerationResult(None, receipt, domain, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _prompt(root: pathlib.Path, spec: CapabilitySpec, failure: str) -> dict[str, Any]:
        runtime_contract = {
            "risk": spec.risk.value,
            "execute_signature": "execute(value, ctx)" if (spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or spec.allowed_dependencies) else "execute(value)",
            "network_api": "ctx.network_public.get(url) or head(url); never import or call network libraries directly" if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK else "unavailable",
            "declared_dependencies": list(spec.allowed_dependencies),
            "dependency_api": "ctx.capabilities.invoke(capability_ref, value) or execute(capability_ref, value); invoke every declared ref and no undeclared ref" if spec.allowed_dependencies else "unavailable",
        }
        return {"node_id": spec.ref, "goal": spec.goal, "requirements": list(spec.acceptance), "runtime_contract": runtime_contract, "allowed_paths": ["executor.py"], "current_sources": {"executor.py": (root / "executor.py").read_text(encoding="utf-8")}, "examples": [dict(item) for item in spec.examples], "failure_evidence": failure, "allowed_actions": ["patch_file"]}

    @staticmethod
    def _scaffold(root: pathlib.Path, spec: CapabilitySpec) -> None:
        root.mkdir(parents=True); (root / "tests").mkdir()
        (root / "executor.py").write_text('"""Generated capability candidate."""\n\ndef execute(value):\n    raise NotImplementedError("candidate not implemented")\n', encoding="utf-8")
        (root / "capability.json").write_text(json.dumps(spec.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        contextual = spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or bool(spec.allowed_dependencies)
        rows = ["from executor import execute", ""]
        if contextual:
            rows.extend([
                "from types import SimpleNamespace", "",
                "class _Network:",
                "    def __init__(self, response): self.response = response",
                "    def get(self, url): return self.response",
                "    def head(self, url): return self.response", "",
                "class _Capabilities:",
                "    def __init__(self, results): self.results, self.offsets = results, {}",
                "    def invoke(self, ref, value):",
                "        result = self.results[ref]",
                "        if not isinstance(result, list): return result",
                "        if not result: return result",
                "        index = self.offsets.get(ref, 0)",
                "        self.offsets[ref] = index + 1",
                "        return result[index]", "",
                "    def execute(self, ref, value): return self.invoke(ref, value)", "",
                "def _context(runtime):",
                "    return SimpleNamespace(network_public=_Network(runtime.get('network_response')), capabilities=_Capabilities(runtime.get('dependency_results', {})))", "",
            ])
        for index, example in enumerate(spec.examples):
            call = f"execute({example['input']!r}, _context({dict(example.get('runtime', {}))!r}))" if contextual else f"execute({example['input']!r})"
            rows.extend([f"def test_example_{index}():", f"    assert {call} == {example['output']!r}", ""])
        (root / "tests/test_capability.py").write_text("\n".join(rows), encoding="utf-8")
        (root / "README.md").write_text(f"# {spec.ref}\n\n{spec.goal}\n", encoding="utf-8")
