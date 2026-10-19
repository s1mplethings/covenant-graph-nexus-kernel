import pytest

from cgkn.application.software_project.contracts import MAX_COHESIVE_WRITE_FILES, WorkerScope, canonical_hash


@pytest.mark.happy_path
@pytest.mark.determinism
def test_contract_hash_is_deterministic():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


@pytest.mark.negative
@pytest.mark.security
def test_worker_scope_rejects_delete_and_overbroad_targets():
    with pytest.raises(ValueError):
        WorkerScope(("a.py",), allow_delete=True)
    with pytest.raises(ValueError):
        WorkerScope(("a.py", "b.py", "c.py"), target_paths=("a.py", "b.py", "c.py"))


@pytest.mark.happy_path
@pytest.mark.boundary
def test_worker_scope_uses_one_bounded_write_ceiling_without_counting_reads():
    four = tuple(f"owned-{index}.py" for index in range(4))
    five = tuple(f"owned-{index}.py" for index in range(MAX_COHESIVE_WRITE_FILES))
    reads = ("dependency-a.py", "dependency-b.py")

    scope = WorkerScope(four + reads, four, max_write_files=4)
    assert scope.visible_paths == four + reads
    assert scope.writable_paths == four
    assert WorkerScope(five, five, max_write_files=5).writable_paths == five

    with pytest.raises(ValueError, match="max_write_files"):
        WorkerScope(five + ("owned-5.py",), five + ("owned-5.py",), max_write_files=6)
    with pytest.raises(ValueError, match="write-file limit"):
        WorkerScope(four, four, max_write_files=3)
