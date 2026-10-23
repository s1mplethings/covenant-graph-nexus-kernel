from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Any, Mapping

from cgkn.component import ComponentSpec, PortSpec
from cgkn.execution import (
    BlockExecutionRequest,
    BlockExecutionResult,
    BlockStatus,
    ExecutionError,
    ExecutionErrorCode,
)
from cgkn.executors import ExecutorDescriptor

try:
    from cgnk_knowledge import KnowledgeMaintenancePolicy, internalize_evidence
except ImportError:  # pragma: no cover - repository source layout fallback
    source_root = pathlib.Path(__file__).resolve().parents[3] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from cgnk_knowledge import KnowledgeMaintenancePolicy, internalize_evidence


KNOWLEDGE_INTERNALIZATION_COMPONENT_SPEC = ComponentSpec(
    "knowledge.internalize",
    "1.0",
    (
        PortSpec("knowledge_pack", "artifact.project_knowledge_pack@1"),
        PortSpec("evidence", "artifact.raw_evidence@1"),
    ),
    (
        PortSpec("updated_knowledge_pack", "artifact.project_knowledge_pack@1"),
        PortSpec("receipt", "artifact.knowledge_internalization_receipt@1"),
    ),
    effects={"knowledge": "write", "provider": "conditional"},
    policy_ref="policy.knowledge.local_lazy@1",
    metadata={"layer": "application", "knowledge_authority": "ProjectKnowledgePack"},
)


class KnowledgeInternalizationService:
    """Application adapter over the existing ProjectKnowledgePack authority."""

    def internalize(
        self,
        pack: dict[str, Any],
        evidence: Mapping[str, Any],
        *,
        policy: KnowledgeMaintenancePolicy | str = KnowledgeMaintenancePolicy.LOCAL_LAZY,
    ) -> dict[str, Any]:
        return internalize_evidence(pack, evidence, policy=policy)


class KnowledgeInternalizationExecutor:
    descriptor = ExecutorDescriptor(
        "knowledge.local_lazy@1",
        "knowledge",
        (KNOWLEDGE_INTERNALIZATION_COMPONENT_SPEC.ref,),
        effects=("knowledge.write", "provider.conditional"),
        supports_cost_reporting=True,
    )

    def __init__(self, service: KnowledgeInternalizationService | None = None) -> None:
        self.service = service or KnowledgeInternalizationService()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = time.perf_counter()
        try:
            if request.component_ref != KNOWLEDGE_INTERNALIZATION_COMPONENT_SPEC.ref:
                raise ValueError("unsupported knowledge internalization component")
            pack = request.input_values.get("knowledge_pack")
            evidence = request.input_values.get("evidence")
            if not isinstance(pack, Mapping) or not isinstance(evidence, Mapping):
                raise ValueError("knowledge_pack and evidence inputs are required")
            policy = str(request.metadata.get("maintenance_policy", KnowledgeMaintenancePolicy.LOCAL_LAZY.value))
            result = self.service.internalize(_thaw(pack), _thaw(evidence), policy=policy)
            receipt = dict(result["receipt"])
            return BlockExecutionResult(
                request.project_id,
                request.run_id,
                request.attempt_id,
                request.node_id,
                request.executor_ref,
                BlockStatus.SUCCEEDED,
                outputs={"updated_knowledge_pack": result["pack"], "receipt": receipt},
                duration_ms=int((time.perf_counter() - started) * 1000),
                usage={"provider_calls": receipt.get("provider_calls", 0)},
                metadata={
                    "component_ref": request.component_ref,
                    "knowledge_authority": "ProjectKnowledgePack",
                    "receipt_hash": _hash(receipt),
                },
            )
        except (ValueError, TypeError, KeyError) as exc:
            return BlockExecutionResult(
                request.project_id,
                request.run_id,
                request.attempt_id,
                request.node_id,
                request.executor_ref,
                BlockStatus.FAILED,
                error=ExecutionError(ExecutionErrorCode.CONTRACT_ERROR, str(exc)),
                duration_ms=int((time.perf_counter() - started) * 1000),
                retryable=False,
            )


def _hash(value: Any) -> str:
    import hashlib

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
