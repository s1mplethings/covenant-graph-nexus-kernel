import os
import json
import hashlib
import shutil
import tempfile
import pytest
from milestones.milestone_4e7c26281cf61a85851e.api import handle

def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def _create_project(data_dir, project_id):
    # Assuming M1 API exists or we mock the state. 
    # Since we only have M2 api.py in context, we assume handle dispatches to internal logic that might rely on M1.
    # However, the prompt says "Reuse M1 project isolation". We need to ensure projects exist.
    # If M1 is not imported here, we might need to create the directory structure manually if the API expects it.
    # Let's assume for testing purposes we can just call ops and they fail if project doesn't exist.
    # To make tests pass, we likely need to initialize a project first via some means or assume the test fixture does it.
    # Given the constraints, I will assume there is a way to create a project or the tests should handle ValueError for missing project.
    # But acceptance criteria imply positive paths work. 
    # I will add a helper to create a dummy project structure if needed, or assume `handle` with op='project.create' exists? 
    # The contract only lists evidence.* and signal.*. It mentions "Validates inputs against M1 project existence".
    # This implies M1 handles project creation. Since I cannot import M1 (not in allowed read/write paths explicitly as a module to import from, though path 0 is M2 api), 
    # I must assume the test environment provides a way to set up projects or I use a fixture.
    # Wait, the allowed_read_paths includes the M2 api file. It does NOT include M1 api file. 
    # This suggests I should not import M1 directly. 
    # How do I create a project? Maybe the `handle` function itself supports 'project.create'? No, contract says ops are evidence.*, signal.*.
    # Perhaps the test setup creates the directory structure manually?
    # Or maybe `handle` implicitly creates the project dir if it doesn't exist? Unlikely given "validates against M1 project existence".
    # Let's look at the edge behavior: "Invalid input... non-existent project... raise ValueError".
    # So I need existing projects.
    # I will assume a standard pattern where I can create the project directory manually in the data_dir before calling handle.
    # M1 persistence is filesystem-based. Usually this means a folder named after project_id in data_dir/projects/ or similar.
    # Without knowing M1's exact layout, this is risky.
    # However, often in these challenges, if M1 isn't exposed, maybe the M2 `handle` has a hidden init or the tests are expected to fail on missing project unless created.
    # Let's try creating a directory `data_dir/projects/{project_id}` as a guess for M1 structure, or better yet, check if there's a generic way.
    # Actually, looking at previous milestones, usually there's an explicit project creation step. 
    # If I can't import M1, I can't call M1.handle.
    # Is it possible the M2 api.py imports M1 internally? Yes. 
    # Can I trigger project creation via M2? No.
    # Maybe the test fixture `tmp_path` combined with manual directory creation works.
    # Let's assume M1 stores projects in `data_dir / "projects" / project_id`. 
    # I'll write a helper `_ensure_project` that creates this dir.
    pass

def _ensure_project(data_dir, project_id):
    proj_dir = os.path.join(data_dir, "projects", project_id)
    os.makedirs(proj_dir, exist_ok=True)
    # Create a metadata file if needed by M1? Unknown. Just dir might be enough for existence check.
    return proj_dir

def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def test_evidence_import_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "file1.txt"), "hello world")
        _write_file(os.path.join(source_dir, "sub/file2.txt"), "foo bar")
        
        req = {
            "op": "evidence.import",
            "project_id": project_id,
            "path": source_dir
        }
        res = handle(data_dir, req)
        
        assert "id" in res
        assert res["project_id"] == project_id
        assert res["status"] == "ACTIVE" # Assumed status name, contract says status field exists. Edge behavior doesn't specify value, but usually ACTIVE.
        assert len(res["files"]) == 2
        
        # Check SHA256
        sha1 = _sha256(b"hello world")
        found = False
        for f in res["files"]:
            if f["path"] == "file1.txt":
                assert f["sha256"] == sha1
                assert f["text"] == "hello world"
                found = True
        assert found

def test_evidence_import_nonexistent_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        req = {
            "op": "evidence.import",
            "project_id": "nonexistent",
            "path": tmpdir
        }
        with pytest.raises(ValueError):
            handle(data_dir, req)

def test_evidence_refresh_no_change():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "file1.txt"), "content v1")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        ver1 = res_imp["version"]
        
        req_ref = {"op": "evidence.refresh", "project_id": project_id, "evidence_id": eid}
        res_ref = handle(data_dir, req_ref)
        
        assert res_ref["id"] == eid
        assert res_ref["version"] == ver1

def test_evidence_refresh_with_change():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "file1.txt"), "content v1")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid_old = res_imp["id"]
        
        # Modify file
        _write_file(os.path.join(source_dir, "file1.txt"), "content v2")
        
        req_ref = {"op": "evidence.refresh", "project_id": project_id, "evidence_id": eid_old}
        res_ref = handle(data_dir, req_ref)
        
        assert res_ref["id"] != eid_old
        assert res_ref["version"] > res_imp["version"]
        
        # Check old record is superseded
        req_get_old = {"op": "evidence.get", "project_id": project_id, "evidence_id": eid_old}
        res_get_old = handle(data_dir, req_get_old)
        assert res_get_old["status"] == "SUPERSEDED"

def test_evidence_get_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        req = {"op": "evidence.get", "project_id": project_id, "evidence_id": "bad-id"}
        with pytest.raises(ValueError):
            handle(data_dir, req)

def test_evidence_list_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        req = {"op": "evidence.list", "project_id": project_id}
        res = handle(data_dir, req)
        assert res["items"] == []

def test_signal_create_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": project_id, "evidence_id": eid, "text": "my signal"}
        res_sig = handle(data_dir, req_sig)
        
        assert "id" in res_sig
        assert res_sig["project_id"] == project_id
        assert res_sig["evidence_id"] == eid
        assert res_sig["text"] == "my signal"
        assert res_sig["status"] == "OPEN"

def test_signal_create_blank_text():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": project_id, "evidence_id": eid, "text": "   "}
        with pytest.raises(ValueError):
            handle(data_dir, req_sig)

def test_signal_create_foreign_evidence():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        p1 = "proj1"
        p2 = "proj2"
        _ensure_project(data_dir, p1)
        _ensure_project(data_dir, p2)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": p1, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid_p1 = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": p2, "evidence_id": eid_p1, "text": "cross project"}
        with pytest.raises(ValueError):
            handle(data_dir, req_sig)

def test_signal_reject_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": project_id, "evidence_id": eid, "text": "sig"}
        res_sig = handle(data_dir, req_sig)
        sid = res_sig["id"]
        
        req_rej = {"op": "signal.reject", "project_id": project_id, "signal_id": sid, "reason": "invalid"}
        res_rej = handle(data_dir, req_rej)
        
        assert res_rej["status"] == "REJECTED"
        assert res_rej["reason"] == "invalid"

def test_signal_reject_blank_reason():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": project_id, "evidence_id": eid, "text": "sig"}
        res_sig = handle(data_dir, req_sig)
        sid = res_sig["id"]
        
        req_rej = {"op": "signal.reject", "project_id": project_id, "signal_id": sid, "reason": ""}
        with pytest.raises(ValueError):
            handle(data_dir, req_rej)

def test_signal_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        source_dir = os.path.join(tmpdir, "source")
        os.makedirs(source_dir)
        _write_file(os.path.join(source_dir, "f.txt"), "data")
        
        req_imp = {"op": "evidence.import", "project_id": project_id, "path": source_dir}
        res_imp = handle(data_dir, req_imp)
        eid = res_imp["id"]
        
        req_sig = {"op": "signal.create", "project_id": project_id, "evidence_id": eid, "text": "sig1"}
        handle(data_dir, req_sig)
        
        req_list = {"op": "signal.list", "project_id": project_id}
        res_list = handle(data_dir, req_list)
        
        assert len(res_list["items"]) == 1
        assert res_list["items"][0]["text"] == "sig1"

def test_unsupported_op():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = tmpdir
        project_id = "proj1"
        _ensure_project(data_dir, project_id)
        
        req = {"op": "unknown.op", "project_id": project_id}
        with pytest.raises(ValueError):
            handle(data_dir, req)
