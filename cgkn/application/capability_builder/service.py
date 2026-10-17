from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import pathlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

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
from .public_network import PublicNetworkClient


def _slug(ref: str) -> str:
    return ref.replace("@", "-").replace(".", "-")


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

    def invoke(self, capability_ref: str, value: Any) -> Any:
        return self.results[capability_ref]


class CapabilityBuilderService:
    def __init__(self, client: CompletionClient, config: ModelRoleConfig, *, provider_id: str, mode: str, store: CapabilityStore):
        if config.role != "worker" or config.model != provider_id or mode not in {"SELECTED", "SINGLE_PROVIDER_MODE"}:
            raise ValueError("capability builder requires one frozen worker route")
        self.client, self.config, self.provider_id, self.mode, self.store = client, config, provider_id, mode, store

    def build(self, candidate_root: pathlib.Path | str, spec: CapabilitySpec) -> CapabilityBuildReceipt:
        root = pathlib.Path(candidate_root).resolve() / _slug(spec.ref)
        if root.exists():
            raise FileExistsError(f"candidate already exists: {root}")
        self._scaffold(root, spec)
        calls = repairs = 0; usage: dict[str, Any] = {}; failure = ""
        try:
            transaction = ScopedFileTransaction(root, WorkerScope(("executor.py", "tests/test_capability.py", "capability.json"), ("executor.py",), protected_paths=("admission.json",), max_actions=1, max_write_files=1, allow_create=False, allow_patch=True))
            for attempt in range(2):
                completion = self.client.complete(
                    system="You implement one bounded Python capability. Patch only executor.py, use only the standard library and the supplied runtime contract, preserve the required execute signature, and return JSON only.",
                    user=json.dumps(self._prompt(root, spec, failure), ensure_ascii=False, sort_keys=True),
                    schema_name="capability_candidate_patch", schema=WORKER_SCHEMA, config=self.config,
                )
                calls += 1; usage = dict(completion.usage)
                proposal = validate_worker_proposal(parse_json_object(completion.text), spec.ref)
                if proposal["needs_escalation"]:
                    failure = str(proposal["escalation_reason"]); break
                transaction.apply(proposal["actions"])
                passed, failure = self._verify(root)
                if passed: break
                if attempt == 0:
                    repairs = 1
            if failure:
                return self._receipt(spec, root, calls, repairs, False, False, False, False, usage, failure)
            package, registry = self._candidate(root, spec)
            execution_passed = self._execute(package, spec)
            if not execution_passed:
                registry.reject(spec.ref)
                return self._receipt(spec, root, calls, repairs, True, False, False, False, usage, "runtime execution failed")
            registry.admit(spec.ref)
            admission = {"kind": "CapabilityAdmission", "schema_version": "1.0", "capability_ref": spec.ref, "status": "ADMITTED", "source_hash": package.source_hash, "provider_id": self.provider_id, "mode": self.mode, "manual_edits": 0}
            (root / "admission.json").write_text(json.dumps(admission, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.store.put(package)
            return self._receipt(spec, root, calls, repairs, True, True, True, True, usage, "")
        except Exception as exc:
            return self._receipt(spec, root, calls, repairs, False, False, False, False, usage, f"{type(exc).__name__}: {exc}")

    def _candidate(self, root: pathlib.Path, spec: CapabilitySpec) -> tuple[CapabilityPackage, CapabilityRegistry]:
        tree = ast.parse((root / "executor.py").read_text(encoding="utf-8"))
        forbidden = {"subprocess", "socket", "requests", "urllib", "httpx", "http", "ftplib", "ctypes", "multiprocessing", "os", "pathlib", "shutil"}
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)} | {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        if imports & forbidden:
            raise ValueError("candidate requests forbidden network or process access")
        forbidden_calls = {"open", "exec", "eval", "compile", "__import__"}
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls for node in ast.walk(tree)):
            raise ValueError("candidate requests forbidden filesystem or dynamic execution access")
        forbidden_attributes = {"system", "popen", "run", "Popen", "write", "write_text", "write_bytes", "unlink", "remove", "rmdir", "mkdir"}
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attributes for node in ast.walk(tree)):
            raise ValueError("candidate requests forbidden filesystem or process access")
        execute_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "execute"]
        if len(execute_nodes) != 1:
            raise ValueError("candidate must declare exactly one execute function")
        parameter_count = len(execute_nodes[0].args.args)
        requires_context = spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or bool(spec.allowed_dependencies)
        if parameter_count != (2 if requires_context else 1):
            raise ValueError("candidate execute signature does not match declared runtime requirements")
        source_text = (root / "executor.py").read_text(encoding="utf-8")
        if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK and any(token in source_text.lower() for token in ("authorization", "cookie", "proxy-authorization", "api_key", "api-key", "bearer ")):
            raise ValueError("public-network capability may not request credentials")
        if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK and "network_public" not in source_text:
            raise ValueError("public-network capability must use the bounded network runtime")
        if spec.risk is not CapabilityRisk.READ_ONLY_PUBLIC_NETWORK and "network_public" in source_text:
            raise ValueError("capability did not declare public-network risk")
        dependency_literals = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "invoke"
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
        }
        if dependency_literals - set(spec.allowed_dependencies):
            raise ValueError("candidate invokes an undeclared capability dependency")
        if spec.allowed_dependencies and dependency_literals != set(spec.allowed_dependencies):
            raise ValueError("candidate did not invoke every declared capability dependency")
        source_hash = "sha256:" + hashlib.sha256((root / "executor.py").read_bytes()).hexdigest()
        component = ComponentSpec(spec.capability_id, spec.version, (PortSpec("value", "artifact.capability.value@1"),), (PortSpec("result", "artifact.capability.result@1"),), metadata={"risk": spec.risk.value})
        executor_ref = f"generated.{spec.capability_id}@{spec.version}"
        package = CapabilityPackage(spec, str(root), component.ref, executor_ref, source_hash, ("tests/test_capability.py",))
        effects = ("public_network_read",) if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK else ()
        descriptor = CapabilityDescriptor(spec.capability_id, spec.version, component.ref, executor_ref, ("generated_python",), ("value",), ("result",), effects, 10.0, "local", "LOW", "generated", {"provider_id": self.provider_id, "source_hash": source_hash, "dependencies": spec.allowed_dependencies}, package.test_refs)
        registry = CapabilityRegistry({component.ref: component}); registry.register_candidate(descriptor)
        return package, registry

    @staticmethod
    def _execute(package: CapabilityPackage, spec: CapabilitySpec) -> bool:
        for index, frozen in enumerate(spec.examples):
            example = dict(frozen)
            runtime = dict(example.get("runtime", {}))
            context = CapabilityRuntimeContext(_ExampleNetwork(runtime.get("network_response")), _ExampleDependencies(runtime.get("dependency_results", {})))
            executor = GeneratedCapabilityExecutor(package, runtime_context=context if (spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or spec.allowed_dependencies) else None)
            request = BlockExecutionRequest("capability-builder", "admission", f"attempt-{index + 1}", spec.ref, package.component_ref, package.executor_ref, TaskContext(spec.goal, acceptance=spec.acceptance), {"value": example["input"]}, timeout_seconds=5)
            result = executor.execute(request)
            if not result.succeeded or materialize_json(result.outputs.get("result")) != example["output"]:
                return False
        return True

    @staticmethod
    def _verify(root: pathlib.Path) -> tuple[bool, str]:
        environment = dict(__import__("os").environ); environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"; environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True, timeout=60, env=environment)
        return result.returncode == 0, "" if result.returncode == 0 else (result.stdout + "\n" + result.stderr)[-4000:]

    @staticmethod
    def _prompt(root: pathlib.Path, spec: CapabilitySpec, failure: str) -> dict[str, Any]:
        runtime_contract = {
            "risk": spec.risk.value,
            "execute_signature": "execute(value, ctx)" if (spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or spec.allowed_dependencies) else "execute(value)",
            "network_api": "ctx.network_public.get(url) or head(url); never import or call network libraries directly" if spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK else "unavailable",
            "declared_dependencies": list(spec.allowed_dependencies),
            "dependency_api": "ctx.capabilities.invoke(capability_ref, value); invoke only declared refs" if spec.allowed_dependencies else "unavailable",
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
                "    def __init__(self, results): self.results = results",
                "    def invoke(self, ref, value): return self.results[ref]", "",
                "def _context(runtime):",
                "    return SimpleNamespace(network_public=_Network(runtime.get('network_response')), capabilities=_Capabilities(runtime.get('dependency_results', {})))", "",
            ])
        for index, example in enumerate(spec.examples):
            call = f"execute({example['input']!r}, _context({dict(example.get('runtime', {}))!r}))" if contextual else f"execute({example['input']!r})"
            rows.extend([f"def test_example_{index}():", f"    assert {call} == {example['output']!r}", ""])
        (root / "tests/test_capability.py").write_text("\n".join(rows), encoding="utf-8")
        (root / "README.md").write_text(f"# {spec.ref}\n\n{spec.goal}\n", encoding="utf-8")

    def _receipt(self, spec: CapabilitySpec, root: pathlib.Path, calls: int, repairs: int, tests: bool, admitted: bool, executed: bool, stored: bool, usage: dict[str, Any], error: str) -> CapabilityBuildReceipt:
        return CapabilityBuildReceipt(spec.ref, self.provider_id, self.mode, str(root), calls, repairs, tests, admitted, executed, stored, 0, "PASS" if stored else "FAIL", usage, error[:4000])
