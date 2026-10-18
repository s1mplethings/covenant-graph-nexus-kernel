from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .contracts import (ProgressEventType, ProviderOperationPolicy, ProviderProgressEvent,
                        ProviderRequestComplexity, SupervisedExecutionResult, SupervisionMode,
                        SupervisionReceipt, SupervisorDecision)
from .history import LatencySnapshot
from .policy import DeadlineEstimatorV1


@dataclass
class SupervisionSession:
    request_id: str
    provider_id: str
    actual_model: str
    policy: ProviderOperationPolicy
    complexity: ProviderRequestComplexity
    latency: LatencySnapshot
    started_ms: int
    initial_deadline_seconds: int
    final_deadline_seconds: int
    extension_count: int = 0
    first_progress_ms: int = -1
    last_progress_ms: int = -1
    connect_elapsed_ms: int = -1
    total_bytes: int = 0
    events: list[ProviderProgressEvent] = field(default_factory=list)
    last_payload_digest: str = ""


class ProviderExecutionSupervisor:
    def __init__(self, estimator: DeadlineEstimatorV1 | None = None, *, extension_lead_seconds: int = 20) -> None:
        self.estimator = estimator or DeadlineEstimatorV1()
        self.extension_lead_seconds = extension_lead_seconds

    def start(self, request_id: str, provider_id: str, actual_model: str, policy: ProviderOperationPolicy,
              complexity: ProviderRequestComplexity, latency: LatencySnapshot, now_ms: int) -> SupervisionSession:
        adjustment = latency.historical_adjustment(base=policy.base_deadline_seconds, hard_limit=policy.hard_limit_seconds)
        deadline = self.estimator.estimate(policy, complexity, adjustment)
        return SupervisionSession(request_id, provider_id, actual_model, policy, complexity, latency, now_ms, deadline, deadline)

    def supervise(self, request: dict[str, object], policy: ProviderOperationPolicy,
                  complexity: ProviderRequestComplexity, progress_source: object) -> SupervisedExecutionResult:
        """Drive a deterministic event source; HTTP ownership remains in SupervisedHttpTransport."""
        now_ms = int(request.get("started_ms", 0))
        latency = request.get("latency_snapshot")
        if not isinstance(latency, LatencySnapshot):
            latency = LatencySnapshot("empty", (), (), (), 0, 0)
        state = self.start(str(request.get("request_id", "request")), str(request.get("provider_id", complexity.provider_id)),
                           str(request.get("actual_model", complexity.actual_model)), policy, complexity, latency, now_ms)
        decision = SupervisorDecision.CONTINUE
        value = None
        iterator = progress_source() if callable(progress_source) else progress_source
        for item in iterator:  # type: ignore[union-attr]
            if isinstance(item, ProviderProgressEvent):
                decision = self.event(state, item.event_type, item.timestamp_monotonic_ms,
                                      bytes_received=item.bytes_received,
                                      total_bytes_received=item.total_bytes_received,
                                      payload_digest=item.payload_digest)
                now_ms = item.timestamp_monotonic_ms
            else:
                event_type, now_ms, details = item
                decision = self.event(state, ProgressEventType(event_type), int(now_ms), **dict(details))
            if decision == SupervisorDecision.COMPLETE or decision.name.startswith("CANCEL_"):
                break
        if decision == SupervisorDecision.CONTINUE:
            decision = self.check(state, now_ms)
        reason = "RESPONSE_COMPLETED" if decision == SupervisorDecision.COMPLETE else decision.value
        receipt = self.receipt(state, now_ms, reason, outcome_unknown=decision.name.startswith("CANCEL_"))
        return SupervisedExecutionResult(decision, receipt, tuple(state.events), value)

    def event(self, session: SupervisionSession, event_type: ProgressEventType, now_ms: int, *,
              bytes_received: int = 0, total_bytes_received: int | None = None, payload_digest: str = "") -> SupervisorDecision:
        elapsed = max(0, now_ms - session.started_ms)
        total = session.total_bytes + max(0, bytes_received) if total_bytes_received is None else max(0, total_bytes_received)
        phase_progress = event_type in {ProgressEventType.CONNECTION_ESTABLISHED, ProgressEventType.HEADERS_RECEIVED,
                                        ProgressEventType.FIRST_CONTENT, ProgressEventType.RESPONSE_COMPLETED,
                                        ProgressEventType.VALIDATION_STARTED, ProgressEventType.VALIDATION_COMPLETED}
        content_progress = total > session.total_bytes or (payload_digest and payload_digest != session.last_payload_digest)
        meaningful = phase_progress or content_progress
        if event_type in {ProgressEventType.CONTENT_CHUNK, ProgressEventType.STREAM_EVENT, ProgressEventType.STRUCTURED_FRAGMENT} and not content_progress:
            meaningful = False
        event = ProviderProgressEvent(str(uuid.uuid4()), session.request_id, session.provider_id, session.actual_model,
                                      session.policy.task_class, session.policy.operation, event_type, now_ms, elapsed,
                                      bytes_received, total, total // 4, payload_digest, meaningful)
        session.events.append(event)
        if meaningful:
            if session.first_progress_ms < 0 and event_type not in {ProgressEventType.REQUEST_CREATED, ProgressEventType.REQUEST_STARTED}:
                session.first_progress_ms = elapsed
            session.last_progress_ms = elapsed
            session.total_bytes = total
            if payload_digest:
                session.last_payload_digest = payload_digest
            if event_type in {ProgressEventType.CONNECTION_ESTABLISHED, ProgressEventType.HEADERS_RECEIVED}:
                session.connect_elapsed_ms = elapsed
            remaining = session.final_deadline_seconds * 1000 - elapsed
            if (remaining <= self.extension_lead_seconds * 1000 and session.extension_count < session.policy.max_extensions
                    and session.final_deadline_seconds < session.policy.hard_limit_seconds):
                session.final_deadline_seconds = min(session.policy.hard_limit_seconds,
                                                     session.final_deadline_seconds + session.policy.extension_seconds)
                session.extension_count += 1
                return SupervisorDecision.EXTEND_DEADLINE
        if event_type == ProgressEventType.RESPONSE_COMPLETED:
            return SupervisorDecision.COMPLETE
        return SupervisorDecision.CONTINUE

    def check(self, session: SupervisionSession, now_ms: int) -> SupervisorDecision:
        elapsed = max(0, now_ms - session.started_ms)
        if elapsed >= session.policy.hard_limit_seconds * 1000:
            return SupervisorDecision.CANCEL_HARD_LIMIT
        if elapsed >= session.final_deadline_seconds * 1000:
            return SupervisorDecision.CANCEL_FIRST_PROGRESS_TIMEOUT if session.first_progress_ms < 0 else SupervisorDecision.CANCEL_IDLE_TIMEOUT
        if session.connect_elapsed_ms < 0 and elapsed >= session.policy.connect_timeout_seconds * 1000:
            return SupervisorDecision.CANCEL_CONNECT_TIMEOUT
        if session.policy.supervision_mode != SupervisionMode.DEADLINE_ONLY:
            if session.first_progress_ms < 0 and elapsed >= session.policy.first_progress_timeout_seconds * 1000:
                return SupervisorDecision.CANCEL_FIRST_PROGRESS_TIMEOUT
            if session.last_progress_ms >= 0 and elapsed - session.last_progress_ms >= session.policy.idle_progress_timeout_seconds * 1000:
                return SupervisorDecision.CANCEL_IDLE_TIMEOUT
        return SupervisorDecision.CONTINUE

    def receipt(self, session: SupervisionSession, now_ms: int, termination_reason: str, *,
                timeout_phase: str = "NONE", outcome_unknown: bool = False) -> SupervisionReceipt:
        elapsed = max(0, now_ms - session.started_ms)
        return SupervisionReceipt(str(uuid.uuid4()), session.request_id, session.provider_id, session.actual_model,
                                  session.policy.task_class, session.policy.operation, session.policy.policy_id,
                                  session.policy.policy_hash, session.policy.supervision_mode, session.complexity.complexity_hash,
                                  session.latency.snapshot_hash, session.initial_deadline_seconds, session.final_deadline_seconds,
                                  session.policy.hard_limit_seconds, session.extension_count, max(0, session.connect_elapsed_ms),
                                  max(0, session.first_progress_ms), max(0, session.last_progress_ms), elapsed,
                                  session.total_bytes, session.total_bytes // 4, termination_reason, timeout_phase,
                                  outcome_unknown, len(session.events))

