from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

from scripts import provider_transport
from scripts.agent_leaf_provider_guard import provider_readiness
from scripts.agent_real_provider_leaf_builder import _repair_prompt
from scripts.agent_conversation_loop import call_default_agent
from scripts.pipeline_planner_agent import plan_pipeline


def _payload() -> dict:
    return {"model": "gpt-5.4-nano", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10}


def _call(tmp_path: pathlib.Path, *, api_budget: str = "standard", project_id: str = "p1", task_id: str = "t1", post_once_fn=None):
    return provider_transport.governed_post_json_with_retry(
        "https://example.test/v1/responses",
        _payload(),
        "fake-provider-token",
        1,
        run_dir=tmp_path,
        project_id=project_id,
        task_id=task_id,
        agent_id="agent_a",
        request_type="leaf_generation",
        model="gpt-5.4-nano",
        endpoint_method="responses",
        api_budget=api_budget,
        post_once_fn=post_once_fn or (lambda endpoint, payload, token, timeout: ({"id": "ok", "output_text": "{}"}, "")),
        sleep_fn=lambda _: None,
        jitter_fn=lambda: 0,
    )


def test_api_budget_off_blocks_before_provider_call(tmp_path: pathlib.Path) -> None:
    calls = {"count": 0}

    def post_once(endpoint, payload, token, timeout):
        calls["count"] += 1
        return {"id": "bad"}, ""

    result = _call(tmp_path, api_budget="off", post_once_fn=post_once)
    assert result.error_type == provider_transport.BLOCKED_API_BUDGET
    assert calls["count"] == 0


def test_low_budget_exhaustion_blocks_before_call(tmp_path: pathlib.Path) -> None:
    for index in range(6):
        provider_transport.append_usage_event(
            tmp_path,
            request_id=f"r{index}",
            project_id="p1",
            task_id=f"t{index}",
            agent_id="agent_other",
            request_type="leaf_generation",
            model="gpt-5.4-nano",
            endpoint_method="responses",
            prompt_chars=10,
            requested_output_tokens=10,
            result_classification="ok",
        )
    result = _call(tmp_path, api_budget="low")
    assert result.error_type == provider_transport.BLOCKED_API_BUDGET


def test_pipeline_planner_keeps_api_budget_off(tmp_path: pathlib.Path, monkeypatch) -> None:
    session = tmp_path / "agent_session.jsonl"
    session.write_text('{"role":"user","content":"build"}\n', encoding="utf-8")
    monkeypatch.setattr("scripts.pipeline_planner_agent.local_model_router.call_json_task", lambda *args, **kwargs: {"ok": False})
    result = plan_pipeline(session, {"project_summary": "build"}, "gpt-5.4-nano", 1, api_budget="off")
    assert result["planner_fallback_reason"] == provider_transport.BLOCKED_API_BUDGET
    assert result["api_budget"] == "off"


def test_agent_conversation_loop_budget_off_blocks_before_provider_call(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr("scripts.agent_conversation_loop.check_connectivity._resolve_api_credentials", lambda: {"api_key": "fake-provider-token", "base_url": "https://example.test/v1"})
    calls = {"count": 0}

    def post_once(*args, **kwargs):
        calls["count"] += 1
        return {"id": "bad"}, ""

    monkeypatch.setattr("scripts.provider_transport.post_json_with_retry", post_once)
    try:
        call_default_agent([{"role": "user", "content": "build"}], "gpt-5.4-nano", 1, run_dir=tmp_path, api_budget="off")
    except RuntimeError as exc:
        assert provider_transport.BLOCKED_API_BUDGET in str(exc)
    else:
        raise AssertionError("expected budget block")
    assert calls["count"] == 0


def test_same_fingerprint_hits_cache_and_different_project_does_not(tmp_path: pathlib.Path) -> None:
    calls = {"count": 0}

    def post_once(endpoint, payload, token, timeout):
        calls["count"] += 1
        return {"id": f"ok-{calls['count']}", "output_text": "{}"}, ""

    first = _call(tmp_path, post_once_fn=post_once)
    second = _call(tmp_path, post_once_fn=post_once)
    third = _call(tmp_path, project_id="p2", post_once_fn=post_once)
    assert first.ok and second.ok and third.ok
    assert calls["count"] == 2
    ledger = provider_transport.usage_ledger_path(tmp_path).read_text(encoding="utf-8")
    assert '"cache_hit": true' in ledger


def test_readiness_cache_reuses_same_run_smoke(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr("scripts.agent_leaf_provider_guard.check_connectivity._resolve_api_credentials", lambda: {"api_key": "fake-provider-token", "base_url": "https://example.test/v1"})
    calls = {"count": 0}

    def smoke(model, timeout, attempts):
        calls["count"] += 1
        return {"ok": True, "attempts": [{"attempt": 1}], "selected_method": "responses", "endpoint_mode": "responses", "base_url_domain": "example.test"}

    monkeypatch.setattr("scripts.agent_leaf_provider_guard.provider_api_smoke.run_smoke", smoke)
    assert provider_readiness(out_dir=tmp_path, model="gpt-5.4-nano")["provider_ready"] is True
    cached = provider_readiness(out_dir=tmp_path, model="gpt-5.4-nano")
    assert cached["readiness_cache_hit"] is True
    assert calls["count"] == 1


def test_quota_or_unsupported_opens_circuit_and_blocks_followup(tmp_path: pathlib.Path) -> None:
    def quota(endpoint, payload, token, timeout):
        return None, "HTTP 403: Key usage limit exceeded [retryable=false]"

    first = _call(tmp_path, post_once_fn=quota)
    assert first.error_type == "PROVIDER_KEY_USAGE_LIMIT"
    second = _call(tmp_path)
    assert second.error == "BLOCKED_PROVIDER_CIRCUIT_OPEN"


def test_non_retryable_error_does_not_retry_and_retryable_respects_cap(tmp_path: pathlib.Path) -> None:
    non_retry_calls = {"count": 0}

    def non_retry(endpoint, payload, token, timeout):
        non_retry_calls["count"] += 1
        return None, "HTTP 400: bad request [retryable=false]"

    _call(tmp_path / "non_retry", post_once_fn=non_retry)
    assert non_retry_calls["count"] == 1
    retry_calls = {"count": 0}

    def retry(endpoint, payload, token, timeout):
        retry_calls["count"] += 1
        return None, "HTTP 503: unavailable [retryable=true]"

    _call(tmp_path / "retry", api_budget="low", post_once_fn=retry)
    assert retry_calls["count"] == 2


def test_missing_file_repair_prompt_is_incremental_and_shorter() -> None:
    base = "BASE PROMPT\n" + ("full context\n" * 200)
    prompt, repair_type = _repair_prompt(
        base,
        classification="real_provider_leaf_missing_files",
        missing=["tests/test_search.py"],
        test_result=None,
        allowed_files=["app/search.py", "tests/test_search.py"],
    )
    assert repair_type == "missing_files"
    assert "tests/test_search.py" in prompt
    assert "Do not resend unchanged allowed files" in prompt
    assert len(prompt) < len(base)


def test_usage_ledger_redacts_secrets_and_records_actual_usage(tmp_path: pathlib.Path) -> None:
    result = _call(
        tmp_path,
        post_once_fn=lambda endpoint, payload, token, timeout: ({"id": "ok", "output_text": "{}", "usage": {"input_tokens": 7, "output_tokens": 3}}, ""),
    )
    assert result.ok
    text = provider_transport.usage_ledger_path(tmp_path).read_text(encoding="utf-8")
    assert "sk-secret" not in text and "Bearer" not in text
    event = json.loads(text.splitlines()[0])
    assert event["actual_usage_present"] is True
    assert event["actual_usage"]["input_tokens"] == 7


def test_usage_ledger_keeps_estimate_when_provider_usage_missing(tmp_path: pathlib.Path) -> None:
    _call(tmp_path)
    event = json.loads(provider_transport.usage_ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()[0])
    assert event["actual_usage_present"] is False
    assert event["estimated_input_tokens"] >= 1


def test_half_open_circuit_allows_one_probe_and_closes_on_success(tmp_path: pathlib.Path) -> None:
    provider_transport.open_circuit(tmp_path, reason="PROVIDER_KEY_USAGE_LIMIT", provider_key="responses:gpt-5.4-nano")
    state = json.loads(provider_transport.circuit_path(tmp_path).read_text(encoding="utf-8"))
    state["opened_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    provider_transport.circuit_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    calls = {"count": 0}

    def ok(endpoint, payload, token, timeout):
        calls["count"] += 1
        return {"id": "ok", "output_text": "{}"}, ""

    result = _call(tmp_path, post_once_fn=ok)
    assert result.ok
    assert calls["count"] == 1
    assert provider_transport.circuit_state(tmp_path)["state"] == "closed"


def test_half_open_probe_in_progress_blocks_duplicate_probe(tmp_path: pathlib.Path) -> None:
    provider_transport.circuit_path(tmp_path).write_text(
        json.dumps(
            {
                "state": "open",
                "reason": "PROVIDER_KEY_USAGE_LIMIT",
                "provider_key": "responses:gpt-5.4-nano",
                "opened_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "half_open_probe_in_progress": True,
            }
        ),
        encoding="utf-8",
    )
    calls = {"count": 0}
    result = _call(tmp_path, post_once_fn=lambda *args: (calls.__setitem__("count", calls["count"] + 1) or {"id": "bad"}, ""))
    assert result.error == "BLOCKED_PROVIDER_CIRCUIT_OPEN"
    assert calls["count"] == 0


def test_corrupt_or_stale_cache_is_ignored_and_replaced(tmp_path: pathlib.Path) -> None:
    first = _call(tmp_path)
    assert first.ok
    cache_file = next((tmp_path / "provider_request_cache").glob("*.json"))
    cache_file.write_text("{bad json", encoding="utf-8")
    calls = {"count": 0}

    def ok(endpoint, payload, token, timeout):
        calls["count"] += 1
        return {"id": "fresh", "output_text": "{}"}, ""

    second = _call(tmp_path, post_once_fn=ok)
    assert second.ok
    assert calls["count"] == 1
    assert json.loads(cache_file.read_text(encoding="utf-8"))["schema_version"] == "provider_cache_v2"


def test_budget_reservations_count_until_completed(tmp_path: pathlib.Path) -> None:
    for index in range(6):
        reservation = provider_transport.reserve_api_budget(
            tmp_path,
            request_id=f"r{index}",
            api_budget="low",
            agent_id=f"agent_{index}",
            task_id=f"task_{index}",
            request_type="leaf_generation",
            request_fingerprint_value=f"fp{index}",
        )
        assert reservation["allowed"] is True
    blocked = provider_transport.reserve_api_budget(
        tmp_path,
        request_id="r_blocked",
        api_budget="low",
        agent_id="agent_b",
        task_id="task_blocked",
        request_type="leaf_generation",
        request_fingerprint_value="fp_blocked",
    )
    assert blocked["reason"] == provider_transport.BLOCKED_API_BUDGET
    provider_transport.complete_api_budget_reservation(tmp_path, "res_r0")
    allowed = provider_transport.reserve_api_budget(
        tmp_path,
        request_id="r_after",
        api_budget="low",
        agent_id="agent_b",
        task_id="task_after",
        request_type="leaf_generation",
        request_fingerprint_value="fp_after",
    )
    assert allowed["allowed"] is True


def test_priority_context_pack_preserves_frozen_facts_and_truncates_low_priority_context() -> None:
    pack = provider_transport.build_context_pack(
        frozen_facts={"goal": "must keep this frozen goal", "non_negotiable": "local_packager"},
        current_task={"task_id": "task_search"},
        allowed_scope=["app/search.py"],
        relevant_file_excerpts={"large.py": "x" * 5000},
        max_prompt_chars=500,
    )
    prompt = pack["prompt"]
    assert "must keep this frozen goal" in prompt
    assert "local_packager" in prompt
    assert "[truncated]" in prompt
    assert len(prompt) <= 1000
