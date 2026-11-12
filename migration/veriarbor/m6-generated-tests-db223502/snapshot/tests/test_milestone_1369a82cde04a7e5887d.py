import os
import json
import tempfile
import pytest
from milestones.milestone_1369a82cde04a7e5887d.api import handle

def _setup_data_dir(tmp_path):
    """Helper to create a temporary data directory with initial evidence."""
    data_dir = str(tmp_path)
    
    # Create evidence.json with some sample evidence
    evidence = [
        {
            "id": "ev-1",
            "project_id": "proj-A",
            "status": "CURRENT",
            "files": [
                {"text": "The sky is blue."}
            ]
        },
        {
            "id": "ev-2",
            "project_id": "proj-A",
            "status": "SUPERSEDED",
            "files": [
                {"text": "The grass is green."}
            ]
        },
        {
            "id": "ev-3",
            "project_id": "proj-B",
            "status": "CURRENT",
            "files": [
                {"text": "Water is wet."}
            ]
        }
    ]
    
    with open(os.path.join(data_dir, "evidence.json"), 'w') as f:
        json.dump(evidence, f)
        
    return data_dir

def test_claim_create_supported():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The sky is blue.",
            "evidence_ids": ["ev-1"]
        }
        
        result = handle(data_dir, request)
        
        assert result["project_id"] == "proj-A"
        assert result["text"] == "The sky is blue."
        assert result["evidence_ids"] == ["ev-1"]
        assert result["status"] == "SUPPORTED"
        assert "id" in result

def test_claim_create_unsupported_no_evidence():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "Fire is hot.",
            "evidence_ids": []
        }
        
        result = handle(data_dir, request)
        assert result["status"] == "UNSUPPORTED"

def test_claim_create_unsupported_text_mismatch():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The moon is made of cheese.",
            "evidence_ids": ["ev-1"]
        }
        
        result = handle(data_dir, request)
        assert result["status"] == "UNSUPPORTED"

def test_claim_create_stale_all_superseded():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The grass is green.",
            "evidence_ids": ["ev-2"]
        }
        
        result = handle(data_dir, request)
        assert result["status"] == "STALE"

def test_claim_create_invalid_evidence_missing():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "Test",
            "evidence_ids": ["non-existent-id"]
        }
        
        with pytest.raises(ValueError):
            handle(data_dir, request)

def test_claim_create_cross_project_evidence():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "Water is wet.",
            "evidence_ids": ["ev-3"] # ev-3 belongs to proj-B
        }
        
        with pytest.raises(ValueError):
            handle(data_dir, request)

def test_claim_get_recomputes_status():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        # Create a claim that is initially SUPPORTED
        create_req = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The sky is blue.",
            "evidence_ids": ["ev-1"]
        }
        created = handle(data_dir, create_req)
        claim_id = created["id"]
        
        # Verify it's supported
        get_req = {
            "op": "claim.get",
            "project_id": "proj-A",
            "claim_id": claim_id
        }
        fetched = handle(data_dir, get_req)
        assert fetched["status"] == "SUPPORTED"
        
        # Manually update evidence.json to make ev-1 SUPERSEDED
        ev_path = os.path.join(data_dir, "evidence.json")
        with open(ev_path, 'r') as f:
            evidence = json.load(f)
        
        for item in evidence:
            if item["id"] == "ev-1":
                item["status"] = "SUPERSEDED"
                break
                
        with open(ev_path, 'w') as f:
            json.dump(evidence, f)
            
        # Get again - should now be STALE because all cited evidence (just ev-1) is superseded
        fetched_again = handle(data_dir, get_req)
        assert fetched_again["status"] == "STALE"

def test_claim_list():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        # Create two claims in proj-A
        req1 = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The sky is blue.",
            "evidence_ids": ["ev-1"]
        }
        handle(data_dir, req1)
        
        req2 = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "Random text.",
            "evidence_ids": []
        }
        handle(data_dir, req2)
        
        # List claims for proj-A
        list_req = {
            "op": "claim.list",
            "project_id": "proj-A"
        }
        result = handle(data_dir, list_req)
        
        assert len(result["items"]) == 2
        statuses = [item["status"] for item in result["items"]]
        assert "SUPPORTED" in statuses
        assert "UNSUPPORTED" in statuses

def test_claim_conflict():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        # Create a claim
        create_req = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "The sky is blue.",
            "evidence_ids": ["ev-1"]
        }
        created = handle(data_dir, create_req)
        claim_id = created["id"]
        
        # Mark as conflict
        conflict_req = {
            "op": "claim.conflict",
            "project_id": "proj-A",
            "claim_id": claim_id,
            "reason": "Disputed by expert"
        }
        result = handle(data_dir, conflict_req)
        
        assert result["status"] == "CONFLICT"
        
        # Verify persistence via get
        get_req = {
            "op": "claim.get",
            "project_id": "proj-A",
            "claim_id": claim_id
        }
        fetched = handle(data_dir, get_req)
        assert fetched["status"] == "CONFLICT"

def test_claim_conflict_invalid_reason():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        create_req = {
            "op": "claim.create",
            "project_id": "proj-A",
            "text": "Test",
            "evidence_ids": []
        }
        created = handle(data_dir, create_req)
        claim_id = created["id"]
        
        conflict_req = {
            "op": "claim.conflict",
            "project_id": "proj-A",
            "claim_id": claim_id,
            "reason": "   " # Blank reason
        }
        
        with pytest.raises(ValueError):
            handle(data_dir, conflict_req)

def test_unknown_operation():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "op": "unknown.op",
            "project_id": "proj-A"
        }
        
        with pytest.raises(ValueError):
            handle(data_dir, request)

def test_missing_op():
    with tempfile.TemporaryDirectory() as tmp_path:
        data_dir = _setup_data_dir(tmp_path)
        
        request = {
            "project_id": "proj-A"
        }
        
        with pytest.raises(ValueError):
            handle(data_dir, request)