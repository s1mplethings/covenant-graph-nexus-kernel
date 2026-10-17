from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import time
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

from .contracts import CapabilityBuildReceipt, CapabilityPackage, CapabilitySpec


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


class GeneratedCapabilityExecutor:
    def __init__(self, package: CapabilityPackage):
        self.package = package
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
            output = self.module.execute(request.input_values.get("value"))
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs={"result": output}, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))


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
                    system="You implement one pure bounded Python function. Patch only executor.py, use only the standard library, preserve execute(value), and return JSON only.",
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
                repairs += 1
            if failure:
                return self._receipt(spec, root, calls, repairs, False, False, False, False, usage, failure)
            package, registry = self._admit(root, spec)
            execution_passed = self._execute(package, registry, spec)
            if not execution_passed:
                return self._receipt(spec, root, calls, repairs, True, True, False, False, usage, "runtime execution failed")
            admission = {"kind": "CapabilityAdmission", "schema_version": "1.0", "capability_ref": spec.ref, "status": "ADMITTED", "source_hash": package.source_hash, "provider_id": self.provider_id, "mode": self.mode, "manual_edits": 0}
            (root / "admission.json").write_text(json.dumps(admission, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.store.put(package)
            return self._receipt(spec, root, calls, repairs, True, True, True, True, usage, "")
        except Exception as exc:
            return self._receipt(spec, root, calls, repairs, False, False, False, False, usage, f"{type(exc).__name__}: {exc}")

    def _admit(self, root: pathlib.Path, spec: CapabilitySpec) -> tuple[CapabilityPackage, CapabilityRegistry]:
        tree = ast.parse((root / "executor.py").read_text(encoding="utf-8"))
        forbidden = {"subprocess", "socket", "requests", "urllib", "httpx"}
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)} | {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        if imports & forbidden:
            raise ValueError("candidate requests forbidden network or process access")
        source_hash = "sha256:" + hashlib.sha256((root / "executor.py").read_bytes()).hexdigest()
        component = ComponentSpec(spec.capability_id, spec.version, (PortSpec("value", "artifact.capability.value@1"),), (PortSpec("result", "artifact.capability.result@1"),), metadata={"risk": spec.risk.value})
        executor_ref = f"generated.{spec.capability_id}@{spec.version}"
        package = CapabilityPackage(spec, str(root), component.ref, executor_ref, source_hash, ("tests/test_capability.py",))
        descriptor = CapabilityDescriptor(spec.capability_id, spec.version, component.ref, executor_ref, ("generated_python",), ("value",), ("result",), (), 5.0, "local", "LOW", "generated", {"provider_id": self.provider_id, "source_hash": source_hash}, package.test_refs)
        registry = CapabilityRegistry({component.ref: component}); registry.register_candidate(descriptor); registry.admit(descriptor.ref)
        return package, registry

    @staticmethod
    def _execute(package: CapabilityPackage, registry: CapabilityRegistry, spec: CapabilitySpec) -> bool:
        resolved = registry.resolve(spec.capability_id, spec.version)
        executor = GeneratedCapabilityExecutor(package)
        example = dict(spec.examples[0])
        request = BlockExecutionRequest("capability-builder", "admission", "attempt-1", spec.ref, resolved.component_ref, resolved.executor_ref, TaskContext(spec.goal, acceptance=spec.acceptance), {"value": example["input"]}, timeout_seconds=5)
        result = executor.execute(request)
        passed = result.succeeded and result.outputs.get("result") == example["output"]
        registry.record_execution_evidence(resolved.ref, passed)
        return passed

    @staticmethod
    def _verify(root: pathlib.Path) -> tuple[bool, str]:
        environment = dict(__import__("os").environ); environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"; environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True, timeout=60, env=environment)
        return result.returncode == 0, "" if result.returncode == 0 else (result.stdout + "\n" + result.stderr)[-4000:]

    @staticmethod
    def _prompt(root: pathlib.Path, spec: CapabilitySpec, failure: str) -> dict[str, Any]:
        return {"node_id": spec.ref, "goal": spec.goal, "requirements": list(spec.acceptance), "allowed_paths": ["executor.py"], "current_sources": {"executor.py": (root / "executor.py").read_text(encoding="utf-8")}, "examples": [dict(item) for item in spec.examples], "failure_evidence": failure, "allowed_actions": ["patch_file"]}

    @staticmethod
    def _scaffold(root: pathlib.Path, spec: CapabilitySpec) -> None:
        root.mkdir(parents=True); (root / "tests").mkdir()
        (root / "executor.py").write_text('"""Generated capability candidate."""\n\ndef execute(value):\n    raise NotImplementedError("candidate not implemented")\n', encoding="utf-8")
        (root / "capability.json").write_text(json.dumps(spec.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rows = ["from executor import execute", ""]
        for index, example in enumerate(spec.examples):
            rows.extend([f"def test_example_{index}():", f"    assert execute({example['input']!r}) == {example['output']!r}", ""])
        (root / "tests/test_capability.py").write_text("\n".join(rows), encoding="utf-8")
        (root / "README.md").write_text(f"# {spec.ref}\n\n{spec.goal}\n", encoding="utf-8")

    def _receipt(self, spec: CapabilitySpec, root: pathlib.Path, calls: int, repairs: int, tests: bool, admitted: bool, executed: bool, stored: bool, usage: dict[str, Any], error: str) -> CapabilityBuildReceipt:
        return CapabilityBuildReceipt(spec.ref, self.provider_id, self.mode, str(root), calls, repairs, tests, admitted, executed, stored, 0, "PASS" if stored else "FAIL", usage, error[:4000])
