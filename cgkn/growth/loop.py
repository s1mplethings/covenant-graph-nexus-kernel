from __future__ import annotations

import json
import pathlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry

from .admission import CapabilityAdmissionReceipt, evaluate_admission
from .discovery import DiscoverySource
from .gap import CapabilityGap
from .sandbox import LocalSandbox


class StdlibJsonExecutor:
    descriptor = ExecutorDescriptor("python.stdlib.json@1", "python_stdlib", ("json.parse@1",), ())

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        raw = request.input_values.get("text")
        try:
            if not isinstance(raw, str):
                raise TypeError("json.parse input 'text' must be a string")
            value = json.loads(raw)
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED, outputs={"object": value}, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), metadata={"module": "json", "callable": "loads"})
        except (json.JSONDecodeError, TypeError) as exc:
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, str(exc)), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)))


@dataclass(frozen=True)
class GrowthOutcome:
    capability: CapabilityDescriptor
    growth_invoked: bool
    candidate_count: int
    trial_count: int
    receipt: CapabilityAdmissionReceipt | None
    reused: bool

    def as_dict(self) -> dict[str, Any]:
        return {"capability": self.capability.as_dict(), "growth_invoked": self.growth_invoked, "candidate_count": self.candidate_count, "trial_count": self.trial_count, "receipt": self.receipt.as_dict() if self.receipt else None, "reused": self.reused}


class GrowthLoop:
    def __init__(self, registry: CapabilityRegistry, executors: ExecutorRegistry, discovery: DiscoverySource, sandbox: LocalSandbox, *, registry_path: pathlib.Path | str, evidence_root: pathlib.Path | str):
        self.registry, self.executors, self.discovery, self.sandbox = registry, executors, discovery, sandbox
        self.registry_path = pathlib.Path(registry_path)
        self.evidence_root = pathlib.Path(evidence_root)
        self.invoked_count = 0

    def ensure(self, gap: CapabilityGap) -> GrowthOutcome:
        capability_id, _, version = gap.requested_capability.partition("@")
        try:
            descriptor = self.registry.resolve(capability_id, version or None)
            self._ensure_executor(descriptor)
            return GrowthOutcome(descriptor, False, 0, 0, None, True)
        except KeyError:
            pass
        self.invoked_count += 1
        candidates = self.discovery.discover(gap)
        if not candidates:
            raise LookupError(f"no local capability candidate for {gap.requested_capability}")
        candidate = candidates[0]
        trial = self.sandbox.trial(candidate)
        receipt = evaluate_admission(candidate, trial)
        evidence_dir = self.evidence_root / gap.project_id / gap.run_id / "growth_sandbox" / gap.gap_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        self._write(evidence_dir / "gap.json", gap.as_dict())
        self._write(evidence_dir / "candidate.json", candidate.as_dict())
        self._write(evidence_dir / "trial.json", trial.as_dict())
        self._write(evidence_dir / "admission_receipt.json", receipt.as_dict())
        if receipt.verdict != "ADMITTED":
            raise RuntimeError(f"capability candidate not admitted: {receipt.reason}")
        self.registry.register_candidate(candidate.proposed_descriptor)
        self.registry.admit(candidate.proposed_descriptor.ref)
        self.registry.save(self.registry_path)
        descriptor = self.registry.resolve(capability_id, version or None)
        self._ensure_executor(descriptor)
        return GrowthOutcome(descriptor, True, len(candidates), 1, receipt, False)

    def _ensure_executor(self, descriptor: CapabilityDescriptor) -> None:
        refs = {item.descriptor.executor_ref for item in self.executors.list()}
        if descriptor.executor_ref in refs:
            return
        if descriptor.executor_ref == "python.stdlib.json@1" and descriptor.ref == "json.parse@1":
            self.executors.register(StdlibJsonExecutor())
            return
        raise LookupError(f"admitted capability executor unavailable: {descriptor.executor_ref}")

    @staticmethod
    def _write(path: pathlib.Path, value: dict[str, Any]) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
