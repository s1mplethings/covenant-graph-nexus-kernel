from __future__ import annotations

import importlib.util
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_release_056_profile", ROOT / "scripts" / "run_release_056_profile.py"
)
assert SPEC and SPEC.loader
PROFILE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROFILE
SPEC.loader.exec_module(PROFILE)


def test_small_knowledge_profile_is_correct_and_source_bound() -> None:
    row = PROFILE.profile_knowledge_scale(100, 1)
    assert row["size"] == 100
    assert row["retrieval"]["recall_pass"] is True
    assert row["retrieval"]["accuracy"] == 1.0
    assert row["retrieval"]["latency_ms"]["p95"] is not None
    assert row["context_assembly"]["provider_calls"] == 0
    assert row["hotspots"]


def test_profile_receipt_hash_is_deterministic_for_same_body() -> None:
    value = {"a": [1, 2], "b": "x"}
    assert PROFILE.stable_hash(value) == PROFILE.stable_hash({"b": "x", "a": [1, 2]})
