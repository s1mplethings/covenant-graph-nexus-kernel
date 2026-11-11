"""Execution progress controller for VeriArbor.

This module classifies one execution attempt and decides whether the local
repair loop may continue, whether the Project Agent should be asked to replan,
or whether the project must stop for budget/infrastructure reasons.

It is intentionally independent of any provider and of the embedded planner.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

PROGRESS = "PROGRESS"
NO_PROGRESS = "NO_PROGRESS"
REGRESSION = "REGRESSION"
PROTOCOL_REPAIRABLE = "PROTOCOL_REPAIRABLE"
BUSINESS_REPAIRABLE = "BUSINESS_REPAIRABLE"
INFRA_BLOCKED = "INFRA_BLOCKED"
BUDGET_BLOCKED = "BUDGET_BLOCKED"
UNKNOWN = "UNKNOWN"
SUCCESS = "SUCCESS"

LOCAL_PROTOCOL_REPAIR = "LOCAL_PROTOCOL_REPAIR"
LOCAL_BUSINESS_REPAIR = "LOCAL_BUSINESS_REPAIR"
QUARANTINE_STRATEGY = "QUARANTINE_STRATEGY"
PROJECT_REPLAN = "PROJECT_REPLAN"
STOP_BUDGET = "STOP_BUDGET"
STOP_INFRA = "STOP_INFRA"
STOP_UNKNOWN = "STOP_UNKNOWN"
CONTINUE = "CONTINUE"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _normalize_message(message: str) -> str:
    text = str(message or "")
    text = re.sub(r"[0-9a-f]{16,}", "<hash>", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    return text.strip()[:300]


def strategy_fingerprint(node: Any) -> str:
    config = dict(getattr(node, "config", {}) or {})
    contract = dict(config.get("leaf_contract") or {})
    return _digest({
        "executor_ref": config.get("executor_ref"),
        "leaf_goal": contract.get("leaf_goal"),
        "target_scope": list(contract.get("target_scope") or ()),
        "task_kind": contract.get("task_kind"),
        "repair_contract": config.get("repair_contract"),
    })


def failure_fingerprint(result: Any) -> str:
    error = getattr(result, "error", None)
    code = getattr(error, "code", None)
    code = getattr(code, "value", code)
    details = dict(getattr(error, "details", {}) or {}) if error else {}
    return _digest({
        "status": getattr(getattr(result, "status", None), "value", getattr(result, "status", None)),
        "code": code,
        "message": _normalize_message(getattr(error, "message", "") if error else ""),
        "failure_domain": details.get("failure_domain"),
        "category": details.get("category"),
        "failure_class": details.get("failure_class"),
    })


def artifact_fingerprint(result: Any) -> str:
    metadata = dict(getattr(result, "metadata", {}) or {})
    deliverable = dict(metadata.get("deliverable_check") or {})
    subjects = dict(deliverable.get("subjects") or {})
    if not subjects:
        subjects = dict(metadata.get("artifact_hashes") or {})
    return _digest(subjects)


def _artifact_delta(result: Any) -> dict[str, Any]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    deliverable = dict(metadata.get("deliverable_check") or {})
    return dict(deliverable.get("artifact_delta") or {})


def _evidence_refs(result: Any) -> tuple[str, ...]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    deliverable = dict(metadata.get("deliverable_check") or {})
    refs = deliverable.get("evidence_refs") or ()
    values = []
    for ref in refs:
        if isinstance(ref, Mapping):
            path = ref.get("path")
            sha = ref.get("sha256")
            values.append(f"{path}:{sha}" if path else str(sha))
        else:
            values.append(str(ref))
    return tuple(values)


@dataclass(frozen=True)
class AttemptObservation:
    node_id: str
    attempt_id: str
    strategy_fingerprint: str
    failure_fingerprint: str
    artifact_before: str
    artifact_after: str
    evidence_before: tuple[str, ...] = ()
    evidence_after: tuple[str, ...] = ()
    protocol_status: str = "OK"
    business_status: str = "UNKNOWN"
    provider_status: str = "OK"
    budget_status: str = "OK"
    progress_class: str = NO_PROGRESS
    result_status: str = ""
    error_code: str = ""
    failure_domain: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def artifact_changed(self) -> bool:
        # The deliverable checker is the authority on material artifact change.
        # A caller-provided before-hash alone cannot prove a delta.
        return bool(self.metadata.get("artifact_delta"))

    @property
    def evidence_changed(self) -> bool:
        return self.evidence_before != self.evidence_after

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "attempt_id": self.attempt_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "failure_fingerprint": self.failure_fingerprint,
            "artifact_before": self.artifact_before,
            "artifact_after": self.artifact_after,
            "evidence_before": list(self.evidence_before),
            "evidence_after": list(self.evidence_after),
            "protocol_status": self.protocol_status,
            "business_status": self.business_status,
            "provider_status": self.provider_status,
            "budget_status": self.budget_status,
            "progress_class": self.progress_class,
            "result_status": self.result_status,
            "error_code": self.error_code,
            "failure_domain": self.failure_domain,
            "artifact_changed": self.artifact_changed,
            "evidence_changed": self.evidence_changed,
            "metadata": dict(self.metadata),
        }


def observe_result(result: Any, node: Any, *, artifact_before: str | None = None,
                   evidence_before: Iterable[str] = (),
                   deliverable_verdict: str | None = None) -> AttemptObservation:
    error = getattr(result, "error", None)
    details = dict(getattr(error, "details", {}) or {}) if error else {}
    status = str(getattr(getattr(result, "status", None), "value", getattr(result, "status", "")))
    domain = str(details.get("failure_domain", ""))
    message = str(getattr(error, "message", "") if error else "")
    code = str(getattr(getattr(error, "code", None), "value", getattr(error, "code", "")))
    artifact_after = artifact_fingerprint(result)
    evidence_after = _evidence_refs(result)
    delta = _artifact_delta(result)

    budget = details.get("budget_blocked") or message.startswith("PROVIDER_BUDGET_EXHAUSTED")
    unknown = bool(details.get("outcome_unknown"))
    protocol = domain == "MODEL_OUTPUT" and (details.get("failure_class") == "schema" or "schema" in message)
    infra = domain in {"TRANSPORT", "HARNESS", "INFRA"}
    business = domain == "BUSINESS" or (status == "FAILED" and not (budget or unknown or protocol or infra))

    if budget:
        progress = BUDGET_BLOCKED
    elif unknown:
        progress = UNKNOWN
    elif infra:
        progress = INFRA_BLOCKED
    elif protocol:
        progress = PROTOCOL_REPAIRABLE
    elif status == "SUCCEEDED":
        progress = SUCCESS
    elif deliverable_verdict == "FAILED" and delta:
        progress = REGRESSION
    elif delta or evidence_after != tuple(evidence_before):
        progress = PROGRESS
    elif business:
        progress = BUSINESS_REPAIRABLE
    else:
        progress = NO_PROGRESS

    return AttemptObservation(
        node_id=str(getattr(result, "node_id", "")),
        attempt_id=str(getattr(result, "attempt_id", "")),
        strategy_fingerprint=strategy_fingerprint(node),
        failure_fingerprint=failure_fingerprint(result),
        artifact_before=str(artifact_before or ""),
        artifact_after=str(artifact_after or ""),
        evidence_before=tuple(evidence_before),
        evidence_after=evidence_after,
        protocol_status="INVALID" if protocol else "OK",
        business_status="FAILED" if business else ("SUCCEEDED" if status == "SUCCEEDED" else "UNKNOWN"),
        provider_status="UNAVAILABLE" if infra else ("UNKNOWN" if unknown else "OK"),
        budget_status="BLOCKED" if budget else "OK",
        progress_class=progress,
        result_status=status,
        error_code=code,
        failure_domain=domain,
        metadata={"message": _normalize_message(message),
                  "artifact_delta": delta,
                  "deliverable_verdict": deliverable_verdict},
    )


@dataclass
class _NodeHistory:
    attempts: list[AttemptObservation] = field(default_factory=list)
    protocol_repairs: int = 0
    business_repairs: int = 0


class ExecutionProgressController:
    """Stateful decision layer for one project run."""

    def __init__(self, *, max_same_failure: int = 2,
                 max_consecutive_no_progress: int = 3,
                 max_protocol_repairs: int = 1,
                 max_business_repairs: int = 2) -> None:
        self.max_same_failure = max_same_failure
        self.max_consecutive_no_progress = max_consecutive_no_progress
        self.max_protocol_repairs = max_protocol_repairs
        self.max_business_repairs = max_business_repairs
        self.history: dict[tuple[str, str], _NodeHistory] = {}
        self.observations: list[AttemptObservation] = []

    def observe(self, observation: AttemptObservation) -> str:
        self.observations.append(observation)
        key = (observation.node_id, observation.strategy_fingerprint)
        history = self.history.setdefault(key, _NodeHistory())
        history.attempts.append(observation)

        if observation.progress_class == BUDGET_BLOCKED:
            return STOP_BUDGET
        if observation.progress_class == UNKNOWN:
            return STOP_UNKNOWN
        if observation.progress_class == INFRA_BLOCKED:
            serialized = [a for a in history.attempts if a.progress_class == INFRA_BLOCKED]
            return STOP_INFRA if len(serialized) >= self.max_same_failure else CONTINUE
        if observation.progress_class == PROTOCOL_REPAIRABLE:
            if history.protocol_repairs < self.max_protocol_repairs:
                history.protocol_repairs += 1
                return LOCAL_PROTOCOL_REPAIR
            return PROJECT_REPLAN
        if observation.progress_class == SUCCESS:
            return CONTINUE
        if observation.progress_class == PROGRESS:
            return CONTINUE
        if observation.progress_class == REGRESSION:
            return PROJECT_REPLAN

        same_failure = 0
        for attempt in reversed(history.attempts):
            if attempt.failure_fingerprint != observation.failure_fingerprint:
                break
            if attempt.artifact_changed or attempt.evidence_changed:
                break
            same_failure += 1
        if same_failure >= self.max_same_failure:
            return QUARANTINE_STRATEGY

        consecutive = 0
        for attempt in reversed(history.attempts):
            if attempt.artifact_changed or attempt.evidence_changed or attempt.progress_class in {SUCCESS, PROGRESS}:
                break
            consecutive += 1
        if consecutive >= self.max_consecutive_no_progress:
            return PROJECT_REPLAN

        if observation.progress_class == BUSINESS_REPAIRABLE:
            if history.business_repairs < self.max_business_repairs:
                history.business_repairs += 1
                return LOCAL_BUSINESS_REPAIR
            return PROJECT_REPLAN
        return CONTINUE

    def decision_for(self, node_id: str, strategy: str) -> str:
        history = self.history.get((node_id, strategy))
        if not history:
            return CONTINUE
        if any(a.progress_class == BUDGET_BLOCKED for a in history.attempts):
            return STOP_BUDGET
        return CONTINUE

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for observation in self.observations:
            counts[observation.progress_class] = counts.get(observation.progress_class, 0) + 1
        return {"observations": len(self.observations), "classes": counts,
                "strategies": len(self.history)}


__all__ = [
    "PROGRESS", "NO_PROGRESS", "REGRESSION", "PROTOCOL_REPAIRABLE", "BUSINESS_REPAIRABLE",
    "INFRA_BLOCKED", "BUDGET_BLOCKED", "UNKNOWN", "SUCCESS",
    "LOCAL_PROTOCOL_REPAIR", "LOCAL_BUSINESS_REPAIR", "QUARANTINE_STRATEGY",
    "PROJECT_REPLAN", "STOP_BUDGET", "STOP_INFRA", "STOP_UNKNOWN", "CONTINUE",
    "AttemptObservation", "ExecutionProgressController", "observe_result",
    "strategy_fingerprint", "failure_fingerprint", "artifact_fingerprint",
]
