import pytest

from cgkn.application.software_project.contracts import WorkerScope, canonical_hash


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
