from __future__ import annotations

import hashlib
import socket
import time
import uuid
from typing import Any, Callable, Mapping
from urllib import error, request

from ..connection_contracts import ProviderConnectionError
from .contracts import (ProgressEventType, ProviderOperationPolicy, ProviderRequestComplexity,
                        SupervisedHttpResponse, SupervisionMode, SupervisorDecision)
from .history import LatencySnapshot, ProviderLatencyProfileStore
from .supervisor import ProviderExecutionSupervisor


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))


class SupervisedHttpTransport:
    """Synchronous urllib transport: cancellation closes the only socket; no worker survives."""

    def __init__(self, *, supervisor: ProviderExecutionSupervisor | None = None,
                 latency_store: ProviderLatencyProfileStore | None = None,
                 open_fn: Callable[..., Any] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 max_response_bytes: int = 2_097_152, chunk_size: int = 65_536) -> None:
        self.supervisor = supervisor or ProviderExecutionSupervisor()
        self.latency_store = latency_store or ProviderLatencyProfileStore()
        self.open_fn = open_fn
        self.clock = clock
        self.max_response_bytes = max_response_bytes
        self.chunk_size = chunk_size
        self.last_receipt = None

    def send(self, *, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
             provider_id: str, model: str, policy: ProviderOperationPolicy,
             complexity: ProviderRequestComplexity) -> SupervisedHttpResponse:
        request_id = str(uuid.uuid4())
        started_ms = int(self.clock() * 1000)
        snapshot = self.latency_store.freeze(provider_id, model, policy.task_class, policy.policy_id)
        session = self.supervisor.start(request_id, provider_id, model, policy, complexity, snapshot, started_ms)
        self.supervisor.event(session, ProgressEventType.REQUEST_CREATED, started_ms)
        self.supervisor.event(session, ProgressEventType.REQUEST_STARTED, started_ms)
        req = request.Request(url, data=body, headers=dict(headers), method=method)
        response = None
        try:
            # urllib combines connect and header wait. The bound is therefore the earliest
            # honest observable deadline; the receipt never claims a fake connect event.
            pre_header_limit = min(session.initial_deadline_seconds, policy.hard_limit_seconds)
            if policy.supervision_mode != SupervisionMode.DEADLINE_ONLY:
                pre_header_limit = min(pre_header_limit, policy.first_progress_timeout_seconds)
            response = (self.open_fn or request.urlopen)(req, timeout=max(1, pre_header_limit))
            now_ms = int(self.clock() * 1000)
            self.supervisor.event(session, ProgressEventType.HEADERS_RECEIVED, now_ms)
            raw = bytearray()
            has_headers = hasattr(response, "headers")
            while True:
                now_ms = int(self.clock() * 1000)
                decision = self.supervisor.check(session, now_ms)
                if decision.name.startswith("CANCEL_"):
                    raise self._timeout_error(decision, session, now_ms)
                self._set_read_timeout(response, max(1.0, min(
                    float(policy.idle_progress_timeout_seconds),
                    float(policy.hard_limit_seconds) - (now_ms - started_ms) / 1000.0,
                )))
                chunk = response.read(min(self.chunk_size, self.max_response_bytes + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                digest = hashlib.sha256(chunk).hexdigest()
                self.supervisor.event(session, ProgressEventType.CONTENT_CHUNK, int(self.clock() * 1000),
                                      bytes_received=len(chunk), total_bytes_received=len(raw), payload_digest=digest)
                if len(raw) > self.max_response_bytes:
                    raise ProviderConnectionError("PROVIDER_TRUNCATED_RESPONSE", "response exceeded bounded size", outcome_unknown=True)
                if not has_headers:
                    break
            now_ms = int(self.clock() * 1000)
            self.supervisor.event(session, ProgressEventType.RESPONSE_COMPLETED, now_ms)
            receipt = self.supervisor.receipt(session, now_ms, "RESPONSE_COMPLETED")
            self.last_receipt = receipt
            self.latency_store.record(snapshot, success_seconds=receipt.total_elapsed_ms / 1000,
                                      first_progress_seconds=receipt.first_progress_ms / 1000)
            safe_headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()
                            if str(k).lower() in {"content-type", "content-length", "x-request-id", "request-id"}}
            return SupervisedHttpResponse(int(getattr(response, "status", 200)), safe_headers, bytes(raw), receipt)
        except error.HTTPError:
            raise
        except ProviderConnectionError:
            raise
        except (TimeoutError, error.URLError, OSError) as exc:
            now_ms = int(self.clock() * 1000)
            if _is_timeout(exc):
                decision = self.supervisor.check(session, now_ms)
                if not decision.name.startswith("CANCEL_"):
                    decision = SupervisorDecision.CANCEL_FIRST_PROGRESS_TIMEOUT if session.first_progress_ms < 0 else SupervisorDecision.CANCEL_IDLE_TIMEOUT
                raise self._timeout_error(decision, session, now_ms) from None
            receipt = self.supervisor.receipt(session, now_ms, "TRANSPORT_FAILURE", outcome_unknown=True)
            self.last_receipt = receipt
            self.latency_store.record(snapshot, transport_failure=True)
            raise ProviderConnectionError("PROVIDER_TRANSPORT_FAILURE", str(getattr(exc, "reason", exc))[:1000],
                                          outcome_unknown=True, evidence=self.usage(receipt)) from None
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def _timeout_error(self, decision: SupervisorDecision, session: Any, now_ms: int) -> ProviderConnectionError:
        mapping = {
            SupervisorDecision.CANCEL_CONNECT_TIMEOUT: ("PROVIDER_CONNECT_TIMEOUT", "CONNECT"),
            SupervisorDecision.CANCEL_FIRST_PROGRESS_TIMEOUT: ("PROVIDER_FIRST_PROGRESS_TIMEOUT", "FIRST_PROGRESS"),
            SupervisorDecision.CANCEL_IDLE_TIMEOUT: ("PROVIDER_IDLE_TIMEOUT", "IDLE_PROGRESS"),
            SupervisorDecision.CANCEL_HARD_LIMIT: ("PROVIDER_HARD_LIMIT_REACHED", "HARD_LIMIT"),
        }
        error_class, phase = mapping[decision]
        receipt = self.supervisor.receipt(session, now_ms, error_class, timeout_phase=phase, outcome_unknown=True)
        self.last_receipt = receipt
        self.latency_store.record(session.latency, hard_limit=decision == SupervisorDecision.CANCEL_HARD_LIMIT)
        return ProviderConnectionError(error_class, f"provider request cancelled at {phase}", outcome_unknown=True,
                                       timeout_phase=phase, evidence=self.usage(receipt))

    @staticmethod
    def _set_read_timeout(response: Any, seconds: float) -> None:
        """Best-effort socket bound; failure is safe because the opener already has a bound timeout."""
        candidates = (
            getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None),
            getattr(getattr(response, "fp", None), "_sock", None),
        )
        for sock in candidates:
            if sock is not None and callable(getattr(sock, "settimeout", None)):
                sock.settimeout(seconds)
                return

    @staticmethod
    def usage(receipt: Any) -> dict[str, Any]:
        return {"supervision_receipt_hash": receipt.receipt_hash, "operation_policy_id": receipt.policy_id,
                "supervision_mode": receipt.supervision_mode.value, "initial_deadline_seconds": receipt.initial_deadline_seconds,
                "final_deadline_seconds": receipt.final_deadline_seconds, "hard_limit_seconds": receipt.hard_limit_seconds,
                "extension_count": receipt.extension_count, "first_progress_ms": receipt.first_progress_ms,
                "last_progress_ms": receipt.last_progress_ms, "termination_reason": receipt.termination_reason,
                "timeout_phase": receipt.timeout_phase, "outcome_unknown": receipt.outcome_unknown,
                "bytes_received": receipt.bytes_received, "contains_credentials": False}

