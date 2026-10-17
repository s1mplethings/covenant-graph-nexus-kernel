from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityPackage, CapabilityRisk, CapabilitySpec, CapabilityStore, GeneratedCapabilityExecutor, StoredCapabilityRuntime
from cgkn.application.materialization import materialize_json
from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import BlockExecutionRequest, TaskContext


class GrowthFailureClass(str, Enum):
    UNSAFE_RISK = "UNSAFE_RISK"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    BUILD_FAILED = "BUILD_FAILED"
    CANDIDATE_NOT_STORED = "CANDIDATE_NOT_STORED"
    RESUME_FAILED = "RESUME_FAILED"


@dataclass(frozen=True)
class SelfGrowthOutcome:
    capability_ref: str
    provider_id: str
    routing_frozen: bool
    growth_invoked: bool
    builder_invoked: bool
    reused: bool
    provider_calls: int
    admitted: bool
    resumed: bool
    output: Any
    status: str
    failure_class: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "SelfGrowthOutcome", "schema_version": "1.0", **self.__dict__, "contains_credentials": False}


class SelfGrowthService:
    """BUILD-only application orchestration; the Agent remains project authority."""

    def __init__(self, builder: CapabilityBuilderService, store: CapabilityStore, *, provider_id: str, mode: str, history_path: pathlib.Path | str, network_public: Any | None = None):
        if mode not in {"SELECTED", "SINGLE_PROVIDER_MODE"}:
            raise ValueError("growth requires a frozen Provider route")
        self.builder, self.store, self.provider_id, self.mode = builder, store, provider_id, mode
        self.history_path = pathlib.Path(history_path)
        self.runtime = StoredCapabilityRuntime(store, provider_id=provider_id, network_public=network_public)

    def ensure_and_resume(self, candidate_root: pathlib.Path | str, spec: CapabilitySpec, value: Any) -> SelfGrowthOutcome:
        if spec.risk not in {CapabilityRisk.PURE, CapabilityRisk.READ_ONLY_LOCAL, CapabilityRisk.READ_ONLY_PUBLIC_NETWORK}:
            return self._failure(spec, GrowthFailureClass.UNSAFE_RISK, False, 0)
        if any(not self.store.contains(ref) for ref in spec.allowed_dependencies):
            return self._failure(spec, GrowthFailureClass.DEPENDENCY_UNAVAILABLE, False, 0)
        reused = self.store.contains(spec.ref)
        calls = 0
        if not reused:
            receipt = self.builder.build(candidate_root, spec)
            calls = receipt.provider_calls
            self._append_history(spec.ref, receipt.status, calls, receipt.usage)
            if receipt.status != "PASS":
                return self._failure(spec, GrowthFailureClass.BUILD_FAILED, True, calls)
        if not self.store.contains(spec.ref):
            return self._failure(spec, GrowthFailureClass.CANDIDATE_NOT_STORED, not reused, calls)
        package, registry = self._load_registered(spec)
        executor = GeneratedCapabilityExecutor(package, runtime_context=self.runtime.context_for(spec))
        descriptor = registry.resolve(spec.capability_id, spec.version)
        request = BlockExecutionRequest("self-growth", "growth-run", "resume-1", spec.ref, descriptor.component_ref, descriptor.executor_ref, TaskContext(f"Resume DAG node with {spec.ref}", acceptance=spec.acceptance), {"value": value}, timeout_seconds=5)
        result = executor.execute(request)
        registry.record_execution_evidence(descriptor.ref, result.succeeded)
        if not result.succeeded:
            return self._failure(spec, GrowthFailureClass.RESUME_FAILED, not reused, calls)
        return SelfGrowthOutcome(spec.ref, self.provider_id, True, not reused, not reused, reused, calls, True, True, materialize_json(result.outputs.get("result")), "PASS")

    def _load_registered(self, spec: CapabilitySpec) -> tuple[CapabilityPackage, CapabilityRegistry]:
        root = self.store.path_for(spec.ref)
        source_hash = "sha256:" + hashlib.sha256((root / "executor.py").read_bytes()).hexdigest()
        admission = json.loads((root / "admission.json").read_text(encoding="utf-8"))
        if admission.get("source_hash") != source_hash:
            raise ValueError("stored capability source hash mismatch")
        component = ComponentSpec(spec.capability_id, spec.version, (PortSpec("value", "artifact.capability.value@1"),), (PortSpec("result", "artifact.capability.result@1"),), metadata={"risk": spec.risk.value})
        executor_ref = f"generated.{spec.capability_id}@{spec.version}"
        package = CapabilityPackage(spec, str(root), component.ref, executor_ref, source_hash, ("tests/test_capability.py",))
        descriptor = CapabilityDescriptor(spec.capability_id, spec.version, component.ref, executor_ref, ("generated_python",), ("value",), ("result",), (), 5.0, "local", "LOW", "capability_store", {"provider_id": self.provider_id, "source_hash": source_hash}, package.test_refs)
        registry = CapabilityRegistry({component.ref: component}); registry.register_candidate(descriptor); registry.admit(descriptor.ref)
        return package, registry

    def _append_history(self, capability_ref: str, status: str, calls: int, usage: Mapping[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        if self.history_path.is_file():
            rows = json.loads(self.history_path.read_text(encoding="utf-8")).get("events", [])
        rows.append({"task_kind": "CAPABILITY_BUILD", "provider_id": self.provider_id, "capability_ref": capability_ref, "status": status, "calls": calls, "tokens": usage.get("total_tokens", "UNKNOWN")})
        value = {"kind": "ProviderCapabilityHistory", "schema_version": "1.0", "events": rows, "contains_credentials": False}
        descriptor, name = tempfile.mkstemp(prefix=".provider-history-", suffix=".tmp", dir=self.history_path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(name, self.history_path)
        finally:
            pathlib.Path(name).unlink(missing_ok=True)

    def _failure(self, spec: CapabilitySpec, failure: GrowthFailureClass, invoked: bool, calls: int) -> SelfGrowthOutcome:
        return SelfGrowthOutcome(spec.ref, self.provider_id, True, invoked, invoked, False, calls, False, False, None, "FAIL", failure.value)
