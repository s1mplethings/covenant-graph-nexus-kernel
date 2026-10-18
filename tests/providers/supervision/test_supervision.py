from __future__ import annotations

import json
import threading

import pytest

from cgkn.providers.connection_contracts import ProviderConnectionError
from cgkn.providers.supervision import (DeadlineEstimatorV1, LatencySnapshot, ProgressEventType,
                                        ProviderExecutionSupervisor, ProviderLatencyProfileStore,
                                        ProviderOperationPolicyRegistry, ProviderRequestComplexity,
                                        SupervisedHttpTransport, SupervisionMode, SupervisorDecision)


def complexity(task="project.domain.simple", tokens=1000):
    return ProviderRequestComplexity(100, 200, 300, 1, 400, 0, tokens, task, "qwen", "qwen3.8-max")


def session(task="project.domain.simple", now=0):
    policy = ProviderOperationPolicyRegistry().get(task)
    snap = LatencySnapshot("k", (), (), (), 0, 0)
    supervisor = ProviderExecutionSupervisor(extension_lead_seconds=30)
    return supervisor, supervisor.start("r", "qwen", "qwen3.8-max", policy, complexity(task), snap, now)


@pytest.mark.parametrize("task,hard", [
    ("connection.probe", 90), ("benchmark.micro", 120), ("project.domain.simple", 300),
    ("project.domain.persistent", 360), ("project.domain.library", 300),
    ("repository.patch", 240), ("project.repair", 240), ("capability.build", 330),
])
def test_registry_has_bounded_task_policies(task, hard):
    policy = ProviderOperationPolicyRegistry().get(task)
    assert policy.hard_limit_seconds == hard
    assert policy.base_deadline_seconds <= hard


@pytest.mark.parametrize("tokens", [1, 1000, 2000, 4000, 7000])
def test_estimator_is_deterministic_and_clamped(tokens):
    policy = ProviderOperationPolicyRegistry().get("project.domain.simple")
    value = DeadlineEstimatorV1().estimate(policy, complexity(tokens=tokens))
    assert value == DeadlineEstimatorV1().estimate(policy, complexity(tokens=tokens))
    assert policy.min_deadline_seconds <= value <= policy.hard_limit_seconds


def test_connect_success_records_progress():
    supervisor, state = session()
    assert supervisor.event(state, ProgressEventType.HEADERS_RECEIVED, 1000) == SupervisorDecision.CONTINUE
    assert state.connect_elapsed_ms == 1000 and state.first_progress_ms == 1000


def test_connect_timeout():
    supervisor, state = session()
    assert supervisor.check(state, state.policy.connect_timeout_seconds * 1000) == SupervisorDecision.CANCEL_CONNECT_TIMEOUT


def test_first_progress_timeout_after_connection_without_content():
    supervisor, state = session()
    supervisor.event(state, ProgressEventType.CONNECTION_ESTABLISHED, 1)
    state.first_progress_ms = -1
    assert supervisor.check(state, state.policy.first_progress_timeout_seconds * 1000) == SupervisorDecision.CANCEL_FIRST_PROGRESS_TIMEOUT


def test_meaningful_progress_can_extend():
    supervisor, state = session("benchmark.micro")
    state.final_deadline_seconds = 90
    decision = supervisor.event(state, ProgressEventType.CONTENT_CHUNK, 80_000, bytes_received=5, payload_digest="a")
    assert decision == SupervisorDecision.EXTEND_DEADLINE and state.final_deadline_seconds == 105


@pytest.mark.parametrize("kind,digest,size", [
    (ProgressEventType.CONTENT_CHUNK, "", 0),
    (ProgressEventType.CONTENT_CHUNK, "same", 0),
    (ProgressEventType.STREAM_EVENT, "same", 0),
])
def test_empty_or_repeated_progress_does_not_extend(kind, digest, size):
    supervisor, state = session("benchmark.micro"); state.final_deadline_seconds = 90; state.last_payload_digest = "same"
    assert supervisor.event(state, kind, 80_000, bytes_received=size, payload_digest=digest) == SupervisorDecision.CONTINUE


def test_body_chunk_increases_progress():
    supervisor, state = session()
    supervisor.event(state, ProgressEventType.CONTENT_CHUNK, 10, bytes_received=7, payload_digest="x")
    assert state.total_bytes == 7 and state.events[-1].meaningful_progress


def test_idle_timeout():
    supervisor, state = session(); supervisor.event(state, ProgressEventType.HEADERS_RECEIVED, 1)
    assert supervisor.check(state, 1 + state.policy.idle_progress_timeout_seconds * 1000) == SupervisorDecision.CANCEL_IDLE_TIMEOUT


def test_hard_limit_wins_despite_progress():
    supervisor, state = session(); supervisor.event(state, ProgressEventType.CONTENT_CHUNK, 1000, bytes_received=1, payload_digest="x")
    assert supervisor.check(state, state.policy.hard_limit_seconds * 1000) == SupervisorDecision.CANCEL_HARD_LIMIT


def test_max_extensions_and_hard_limit_are_enforced():
    supervisor, state = session("benchmark.micro"); state.final_deadline_seconds = 90
    for index in range(5): supervisor.event(state, ProgressEventType.CONTENT_CHUNK, (80 + index * 15) * 1000, bytes_received=1, payload_digest=str(index))
    assert state.extension_count <= state.policy.max_extensions
    assert state.final_deadline_seconds <= state.policy.hard_limit_seconds


def test_deadline_only_has_no_idle_timeout():
    registry = ProviderOperationPolicyRegistry(); policy = registry.get("project.domain.simple")
    policy = type(policy)(**{**policy.__dict__, "supervision_mode": SupervisionMode.DEADLINE_ONLY})
    supervisor = ProviderExecutionSupervisor(); state = supervisor.start("r", "p", "m", policy, complexity(), LatencySnapshot("k",(),(),(),0,0), 0)
    state.connect_elapsed_ms = 1; state.first_progress_ms = 1; state.last_progress_ms = 1
    assert supervisor.check(state, policy.idle_progress_timeout_seconds * 1000 + 2) == SupervisorDecision.CONTINUE


def test_historical_p90_requires_three_successes():
    assert LatencySnapshot("k", (10, 20), (), (), 0, 0).historical_adjustment(base=10, hard_limit=100) == 0
    assert LatencySnapshot("k", (10, 20, 30), (), (), 0, 0).historical_adjustment(base=10, hard_limit=100) == 26


def test_current_snapshot_is_immutable_for_future_records(tmp_path):
    store = ProviderLatencyProfileStore(tmp_path / "latency.json"); snap = store.freeze("p","m","t","x")
    store.record(snap, success_seconds=30); assert snap.successful_seconds == ()
    assert store.freeze("p","m","t","x").successful_seconds == (30.0,)


class Response:
    status = 200
    headers = {"Content-Type": "application/json", "Authorization": "forbidden"}
    def __init__(self, body=b'{"ok":true}'):
        self.parts = [body, b""]; self.closed = False
    def read(self, _size): return self.parts.pop(0)
    def close(self): self.closed = True


def test_transport_closes_response_and_redacts_headers():
    response = Response(); transport = SupervisedHttpTransport(open_fn=lambda *_a, **_k: response)
    policy = ProviderOperationPolicyRegistry().get("project.domain.simple")
    result = transport.send(method="POST",url="https://example.test",headers={"Authorization":"secret"},body=b"{}",provider_id="qwen",model="m",policy=policy,complexity=complexity())
    assert response.closed and "authorization" not in result.headers
    assert result.receipt.contains_credentials is False


def test_transport_cancellation_has_no_worker_thread():
    before = {thread.ident for thread in threading.enumerate()}
    transport = SupervisedHttpTransport(open_fn=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("timeout")))
    policy = ProviderOperationPolicyRegistry().get("project.domain.simple")
    with pytest.raises(ProviderConnectionError):
        transport.send(method="POST",url="https://example.test",headers={},body=b"{}",provider_id="qwen",model="m",policy=policy,complexity=complexity())
    assert {thread.ident for thread in threading.enumerate()} == before


def test_receipt_and_events_contain_no_prompt_or_secret():
    response = Response(); transport = SupervisedHttpTransport(open_fn=lambda *_a, **_k: response)
    policy = ProviderOperationPolicyRegistry().get("project.domain.simple")
    result = transport.send(method="POST",url="https://example.test",headers={"Authorization":"TOPSECRET"},body=b'{"prompt":"PRIVATE"}',provider_id="qwen",model="m",policy=policy,complexity=complexity())
    serialized = json.dumps(result.receipt.as_dict())
    assert "TOPSECRET" not in serialized and "PRIVATE" not in serialized


def test_one_transport_send_is_one_operation():
    calls=[]; transport=SupervisedHttpTransport(open_fn=lambda *_a,**_k:(calls.append(1) or Response()))
    policy=ProviderOperationPolicyRegistry().get("project.domain.simple")
    transport.send(method="POST",url="https://example.test",headers={},body=b"{}",provider_id="qwen",model="m",policy=policy,complexity=complexity())
    assert calls == [1]


def test_supervise_contract_consumes_deterministic_progress_source():
    supervisor=ProviderExecutionSupervisor(); policy=ProviderOperationPolicyRegistry().get("project.domain.simple")
    result=supervisor.supervise({"request_id":"r","provider_id":"qwen","actual_model":"m","started_ms":0},policy,complexity(),[
        ("HEADERS_RECEIVED",10,{}),("CONTENT_CHUNK",20,{"bytes_received":2,"payload_digest":"x"}),("RESPONSE_COMPLETED",30,{})])
    assert result.decision == SupervisorDecision.COMPLETE
    assert result.receipt.termination_reason == "RESPONSE_COMPLETED"
