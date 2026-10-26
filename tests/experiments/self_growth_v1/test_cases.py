from __future__ import annotations

from collections import Counter

from experiments.self_growth_v1.cases import family_fixtures, ordered_task_stream, stream_hashes


def test_stream_is_frozen_ordered_and_has_required_distribution() -> None:
    stream = ordered_task_stream()
    assert len(stream) == 100
    assert len({item.need.task_id for item in stream}) == 100
    assert Counter(item.expected_class for item in stream) == {
        "REUSE": 45,
        "COMPOSE": 25,
        "TRUE_GAP": 15,
        "NON_CAPABILITY_GAP": 10,
        "CRITICAL_STOP": 5,
    }
    assert len(family_fixtures()) == 15


def test_stream_windows_have_accumulation_structure() -> None:
    stream = ordered_task_stream()
    early = Counter(item.expected_class for item in stream[:20])
    late = Counter(item.expected_class for item in stream[80:])
    assert early["TRUE_GAP"] == 5
    assert early["COMPOSE"] == 0
    assert late["TRUE_GAP"] == 0
    assert late["COMPOSE"] == 14
    assert late["REUSE"] == 5


def test_hidden_qualification_is_not_in_public_task_payload() -> None:
    case = next(item for item in ordered_task_stream() if item.expected_class == "TRUE_GAP")
    public = case.public_dict()
    assert "hidden_examples" not in public
    assert case.hidden_examples
    assert case.evaluator_dict()["hidden_examples"]


def test_stream_hashes_are_complete_and_stable() -> None:
    first = stream_hashes()
    second = stream_hashes()
    assert first == second
    assert set(first) == {"task_stream_hash", "expected_class_hash", "qualification_set_hash", "rubric_hash"}
    assert all(value.startswith("sha256:") for value in first.values())
