from __future__ import annotations

from collections import Counter

from scripts.run_self_growth_benchmarks import longevity_task_stream


def test_longevity_stream_is_frozen_unique_and_saturating() -> None:
    stream = longevity_task_stream(500)
    assert len(stream) == 500
    assert len({case.need.task_id for case in stream}) == 500
    first = Counter(case.expected_class for case in stream[:100])
    tail = Counter(case.expected_class for case in stream[100:])
    assert first["TRUE_GAP"] == 15
    assert tail["TRUE_GAP"] == 0
    assert tail["REUSE"] and tail["COMPOSE"]
    assert tail["NON_CAPABILITY_GAP"] and tail["CRITICAL_STOP"]


def test_longevity_stream_rejects_out_of_policy_sizes() -> None:
    for count in (499, 1001):
        try:
            longevity_task_stream(count)
        except ValueError as exc:
            assert "between 500 and 1000" in str(exc)
        else:
            raise AssertionError("expected ValueError")
