from __future__ import annotations

from benchmarks.knowledge_persistence_scaling import workloads


def test_workload_traces_are_exact_and_ratio_correct() -> None:
    read = workloads.workload_trace("read_heavy")
    balanced = workloads.workload_trace("balanced")
    write = workloads.workload_trace("write_heavy")
    assert len(read) == len(balanced) == len(write) == 1_000
    assert (read.count("QUERY"), read.count("UPDATE")) == (910, 90)
    assert (balanced.count("QUERY"), balanced.count("UPDATE")) == (500, 500)
    assert (write.count("QUERY"), write.count("UPDATE")) == (90, 910)
    assert len(set(workloads.workload_hashes().values())) == 3


def test_workload_trace_rejects_unknown_mix() -> None:
    try:
        workloads.workload_trace("unknown")
    except ValueError as exc:
        assert str(exc) == "unknown"
    else:
        raise AssertionError("unknown workload should fail")
