from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from experiments.release_058.analysis import analyze
from experiments.release_058.essential_workload import (
    BASELINES,
    FAMILIES,
    development_chains,
    formal_chains,
    workload_manifest,
)
from experiments.release_058.runner import _RouteState, build_execution_packet, evaluate_episode, run_chain
from cgnk_knowledge import internalize_evidence, new_project_knowledge_pack, retrieve_relevant_knowledge


@dataclass
class _Completion:
    text: str
    model: str = "fixture-cheap"
    request_id: str = "fixture-request"
    usage: dict | None = None
    attempts: int = 1


def _scripted(chain):
    by_id = {episode.episode_id: episode for episode in chain.episodes}

    def complete(run_id, episode_id, packet, model_config):
        episode = by_id[episode_id]
        return _Completion(json.dumps({
            "answer": " ".join(episode.expected_terms),
            "evidence_ids": list(episode.required_evidence_ids),
            "action": episode.expected_action,
            "state_refs": list(episode.required_evidence_ids),
            "reused_capability_ids": list(episode.expected_capability_ids),
        }), usage={"prompt_tokens": 100, "completion_tokens": 20})

    return complete


def test_workload_has_frozen_split_family_and_episode_counts() -> None:
    manifest = workload_manifest()
    assert len(development_chains()) == 12
    assert len(formal_chains()) == 18
    assert manifest["total_chain_count"] == 30
    assert manifest["development_episode_count"] == 60
    assert manifest["formal_episode_count"] == 90
    assert set(row.family for row in formal_chains()) == set(FAMILIES)
    assert len({row.scenario_id for row in (*development_chains(), *formal_chains())}) == 30
    assert manifest["manifest_hash"].startswith("sha256:")


def test_public_task_projection_contains_no_gold() -> None:
    forbidden = {"expected_terms", "required_evidence_ids", "forbidden_terms", "expected_action", "expected_capability_ids"}
    for chain in (*development_chains(), *formal_chains()):
        for episode in chain.episodes:
            assert forbidden.isdisjoint(episode.public_task())


def test_b0_and_b1_receive_same_underlying_sources_but_different_organization(tmp_path: pathlib.Path) -> None:
    chain = development_chains()[0]
    episode = chain.episodes[0]
    b0 = _RouteState(BASELINES[0], tmp_path / "b0", list(episode.additions))
    b1 = _RouteState(BASELINES[1], tmp_path / "b1", list(episode.additions))
    p0, ids0 = build_execution_packet(b0, chain, episode)
    p1, ids1 = build_execution_packet(b1, chain, episode)
    assert ids0 == ids1
    assert p0["project_context"]["kind"] == "DirectWorkspaceSourcesV1"
    assert p1["project_context"]["kind"] == "FlatProjectStateV1"
    assert "history_index" not in p0["project_context"]
    assert "history_index" in p1["project_context"]
    assert "knowledge_index" not in json.dumps(p1)


def test_historical_query_can_retrieve_superseded_raw_source() -> None:
    pack = new_project_knowledge_pack("history")
    first = internalize_evidence(pack, {
        "content": "App port is 8000.", "item_type": "research_finding", "scope": "project",
        "source_ref": "PORT.V1", "subject_ref": "app.port", "branch_ref": "app", "source_version": "1",
    })["pack"]
    second = internalize_evidence(first, {
        "content": "App port is 9000.", "item_type": "research_finding", "scope": "project",
        "source_ref": "PORT.V2", "subject_ref": "app.port", "branch_ref": "app", "source_version": "2",
    })["pack"]
    result = retrieve_relevant_knowledge(second, {
        "goal": "historical app port 8000 current 9000", "require_relevance": True,
        "include_superseded": True, "include_archived": True, "max_items": 5,
    })
    refs = {ref for item in result["selected_items"] for ref in item.get("source_refs", ())}
    assert {"PORT.V1", "PORT.V2"} <= refs


def test_all_development_cgnk_packets_expose_required_evidence_and_restart(tmp_path: pathlib.Path) -> None:
    for chain in development_chains():
        result = run_chain(chain, BASELINES[2], tmp_path, _scripted(chain), model_config={"model": "fixture-cheap"})
        assert result["chain_success"], (chain.scenario_id, [row["failure_classes"] for row in result["episodes"]])
        assert result["logical_calls"] == 5
        assert result["restart_recovery"] is True


def test_evaluator_rejects_stale_answer_and_invented_source() -> None:
    episode = development_chains()[0].episodes[3]
    result = evaluate_episode(episode, {
        "answer": "The old port is 8001.",
        "evidence_ids": ["invented"], "action": "ANSWER",
        "state_refs": [], "reused_capability_ids": [],
    }, (episode.required_evidence_ids[0],))
    assert result["success"] is False
    assert "STALE_STATE" in result["failure_classes"]
    assert "PROVENANCE_ERROR" in result["failure_classes"]


def test_evaluator_accepts_plus_symbol_and_capability_subject_prefix() -> None:
    capability_chain = next(row for row in development_chains() if row.family == "W5_CAPABILITY_REUSE_COMPOSITION")
    capability_episode = capability_chain.episodes[0]
    capability = capability_episode.expected_capability_ids[0]
    result = evaluate_episode(capability_episode, {
        "answer": f"Reuse {capability}.",
        "evidence_ids": list(capability_episode.required_evidence_ids), "action": "REUSE",
        "state_refs": [], "reused_capability_ids": [f"capability.{capability}"],
    }, capability_episode.required_evidence_ids)
    assert result["success"] is True

    repair_chain = next(row for row in development_chains() if row.family == "W4_REPAIR_CONTINUITY")
    repair_episode = repair_chain.episodes[1]
    result = evaluate_episode(repair_episode, {
        "answer": f"Preserve a leading + in {repair_episode.expected_terms[0]} and change normalize.py.",
        "evidence_ids": list(repair_episode.required_evidence_ids), "action": "REPAIR",
        "state_refs": [], "reused_capability_ids": [],
    }, repair_episode.required_evidence_ids)
    assert result["success"] is True


def test_chain_level_analysis_preserves_paired_unit(tmp_path: pathlib.Path) -> None:
    chain = development_chains()[0]
    runs = [
        run_chain(chain, baseline, tmp_path, _scripted(chain), model_config={"model": "fixture-cheap"})
        for baseline in BASELINES
    ]
    result = analyze(runs)
    comparison = result["comparisons"][f"{BASELINES[1]}_VS_B2_CGNK_CURRENT"]
    assert comparison["chain_count"] == 1
    assert comparison["mcnemar"]["discordant"] == 0
