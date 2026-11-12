import hashlib
import json
import subprocess
import sys
from types import MappingProxyType

import pytest
from cgkn.artifacts.evidence_identity import identity, digest
from cgkn.artifacts.locking import exclusive_file, StateStoreError
from cgkn.state.store import FileRunStore
from cgkn.state.acceptance import GoalAcceptance
from cgkn.runtime.acceptance import open_goal_acceptance
from cgkn.runtime.node_authority import ExecutionAuthority


@pytest.mark.happy_path
@pytest.mark.roundtrip
def test_host_assembly_preserves_single_acceptance_owner(tmp_path):
    store = FileRunStore(tmp_path)
    value = open_goal_acceptance(store, 'p', 'r', {'R': {'must': True}}, {})
    assert type(value) is GoalAcceptance
    assert isinstance(value.execution_authority, ExecutionAuthority)
    assert not value.view()['complete']
    restored = open_goal_acceptance(store, 'p', 'r', {'R': {'must': True}}, {})
    assert restored.view() == value.view()


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.security
def test_state_acceptance_cannot_silently_construct_authority(tmp_path):
    store = FileRunStore(tmp_path)
    value = GoalAcceptance(store, 'p', 'r', {'R': {'must': True}}, {})
    with pytest.raises(ValueError, match='ACCEPTANCE_EXECUTION_AUTHORITY_REQUIRED'):
        value.view()
    wrong = ExecutionAuthority(store, 'p', 'other')
    with pytest.raises(ValueError, match='ACCEPTANCE_AUTHORITY_SCOPE_MISMATCH'):
        GoalAcceptance(store, 'p', 'r', {'R': {'must': True}}, {}, execution_authority=wrong)


@pytest.mark.happy_path
@pytest.mark.boundary
def test_existing_identity_bytes_and_mapping_projection_are_preserved():
    value = {'units': ['毫秒', 1.25], 'unknown': None}
    expected = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert identity(value) == expected
    assert digest(MappingProxyType(value)) == expected


@pytest.mark.negative
@pytest.mark.fault_injection
@pytest.mark.security
def test_shared_lock_excludes_other_process_and_releases(tmp_path):
    lock = tmp_path / 'state.lock'
    code = ("from cgkn.artifacts.locking import exclusive_file; import sys; "
            "ctx=exclusive_file(sys.argv[1],sys.argv[2]); ctx.__enter__(); ctx.__exit__(None,None,None)")
    with exclusive_file(tmp_path, lock):
        blocked = subprocess.run([sys.executable, '-c', code, str(tmp_path), str(lock)], capture_output=True)
        assert blocked.returncode != 0 and b'active coordinator' in blocked.stderr
    released = subprocess.run([sys.executable, '-c', code, str(tmp_path), str(lock)], capture_output=True)
    assert released.returncode == 0, released.stderr
    with pytest.raises(StateStoreError, match='escapes'):
        with exclusive_file(tmp_path, tmp_path.parent / 'outside.lock'):
            pass


@pytest.mark.boundary
def test_low_authority_import_does_not_load_scheduler():
    code = "import sys; import cgkn.runtime.node_authority; assert 'cgkn.runtime.dag_runner' not in sys.modules"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True)
    assert result.returncode == 0, result.stderr
