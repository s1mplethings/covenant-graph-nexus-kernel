"""Claim Ledger module (M3).

Provides persistent, isolated claim management with deterministic validity computation based on evidence status and content matching.
Reuses M1 project isolation and persistence, and M2 evidence/signal structures.
"""

import json
import os
import uuid

MILESTONE_ID = "M3"

_PROJECTS_FILENAME = "projects.json"
_EVIDENCE_FILENAME = "evidence.json"
_CLAIMS_FILENAME = "claims.json"


def _path(data_dir, filename):
    return os.path.join(data_dir, filename)


def _load_list(data_dir, filename):
    path = _path(data_dir, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    data = json.loads(content)
    if not isinstance(data, list):
        return []
    return data


def _save_list(data_dir, filename, items):
    os.makedirs(data_dir, exist_ok=True)
    path = _path(data_dir, filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def _load_projects(data_dir):
    return _load_list(data_dir, _PROJECTS_FILENAME)


def _require_project(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    for record in _load_projects(data_dir):
        if record.get("id") == project_id:
            return record
    raise ValueError("project not found: %s" % project_id)


def _find_evidence(evidence, project_id, evidence_id):
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError("evidence_id must be a non-empty string")
    for record in evidence:
        if record.get("id") == evidence_id:
            if record.get("project_id") != project_id:
                raise ValueError("evidence not found: %s" % evidence_id)
            return record
    raise ValueError("evidence not found: %s" % evidence_id)


def _compute_status(claim_text, cited_evidence_records):
    """
    Compute status based on spec:
    - SUPPORTED: If the claim text is an exact substring of the current (non-SUPERSEDED) text content of at least one cited evidence file.
    - UNSUPPORTED: If no evidence is cited, or if the claim text is not found in any current cited evidence.
    - STALE: If all cited evidence records are SUPERSEDED.
    - CONFLICT: Only set via explicit conflict operation; create never sets this initially unless logic dictates otherwise.
    """
    if not cited_evidence_records:
        return "UNSUPPORTED"

    # Check if all cited evidence are SUPERSEDED
    all_superseded = True
    has_current_support = False

    for ev in cited_evidence_records:
        if ev["status"] != "SUPERSEDED":
            all_superseded = False
            # Check if claim text is substring of any file in this evidence
            for file_info in ev.get("files", []):
                if claim_text in file_info.get("text", ""):
                    has_current_support = True
                    break
        if has_current_support:
            break

    if all_superseded:
        return "STALE"
    
    if has_current_support:
        return "SUPPORTED"
    
    return "UNSUPPORTED"


def _public_claim(record):
    return {
        "id": record["id"],
        "project_id": record["project_id"],
        "text": record["text"],
        "evidence_ids": record["evidence_ids"],
        "status": record["status"],
        "reason": record.get("reason")
    }


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    if op == "claim.create":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        
        text = request.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
            
        evidence_ids = request.get("evidence_ids")
        if not isinstance(evidence_ids, list):
             raise ValueError("evidence_ids must be a list")
             
        evidence = _load_list(data_dir, _EVIDENCE_FILENAME)
        cited_evidence_records = []
        for eid in evidence_ids:
            rec = _find_evidence(evidence, project_id, eid)
            cited_evidence_records.append(rec)
            
        status = _compute_status(text, cited_evidence_records)
        
        claims = _load_list(data_dir, _CLAIMS_FILENAME)
        record = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "text": text,
            "evidence_ids": evidence_ids,
            "status": status,
        }
        claims.append(record)
        _save_list(data_dir, _CLAIMS_FILENAME, claims)
        return _public_claim(record)

    if op == "claim.get":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        claim_id = request.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("claim_id must be a non-empty string")
            
        claims = _load_list(data_dir, _CLAIMS_FILENAME)
        target_claim = None
        for c in claims:
            if c["id"] == claim_id:
                if c["project_id"] != project_id:
                    raise ValueError("claim not found: %s" % claim_id)
                target_claim = c
                break
        
        if not target_claim:
            raise ValueError("claim not found: %s" % claim_id)
            
        # Recompute status based on latest evidence state
        # Note: Spec says "claim.conflict marks... This overrides the computed status until the claim is potentially re-evaluated or modified"
        # But also "claim.get recomputes the current validity status..."
        # And "CONFLICT: Only set via explicit conflict operation..."
        # Usually, if a claim is explicitly marked CONFLICT, get might keep it CONFLICT or recompute? 
        # The spec says: "claim.conflict marks a specific claim as CONFLICT with a persistent reason. This overrides the computed status until the claim is potentially re-evaluated or modified (though modification isn't supported here, so it stays CONFLICT)."
        # So if status is already CONFLICT, we should probably keep it CONFLICT unless there's a way to clear it? 
        # However, standard interpretation of "recomputes" usually implies checking evidence again. 
        # BUT, the edge behavior says: "CONFLICT: Only set via explicit conflict operation; create never sets this initially..."
        # And: "claim.conflict ... overrides the computed status ... so it stays CONFLICT".
        # This implies that once CONFLICT, it remains CONFLICT even on get, because there is no "clear conflict" operation.
        
        if target_claim["status"] == "CONFLICT":
            return _public_claim(target_claim)
            
        evidence = _load_list(data_dir, _EVIDENCE_FILENAME)
        cited_evidence_records = []
        for eid in target_claim["evidence_ids"]:
            try:
                rec = _find_evidence(evidence, project_id, eid)
                cited_evidence_records.append(rec)
            except ValueError:
                # Evidence deleted? Treat as missing/unsupported?
                # Spec doesn't explicitly say what happens if evidence disappears.
                # Safest is to treat as not supporting the claim.
                pass
                
        new_status = _compute_status(target_claim["text"], cited_evidence_records)
        target_claim["status"] = new_status
        _save_list(data_dir, _CLAIMS_FILENAME, claims)
        
        return _public_claim(target_claim)

    if op == "claim.list":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        claims = _load_list(data_dir, _CLAIMS_FILENAME)
        evidence = _load_list(data_dir, _EVIDENCE_FILENAME)
        
        items = []
        for c in claims:
            if c["project_id"] != project_id:
                continue
                
            # Recompute status for list as well? 
            # Spec: "claim.list returns {items: [...]} containing all claims for the project with their currently computed statuses."
            # Yes, compute status.
            
            if c["status"] == "CONFLICT":
                items.append(_public_claim(c))
                continue
                
            cited_evidence_records = []
            for eid in c["evidence_ids"]:
                try:
                    rec = _find_evidence(evidence, project_id, eid)
                    cited_evidence_records.append(rec)
                except ValueError:
                    pass
                    
            new_status = _compute_status(c["text"], cited_evidence_records)
            c["status"] = new_status
            items.append(_public_claim(c))
            
        _save_list(data_dir, _CLAIMS_FILENAME, claims)
        return {"items": items}

    if op == "claim.conflict":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        claim_id = request.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("claim_id must be a non-empty string")
            
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
            
        claims = _load_list(data_dir, _CLAIMS_FILENAME)
        target_claim = None
        for c in claims:
            if c["id"] == claim_id:
                if c["project_id"] != project_id:
                    raise ValueError("claim not found: %s" % claim_id)
                target_claim = c
                break
                
        if not target_claim:
            raise ValueError("claim not found: %s" % claim_id)
            
        target_claim["status"] = "CONFLICT"
        target_claim["reason"] = reason
        _save_list(data_dir, _CLAIMS_FILENAME, claims)
        
        return _public_claim(target_claim)

    raise ValueError("unknown operation: %s" % op)
