from __future__ import annotations

from collections import Counter
import json

import pytest

from experiments.release_060.contracts import ArchitectureBaseline, EvaluationPolicy, canonical_hash
from experiments.release_060.leakage import check_family_leakage, model_packet
from experiments.release_060.specs import development_families, formal_families, full_manifest


def test_family_counts_types_and_complexity_balance() -> None:
    development = development_families(); formal = formal_families()
    assert len(development) == 12
    assert Counter(item.complexity for item in development) == {"LOW": 4, "MEDIUM": 4, "HIGH": 4}
    assert len(formal) == 24
    assert Counter(item.complexity for item in formal) == {"LOW": 8, "MEDIUM": 8, "HIGH": 8}
    assert set(Counter(item.project_type for item in formal).values()) == {3}


def test_formal_coverage_requirements() -> None:
    formal = formal_families()
    modes = lambda item: {episode.mode for episode in item.episodes}
    assert sum("RESTART_RESUME" in modes(item) for item in formal if item.complexity == "HIGH") >= 4
    assert sum("VERSION_CHANGE" in modes(item) for item in formal if item.complexity in {"MEDIUM", "HIGH"}) >= 4
    assert sum("BUG_REPAIR" in modes(item) for item in formal) >= 6
    assert sum("FEATURE_EXTENSION" in modes(item) for item in formal) >= 8
    assert sum(item.provenance_sensitive for item in formal) >= 4
    assert sum(item.raw_complexity["state_dependency_count"] > 0 for item in formal) >= 6
    assert sum(item.capability_heavy for item in formal if item.complexity in {"MEDIUM", "HIGH"}) >= 4


def test_manifest_is_stable_and_private_cases_are_not_in_public_specs() -> None:
    first = full_manifest(); second = full_manifest()
    assert first == second
    assert first["manifest_hash"] == canonical_hash({key: value for key, value in first.items() if key != "manifest_hash"})
    encoded = json.dumps(first, sort_keys=True)
    assert "private_cases" not in encoded
    assert "private_evaluator_packet" not in encoded


def test_family_leakage_gate_and_model_packets() -> None:
    families = development_families() + formal_families()
    receipt = check_family_leakage(families)
    assert receipt["status"] == "PASS", receipt["findings"]
    for family in families:
        for index in range(len(family.episodes)):
            packet = model_packet(family, index)
            assert packet["private_evaluator"] == "WITHHELD"
            assert "private_cases" not in json.dumps(packet, sort_keys=True)


def test_fair_policy_and_baselines_are_frozen() -> None:
    policy = EvaluationPolicy()
    assert policy.provider == "deepseek"
    assert policy.model == "deepseek-flash"
    assert policy.corpus_read_enabled is False
    assert policy.network_enabled is False
    assert policy.manual_intervention == 0
    assert {item.value for item in ArchitectureBaseline} == {
        "B0_DIRECT_CHEAP", "B1_DIRECT_CHEAP_FLAT_STATE", "B2_MINIMAL_CGNK", "B3_FULL_CGNK",
    }


@pytest.mark.parametrize("bad", [dict(provider="qwen"), dict(model="deepseek-chat"), dict(temperature=0.2), dict(network_enabled=True), dict(corpus_read_enabled=True), dict(manual_intervention=1)])
def test_policy_fails_closed(bad: dict) -> None:
    with pytest.raises(ValueError):
        EvaluationPolicy(**bad)
