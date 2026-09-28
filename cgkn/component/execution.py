from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from cgkn.artifacts.models import ArtifactRef


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComponentExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    BYPASSED = "bypassed"
    CACHED = "cached"


@dataclass
class ComponentExecution:
    component_ref: str
    node_id: str
    run_id: str
    execution_id: str = field(default_factory=lambda: f"exec.{uuid.uuid4().hex}")
    input_artifact_refs: tuple[ArtifactRef, ...] = ()
    output_artifact_refs: tuple[ArtifactRef, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    cache_status: str = "miss"
    diagnostics: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()
    effects_summary: dict[str, Any] = field(default_factory=dict)
    execution_fingerprint: str = ""
    _status: ComponentExecutionStatus = field(default=ComponentExecutionStatus.PENDING, init=False, repr=False)
    _started_clock: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.execution_id or not self.component_ref or not self.node_id or not self.run_id:
            raise ValueError("execution id, component ref, node id, and run id are required")
        self.input_artifact_refs = self._refs(self.input_artifact_refs)
        self.output_artifact_refs = self._refs(self.output_artifact_refs)

    @property
    def status(self) -> ComponentExecutionStatus:
        return self._status

    def start(self, inputs: Iterable[ArtifactRef] = ()) -> "ComponentExecution":
        self._require(ComponentExecutionStatus.PENDING)
        self.input_artifact_refs = self._refs(inputs)
        self.started_at = _now()
        self._started_clock = time.perf_counter()
        self._status = ComponentExecutionStatus.RUNNING
        return self

    def succeed(self, outputs: Iterable[ArtifactRef], *, evidence_refs: Iterable[str] = ()) -> "ComponentExecution":
        self._finish(ComponentExecutionStatus.PASS, outputs)
        self.evidence_refs = tuple(evidence_refs)
        return self

    def fail(self, diagnostics: Iterable[dict[str, Any]]) -> "ComponentExecution":
        values = tuple(dict(item) for item in diagnostics)
        if not values:
            raise ValueError("failed execution requires diagnostics")
        self.diagnostics = values
        self._finish(ComponentExecutionStatus.FAIL, ())
        return self

    def cached(self, outputs: Iterable[ArtifactRef]) -> "ComponentExecution":
        self.cache_status = "hit"
        self._finish(ComponentExecutionStatus.CACHED, outputs)
        return self

    def bypass(self, outputs: Iterable[ArtifactRef]) -> "ComponentExecution":
        self._require(ComponentExecutionStatus.PENDING)
        self.started_at = self.finished_at = _now()
        self.duration_ms = 0
        self.output_artifact_refs = self._refs(outputs)
        self.cache_status = "bypass"
        self._status = ComponentExecutionStatus.BYPASSED
        return self

    def _finish(self, status: ComponentExecutionStatus, outputs: Iterable[ArtifactRef]) -> None:
        self._require(ComponentExecutionStatus.RUNNING)
        self.output_artifact_refs = tuple(outputs)
        self.finished_at = _now()
        self.duration_ms = max(0, int((time.perf_counter() - (self._started_clock or time.perf_counter())) * 1000))
        self._status = status

    def _require(self, expected: ComponentExecutionStatus) -> None:
        if self._status is not expected:
            raise ValueError(f"illegal execution transition: {self._status.value} -> expected {expected.value}")

    @staticmethod
    def _refs(values: Iterable[ArtifactRef]) -> tuple[ArtifactRef, ...]:
        result = tuple(values)
        if not all(isinstance(item, ArtifactRef) for item in result):
            raise TypeError("component execution artifact refs must be ArtifactRef values")
        return result

    def as_checkpoint(self) -> dict[str, Any]:
        if self._status in {ComponentExecutionStatus.PASS, ComponentExecutionStatus.FAIL, ComponentExecutionStatus.CACHED, ComponentExecutionStatus.BYPASSED} and not self.finished_at:
            raise ValueError("terminal execution requires finished_at")
        if self._status is ComponentExecutionStatus.FAIL and not self.diagnostics:
            raise ValueError("failed execution requires diagnostics")
        return {
            "kind": "GenerationCheckpoint",
            "executionId": self.execution_id,
            "componentRef": self.component_ref,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "status": self._status.value,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "durationMs": self.duration_ms,
            "inputArtifactRefs": [item.as_dict() for item in self.input_artifact_refs],
            "outputArtifactRefs": [item.as_dict() for item in self.output_artifact_refs],
            "executionFingerprint": self.execution_fingerprint,
            "cacheStatus": self.cache_status,
            "diagnostics": list(self.diagnostics),
            "evidenceRefs": list(self.evidence_refs),
            "effectsSummary": dict(self.effects_summary),
        }
