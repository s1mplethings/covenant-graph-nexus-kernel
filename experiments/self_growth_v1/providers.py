from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.capability_builder import (
    CapabilityBuilderService,
    CapabilityRisk,
    CapabilitySpec,
    CapabilityStore,
    StoredCapabilityRuntime,
)
from cgkn.application.self_growth import (
    CapabilityProposal,
    StrongDecisionPacket,
    canonical_hash,
    qualification_receipt,
)
from cgkn.providers import CompletionClient, GatewayCompletionError, ModelRoleConfig, ProviderCompletion

from .cases import GrowthTaskCase
from .runner import CandidateBuildResult, ModelCallEvidence, StrongDecisionResult


STRONG_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason_codes"],
    "properties": {
        "decision": {"enum": ["GENERAL_FAMILY", "TASK_SPECIFIC", "DO_NOT_CREATE"]},
        "reason_codes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
        },
    },
}


@dataclass(frozen=True)
class _CallRecord:
    role: str
    operation: str
    config: ModelRoleConfig
    latency_ms: float
    completion: ProviderCompletion | None = None
    error: Exception | None = None


class RecordingCompletionClient:
    """Secret-free evidence wrapper around the existing reviewed CompletionClient."""

    def __init__(self, client: CompletionClient) -> None:
        self.client = client
        self.records: list[_CallRecord] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
        config: ModelRoleConfig,
    ) -> ProviderCompletion:
        started = time.perf_counter()
        try:
            completion = self.client.complete(
                system=system,
                user=user,
                schema_name=schema_name,
                schema=schema,
                config=config,
            )
        except Exception as exc:
            self.records.append(
                _CallRecord(config.role, config.operation, config, (time.perf_counter() - started) * 1000, error=exc)
            )
            raise
        self.records.append(
            _CallRecord(config.role, config.operation, config, (time.perf_counter() - started) * 1000, completion=completion)
        )
        return completion


def _integer_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def model_call_evidence(record: _CallRecord) -> ModelCallEvidence:
    evidence_role = "strong" if record.role == "agent" else record.role
    if record.completion is None:
        error = record.error
        evidence = dict(error.evidence) if isinstance(error, GatewayCompletionError) else {}
        return ModelCallEvidence(
            evidence_role,
            record.config.model,
            record.config.model,
            record.operation,
            "FAIL",
            _integer_or_none(evidence.get("prompt_tokens")),
            _integer_or_none(evidence.get("completion_tokens")),
            _integer_or_none(evidence.get("cached_tokens")),
            _integer_or_none(evidence.get("reasoning_tokens")),
            _integer_or_none(evidence.get("total_tokens")),
            "UNKNOWN_AFTER_TRANSPORT_FAILURE",
            round(record.latency_ms, 6),
            str(evidence.get("request_id") or ""),
            int(evidence.get("transport_attempts") or 0),
            getattr(error, "category", type(error).__name__ if error else "UNKNOWN"),
            canonical_hash(evidence) if evidence else "",
        )
    completion = record.completion
    usage = dict(completion.usage)
    receipt = dict(completion.selection_receipt)
    input_tokens = _integer_or_none(usage.get("prompt_tokens", usage.get("input_tokens")))
    output_tokens = _integer_or_none(usage.get("completion_tokens", usage.get("output_tokens")))
    total_tokens = _integer_or_none(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return ModelCallEvidence(
        evidence_role,
        record.config.model,
        str(completion.model or record.config.model),
        record.operation,
        "PASS",
        input_tokens,
        output_tokens,
        _integer_or_none(receipt.get("cached_tokens", usage.get("cached_tokens"))),
        _integer_or_none(receipt.get("reasoning_tokens", usage.get("reasoning_tokens"))),
        total_tokens,
        "REPORTED" if usage else "UNREPORTED",
        round(record.latency_ms, 6),
        str(completion.request_id),
        int(completion.attempts),
        "",
        canonical_hash(receipt) if receipt else "",
    )


class ProviderStrongDecider:
    def __init__(self, client: CompletionClient, config: ModelRoleConfig) -> None:
        if config.role != "agent":
            raise ValueError("strong growth decisions require the frozen agent route")
        self.recorder = RecordingCompletionClient(client)
        self.config = config

    def decide(self, packet: StrongDecisionPacket) -> StrongDecisionResult:
        before = len(self.recorder.records)
        try:
            completion = self.recorder.complete(
                system=(
                    "You make one bounded capability-abstraction decision. Use only the supplied compressed public packet. "
                    "Prefer a cohesive reusable family, reject authority/security circumvention, and return JSON only."
                ),
                user=json.dumps(packet.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                schema_name="self_growth_abstraction_decision",
                schema=STRONG_DECISION_SCHEMA,
                config=self.config,
            )
        except Exception:
            call = model_call_evidence(self.recorder.records[before])
            return StrongDecisionResult("DO_NOT_CREATE", ("STRONG_PROVIDER_FAILURE",), call, packet)
        value = json.loads(completion.text)
        call = model_call_evidence(self.recorder.records[before])
        return StrongDecisionResult(
            str(value["decision"]),
            tuple(str(item) for item in value["reason_codes"]),
            call,
            packet,
        )


class ProviderCandidateBackend:
    """Build and qualify candidates through the existing immutable builder lifecycle."""

    def __init__(self, client: CompletionClient, config: ModelRoleConfig, store_root: pathlib.Path) -> None:
        if config.role != "worker":
            raise ValueError("candidate implementation requires the frozen worker route")
        self.store = CapabilityStore(store_root)
        self.runtime = StoredCapabilityRuntime(self.store, provider_id=config.model)
        self.recorder = RecordingCompletionClient(client)
        self.builder = CapabilityBuilderService(
            self.recorder,
            config,
            provider_id=config.model,
            mode="SELECTED",
            store=self.store,
        )

    @staticmethod
    def _spec(proposal: CapabilityProposal, case: GrowthTaskCase) -> CapabilitySpec:
        return CapabilitySpec(
            proposal.capability_id,
            proposal.version,
            proposal.purpose,
            dict(proposal.input_contract),
            dict(proposal.output_contract),
            tuple(dict(item) for item in case.public_examples),
            (
                case.need.required_observable or "produce the declared observable result",
                "use only the Python standard library",
                "preserve execute(value) and the declared scope",
            ),
            CapabilityRisk.PURE,
        )

    def build(self, proposal: CapabilityProposal, case: GrowthTaskCase, candidate_root: pathlib.Path) -> CandidateBuildResult:
        before = len(self.recorder.records)
        spec = self._spec(proposal, case)
        receipt = self.builder.build(candidate_root, spec)
        calls = tuple(model_call_evidence(item) for item in self.recorder.records[before:])
        hidden_results: list[bool] = []
        if receipt.status == "PASS" and self.store.contains(spec.ref):
            for hidden in case.hidden_examples:
                try:
                    hidden_results.append(self.runtime.invoke(spec.ref, hidden["input"]) == hidden["output"])
                except Exception:
                    hidden_results.append(False)
        admission_path = self.store.path_for(spec.ref) / "admission.json"
        source_hash = ""
        if admission_path.is_file():
            value = json.loads(admission_path.read_text(encoding="utf-8"))
            source_hash = str(value.get("source_hash") or "")
        qualification = qualification_receipt(
            proposal,
            source_hash=source_hash or "sha256:" + "0" * 64,
            hidden_results=hidden_results,
            builder_passed=receipt.status == "PASS",
            scope_passed=receipt.status == "PASS",
            security_passed=receipt.status == "PASS",
        )
        passed = receipt.status == "PASS" and qualification.status == "PASS"
        return CandidateBuildResult(
            "PASS" if passed else "FAIL",
            source_hash,
            f"generated.{proposal.capability_id}@{proposal.version}",
            qualification,
            calls,
            receipt.repair_rounds,
            "" if passed else receipt.error or "HIDDEN_QUALIFICATION_FAILED",
        )

    def execute(self, capability_ref: str, value: Any) -> Any:
        return self.runtime.invoke(capability_ref, value)
