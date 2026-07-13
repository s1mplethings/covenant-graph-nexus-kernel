from __future__ import annotations

import json
import pathlib

from scripts.agent_reputation_store import (
    load_reputation_store,
    record_reputation_event,
    reputation_snapshot,
    save_reputation_store,
    select_with_reputation,
)


def test_cross_run_reputation_is_domain_and_task_isolated(tmp_path: pathlib.Path) -> None:
    store = tmp_path / "reputation.json"
    for index in range(3):
        record_reputation_event(
            store,
            agent_id="agent_a",
            role="SearchServiceLeafAgent",
            domain="knowledge_studio",
            task_type="knowledge_search",
            event_type="task_completed",
            first_pass=True,
        )
    run2 = select_with_reputation(["agent_b", "agent_a"], path=store, domain="knowledge_studio", task_type="knowledge_search")
    run3 = select_with_reputation(["agent_b", "agent_a"], path=store, domain="media_analysis_tool", task_type="image_pipeline")
    assert run2["selected_agent"] == "agent_a"
    assert run3["candidates"][0]["score"] == run3["candidates"][1]["score"]
    assert run3["selected_agent"] == "agent_a"  # deterministic tie-break only, not evidence-backed cross-domain preference
    assert run3["snapshot"]["records"] == {}


def test_provider_quota_does_not_lower_reputation(tmp_path: pathlib.Path) -> None:
    store = tmp_path / "reputation.json"
    before = record_reputation_event(
        store,
        agent_id="agent_a",
        role="SearchServiceLeafAgent",
        domain="knowledge_studio",
        task_type="knowledge_search",
        event_type="task_completed",
        first_pass=True,
    )
    after = record_reputation_event(
        store,
        agent_id="agent_a",
        role="SearchServiceLeafAgent",
        domain="knowledge_studio",
        task_type="knowledge_search",
        event_type="provider_quota",
    )
    assert after["failed_tasks"] == before["failed_tasks"]
    assert after["scope_discipline"] == before["scope_discipline"]


def test_reputation_decay_reduces_permanent_advantage(tmp_path: pathlib.Path) -> None:
    store = tmp_path / "reputation.json"
    for _ in range(4):
        record_reputation_event(store, agent_id="agent_a", role="SearchServiceLeafAgent", domain="knowledge_studio", task_type="knowledge_search", event_type="task_completed", first_pass=True)
    strong = select_with_reputation(["agent_a", "agent_b"], path=store, domain="knowledge_studio", task_type="knowledge_search", decay_factor=1.0)
    decayed = select_with_reputation(["agent_a", "agent_b"], path=store, domain="knowledge_studio", task_type="knowledge_search", decay_factor=0.35)
    gap_strong = strong["candidates"][0]["score"] - strong["candidates"][1]["score"]
    gap_decayed = decayed["candidates"][0]["score"] - decayed["candidates"][1]["score"]
    assert gap_decayed < gap_strong


def test_reputation_store_migrates_old_version_and_writes_atomically(tmp_path: pathlib.Path) -> None:
    store = tmp_path / "reputation.json"
    store.write_text(json.dumps({"version": 0, "records": {}}), encoding="utf-8")
    loaded = load_reputation_store(store)
    assert loaded["version"] == 1
    loaded["records"]["x"] = {"agent_id": "x"}
    save_reputation_store(loaded, store)
    assert json.loads(store.read_text(encoding="utf-8"))["records"]["x"]["agent_id"] == "x"
    assert not list(tmp_path.glob("*.tmp"))

