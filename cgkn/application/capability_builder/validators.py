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
import tempfile
import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

from cgkn.execution.contracts import utc_now

from .contracts import CapabilityRisk, CapabilitySpec
from .lifecycle_contracts import (
    CandidateRevision,
    FailureDomain,
    FailureOwner,
    RecommendedAction,
    ValidationPhase,
    ValidationReceipt,
    ValidatorSuiteIdentity,
)
from .revision_store import canonical_hash, file_hash


class HarnessFailure(RuntimeError):
    pass


class ValidatorFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationContext:
    revision: CandidateRevision
    source_path: pathlib.Path
    spec: CapabilitySpec
    dependency_manifest_hash: str
    capability_store: Any = None
    external_status: str = "NOT_PROBED"
    external_required: bool = False


@dataclass(frozen=True)
class ValidationObservation:
    status: str
    failure_domain: FailureDomain | None = None
    failure_code: str = ""
    failure_owner: FailureOwner | None = None
    expected: Any = "PASS"
    observed: Any = "PASS"
    evidence_refs: tuple[str, ...] = ()
    recommended_action: RecommendedAction = RecommendedAction.NO_ACTION


class CandidateValidator(Protocol):
    phase: ValidationPhase
    version: str

    def validate(self, context: ValidationContext) -> ValidationObservation: ...


def _candidate_failure(code: str, observed: Any, *, phase_action: RecommendedAction = RecommendedAction.REPAIR_CANDIDATE) -> ValidationObservation:
    return ValidationObservation("FAIL", FailureDomain.CANDIDATE_DEFECT, code, FailureOwner.CANDIDATE, "PASS", observed, (), phase_action)


class SyntaxValidator:
    phase, version = ValidationPhase.SYNTAX, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        try:
            ast.parse((context.source_path / "executor.py").read_text(encoding="utf-8"))
            return ValidationObservation("PASS")
        except (OSError, SyntaxError) as exc:
            return _candidate_failure("CANDIDATE_SYNTAX_INVALID", f"{type(exc).__name__}: {exc}")


class ScopeValidator:
    phase, version = ValidationPhase.SCOPE, "1.0"
    allowed = {"executor.py", "capability.json", "README.md", "tests/test_capability.py"}

    def validate(self, context: ValidationContext) -> ValidationObservation:
        paths = {str(row["path"]) for row in context.revision.source_manifest}
        unexpected = sorted(paths - self.allowed)
        return ValidationObservation("PASS") if not unexpected else ValidationObservation(
            "FAIL", FailureDomain.CANDIDATE_POLICY_DEFECT, "CANDIDATE_SCOPE_VIOLATION", FailureOwner.CANDIDATE,
            sorted(self.allowed), unexpected, (), RecommendedAction.REJECT_CANDIDATE,
        )


class InterfaceValidator:
    phase, version = ValidationPhase.INTERFACE, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        try:
            tree = ast.parse((context.source_path / "executor.py").read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            return _candidate_failure("CANDIDATE_INTERFACE_UNREADABLE", str(exc))
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "execute"]
        required = 2 if context.spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or context.spec.allowed_dependencies else 1
        observed = len(functions[0].args.args) if len(functions) == 1 else None
        return ValidationObservation("PASS") if len(functions) == 1 and observed == required else _candidate_failure(
            "CANDIDATE_INTERFACE_MISMATCH", {"execute_functions": len(functions), "parameters": observed},
        )


class ContractTestValidator:
    phase, version = ValidationPhase.CONTRACT_TEST, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        environment = dict(__import__("os").environ)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        temporary = pathlib.Path(tempfile.mkdtemp(prefix="cgkn-contract-test-"))
        try:
            shutil.copyfile(context.source_path / "executor.py", temporary / "executor.py")
            rows = ["from executor import execute", ""]
            contextual = context.spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK or bool(context.spec.allowed_dependencies)
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
                    "        if not isinstance(result, list) or not result: return result",
                    "        index = self.offsets.get(ref, 0)",
                    "        if index >= len(result): raise IndexError(ref)",
                    "        self.offsets[ref] = index + 1",
                    "        return result[index]", "",
                    "    def execute(self, ref, value): return self.invoke(ref, value)", "",
                    "def _context(runtime):",
                    "    return SimpleNamespace(network_public=_Network(runtime.get('network_response')), capabilities=_Capabilities(runtime.get('dependency_results', {})))", "",
                ])
            for index, frozen in enumerate(context.spec.examples):
                example = dict(frozen)
                call = f"execute({example['input']!r}, _context({dict(example.get('runtime', {}))!r}))" if contextual else f"execute({example['input']!r})"
                rows.extend([f"def test_example_{index}():", f"    assert {call} == {example['output']!r}", ""])
            (temporary / "test_contract.py").write_text("\n".join(rows), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"], cwd=temporary,
                capture_output=True, text=True, timeout=60, env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            return ValidationObservation("FAIL", FailureDomain.ENVIRONMENT_BLOCKED, "CONTRACT_TEST_TIMEOUT", FailureOwner.ENVIRONMENT, "complete within 60s", str(exc), (), RecommendedAction.BLOCK_ENVIRONMENT)
        except Exception as exc:
            return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_HARNESS_DEFECT, "CONTRACT_TEST_HARNESS_EXCEPTION", FailureOwner.HARNESS, "test harness executes", f"{type(exc).__name__}: {exc}", (), RecommendedAction.REVALIDATE_EXISTING)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        output = (result.stdout + "\n" + result.stderr)[-4000:]
        return ValidationObservation("PASS", observed=output) if result.returncode == 0 else _candidate_failure("CONTRACT_TEST_FAILED", output)


class DependencyValidator:
    phase, version = ValidationPhase.DEPENDENCY, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        if not context.spec.allowed_dependencies:
            return ValidationObservation("PASS")
        if context.capability_store is None:
            return ValidationObservation("FAIL", FailureDomain.CONTRACT_GAP, "DEPENDENCY_STORE_MISSING", FailureOwner.CONTRACT, "dependency store", None, (), RecommendedAction.ESCALATE_REVIEW)
        try:
            manifest = context.capability_store.resolve_dependency_manifest(context.spec)
        except ValueError as exc:
            marker = str(exc).split(":", 1)[0]
            domain = FailureDomain.DEPENDENCY_DRIFT if marker == "DEPENDENCY_HASH_DRIFT" else FailureDomain.ENVIRONMENT_BLOCKED
            owner = FailureOwner.DEPENDENCY if domain is FailureDomain.DEPENDENCY_DRIFT else FailureOwner.ENVIRONMENT
            action = RecommendedAction.REVALIDATE_DEPENDENCY if domain is FailureDomain.DEPENDENCY_DRIFT else RecommendedAction.BLOCK_ENVIRONMENT
            return ValidationObservation("FAIL", domain, marker, owner, "pinned dependency manifest", str(exc), (), action)
        observed_hash = canonical_hash(manifest)
        return ValidationObservation("PASS", observed=observed_hash) if observed_hash == context.dependency_manifest_hash else ValidationObservation(
            "FAIL", FailureDomain.DEPENDENCY_DRIFT, "DEPENDENCY_MANIFEST_CHANGED", FailureOwner.DEPENDENCY,
            context.dependency_manifest_hash, observed_hash, (), RecommendedAction.REVALIDATE_DEPENDENCY,
        )


class RiskValidator:
    phase, version = ValidationPhase.RISK, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        text = (context.source_path / "executor.py").read_text(encoding="utf-8")
        uses_network = "network_public" in text
        if context.spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK and not uses_network:
            return ValidationObservation("FAIL", FailureDomain.CANDIDATE_POLICY_DEFECT, "DECLARED_NETWORK_RUNTIME_UNUSED", FailureOwner.CANDIDATE, "network_public usage", False, (), RecommendedAction.REJECT_CANDIDATE)
        if context.spec.risk is not CapabilityRisk.READ_ONLY_PUBLIC_NETWORK and uses_network:
            return ValidationObservation("FAIL", FailureDomain.CANDIDATE_POLICY_DEFECT, "UNDECLARED_NETWORK_RUNTIME", FailureOwner.CANDIDATE, False, True, (), RecommendedAction.REJECT_CANDIDATE)
        return ValidationObservation("PASS")


class SecurityValidator:
    phase, version = ValidationPhase.SECURITY, "1.0"
    forbidden_imports = {"subprocess", "socket", "requests", "urllib", "httpx", "http", "ftplib", "ctypes", "multiprocessing", "os", "pathlib", "shutil"}
    forbidden_names = {"open", "exec", "eval", "compile", "__import__"}
    forbidden_attributes = {"system", "popen", "run", "Popen", "write", "write_text", "write_bytes", "unlink", "remove", "rmdir", "mkdir"}

    def validate(self, context: ValidationContext) -> ValidationObservation:
        tree = ast.parse((context.source_path / "executor.py").read_text(encoding="utf-8"))
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)} | {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        attributes = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        violations = sorted((imports & self.forbidden_imports) | (calls & self.forbidden_names) | (attributes & self.forbidden_attributes))
        return ValidationObservation("PASS") if not violations else ValidationObservation(
            "FAIL", FailureDomain.CANDIDATE_POLICY_DEFECT, "CANDIDATE_SECURITY_POLICY_VIOLATION", FailureOwner.CANDIDATE,
            "no forbidden effects", violations, (), RecommendedAction.REJECT_CANDIDATE,
        )


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
        if capability_ref not in self.results:
            raise HarnessFailure(f"fixture omitted dependency result: {capability_ref}")
        result = self.results[capability_ref]
        if not isinstance(result, list) or not result:
            return result
        index = self.offsets.get(capability_ref, 0)
        if index >= len(result):
            raise HarnessFailure(f"fixture dependency result exhausted: {capability_ref}")
        self.offsets[capability_ref] = index + 1
        return result[index]

    def execute(self, capability_ref: str, value: Any) -> Any:
        return self.invoke(capability_ref, value)


def _load_execute(context: ValidationContext):
    module_path = context.source_path / "executor.py"
    module_spec = importlib.util.spec_from_file_location(f"candidate_{uuid.uuid4().hex}", module_path)
    if module_spec is None or module_spec.loader is None:
        raise ValidatorFailure("candidate module could not be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    execute = getattr(module, "execute", None)
    if not callable(execute):
        raise ValidatorFailure("candidate execute is not callable")
    return execute


def _execute_examples(context: ValidationContext) -> list[Any]:
    execute = _load_execute(context)
    outputs = []
    for frozen in context.spec.examples:
        example = dict(frozen)
        runtime = dict(example.get("runtime", {}))
        if len(inspect.signature(execute).parameters) == 2:
            bounded = SimpleNamespace(network_public=_ExampleNetwork(runtime.get("network_response")), capabilities=_ExampleDependencies(runtime.get("dependency_results", {})))
            output = execute(json.loads(json.dumps(example["input"])), bounded)
        else:
            output = execute(json.loads(json.dumps(example["input"])))
        outputs.append(output)
    return outputs


class RuntimeExampleValidator:
    phase, version = ValidationPhase.RUNTIME_EXAMPLE, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        try:
            outputs = _execute_examples(context)
            expected = [dict(row)["output"] for row in context.spec.examples]
            return ValidationObservation("PASS", expected=expected, observed=outputs) if outputs == expected else _candidate_failure("RUNTIME_EXAMPLE_MISMATCH", outputs)
        except HarnessFailure as exc:
            return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_HARNESS_DEFECT, "RUNTIME_HARNESS_FAILURE", FailureOwner.HARNESS, "valid fixture", str(exc), (), RecommendedAction.REVALIDATE_EXISTING)
        except ValidatorFailure as exc:
            return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_VALIDATOR_DEFECT, "RUNTIME_VALIDATOR_FAILURE", FailureOwner.VALIDATOR, "validator operational", str(exc), (), RecommendedAction.REVALIDATE_EXISTING)
        except Exception as exc:
            return _candidate_failure("RUNTIME_EXAMPLE_EXCEPTION", f"{type(exc).__name__}: {exc}")


class SerializationValidator:
    phase, version = ValidationPhase.SERIALIZATION, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        try:
            json.dumps(_execute_examples(context), ensure_ascii=False, sort_keys=True)
            return ValidationObservation("PASS")
        except HarnessFailure as exc:
            return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_HARNESS_DEFECT, "SERIALIZATION_HARNESS_FAILURE", FailureOwner.HARNESS, "valid fixture", str(exc), (), RecommendedAction.REVALIDATE_EXISTING)
        except (TypeError, ValueError) as exc:
            return _candidate_failure("CANDIDATE_OUTPUT_NOT_SERIALIZABLE", str(exc))
        except Exception as exc:
            return ValidationObservation("FAIL", FailureDomain.FRAMEWORK_VALIDATOR_DEFECT, "SERIALIZATION_VALIDATOR_FAILURE", FailureOwner.VALIDATOR, "validator operational", f"{type(exc).__name__}: {exc}", (), RecommendedAction.REVALIDATE_EXISTING)


class ExternalSmokeValidator:
    phase, version = ValidationPhase.EXTERNAL_SMOKE, "1.0"

    def validate(self, context: ValidationContext) -> ValidationObservation:
        if context.external_status in {"AVAILABLE", "PASS"}:
            return ValidationObservation("PASS", observed="EXTERNAL_AVAILABLE")
        if not context.external_required:
            return ValidationObservation("PASS", expected="local validation permits blocked external smoke", observed="EXTERNAL_BLOCKED")
        return ValidationObservation("BLOCKED_EXTERNAL", FailureDomain.EXTERNAL_DEPENDENCY_FAILURE, "EXTERNAL_SMOKE_BLOCKED", FailureOwner.EXTERNAL_SERVICE, "EXTERNAL_AVAILABLE", context.external_status, (), RecommendedAction.WAIT_EXTERNAL)


class ValidationSuite:
    def __init__(
        self,
        validators: tuple[CandidateValidator, ...] | None = None,
        *,
        suite_id: str = "capability-builder-local",
        version: str = "2.0",
        contract_test_hashes: dict[str, str] | None = None,
        fixture_hashes: dict[str, str] | None = None,
        policy_version: str = "1.0",
    ) -> None:
        self.validators = validators or (
            SyntaxValidator(), ScopeValidator(), InterfaceValidator(), ContractTestValidator(),
            DependencyValidator(), RiskValidator(), SecurityValidator(), RuntimeExampleValidator(),
            SerializationValidator(), ExternalSmokeValidator(),
        )
        source_hashes: dict[str, str] = {}
        for validator in self.validators:
            source = pathlib.Path(inspect.getsourcefile(type(validator)) or __file__)
            source_hashes[type(validator).__name__] = file_hash(source)
        payload = {
            "suite_id": suite_id, "version": version, "validator_source_hashes": source_hashes,
            "contract_test_hashes": contract_test_hashes or {}, "fixture_hashes": fixture_hashes or {},
            "policy_version": policy_version, "schema_version": "1.0",
        }
        self.identity = ValidatorSuiteIdentity(
            suite_id, version, canonical_hash(payload), source_hashes,
            contract_test_hashes or {}, fixture_hashes or {}, policy_version,
        )

    def validate_one(self, validator: CandidateValidator, context: ValidationContext) -> ValidationReceipt:
        started_at, clock = utc_now(), time.perf_counter()
        try:
            observation = validator.validate(context)
        except Exception as exc:
            observation = ValidationObservation(
                "FAIL", FailureDomain.FRAMEWORK_VALIDATOR_DEFECT, "VALIDATOR_UNHANDLED_EXCEPTION",
                FailureOwner.VALIDATOR, "validator returns evidence", f"{type(exc).__name__}: {exc}",
                (), RecommendedAction.REVALIDATE_EXISTING,
            )
        ended_at = utc_now()
        values = {
            "validation_id": f"validation.{uuid.uuid4().hex}",
            "candidate_revision_id": context.revision.revision_id,
            "candidate_source_hash": context.revision.source_hash,
            "spec_hash": context.revision.spec_hash,
            "dependency_manifest_hash": context.dependency_manifest_hash,
            "validator_suite_id": self.identity.validator_suite_id,
            "validator_suite_hash": self.identity.validator_suite_hash,
            "validator_version": validator.version,
            "validation_phase": validator.phase.value,
            "status": observation.status,
            "failure_domain": observation.failure_domain.value if observation.failure_domain else None,
            "failure_code": observation.failure_code,
            "failure_owner": observation.failure_owner.value if observation.failure_owner else None,
            "expected": observation.expected,
            "observed": observation.observed,
            "evidence_refs": list(observation.evidence_refs),
            "recommended_action": observation.recommended_action.value,
            "started_at": started_at, "ended_at": ended_at,
            "duration_ms": int((time.perf_counter() - clock) * 1000),
        }
        receipt_hash = canonical_hash({
            key: value for key, value in values.items()
            if key not in {"validation_id", "started_at", "ended_at", "duration_ms"}
        })
        return ValidationReceipt(
            values["validation_id"], context.revision.revision_id, context.revision.source_hash,
            context.revision.spec_hash, context.dependency_manifest_hash,
            self.identity.validator_suite_id, self.identity.validator_suite_hash, validator.version,
            validator.phase, observation.status, observation.failure_domain, observation.failure_code,
            observation.failure_owner, observation.expected, observation.observed, observation.evidence_refs,
            observation.recommended_action, started_at, ended_at, values["duration_ms"], receipt_hash,
        )

    def validate(self, context: ValidationContext) -> tuple[ValidationReceipt, ...]:
        return tuple(self.validate_one(validator, context) for validator in self.validators)
