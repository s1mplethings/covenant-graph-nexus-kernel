from __future__ import annotations

import pathlib
import sys

import pytest


SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import receipt_freshness
import source_boundaries


def test_boundaries_classify_only_their_owned_source() -> None:
    assert source_boundaries.BOUNDARIES["kernel"].contains("cgkn/runtime/dag_runner.py")
    assert not source_boundaries.BOUNDARIES["kernel"].contains("cgkn/application/software_project/service.py")
    assert source_boundaries.BOUNDARIES["application"].contains("tests/application/software_project/test_bundle.py")
    assert source_boundaries.BOUNDARIES["application"].contains("scripts/obligation_traceability_gate.py")
    assert source_boundaries.BOUNDARIES["experiment"].contains("experiments/semantic_artifact_design/common/runner.py")
    assert not source_boundaries.BOUNDARIES["experiment"].contains("experiments/semantic_artifact_design/receipts/repeat.json")


def test_boundary_identity_is_stable_and_unknown_boundary_fails() -> None:
    assert source_boundaries.boundary_identity("kernel") == source_boundaries.boundary_identity("kernel")
    with pytest.raises(ValueError, match="unknown source boundary"):
        source_boundaries.boundary_identity("unknown")


def test_current_receipts_are_fresh_in_their_own_boundaries() -> None:
    value = receipt_freshness.check_all()
    assert value["status"] == "PASS", value
    assert {item["boundary"] for item in value["results"]} == {"kernel", "application", "experiment"}


def test_worktree_identity_detects_uncommitted_new_changed_and_deleted_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(source_boundaries,'ROOT',tmp_path)
    names=['cgkn/runtime/old.py','cgkn/protocol/new.py']
    monkeypatch.setattr(source_boundaries,'_git',lambda *args:
        '\0'.join(names)+'\0' if args[0]=='ls-files' else 'a'*40)
    for name in names:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('value=1')
    first=source_boundaries.boundary_identity('kernel','WORKTREE')
    assert first['path_count']==2 and first['identity_mode']=='WORKTREE_SHA256'
    (tmp_path/names[1]).write_text('value=2')
    second=source_boundaries.boundary_identity('kernel','WORKTREE')
    assert first['boundary_hash']!=second['boundary_hash']
    (tmp_path/names[0]).unlink()
    third=source_boundaries.boundary_identity('kernel','WORKTREE')
    assert third['path_count']==1 and third['boundary_hash']!=second['boundary_hash']
    assert source_boundaries.boundary_identity('kernel','WORKTREE')==third
