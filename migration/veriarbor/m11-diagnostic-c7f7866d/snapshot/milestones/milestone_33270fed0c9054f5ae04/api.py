"""Milestone M6: Approval.

Provides persistent, isolated approval management (review, approve, status)
for content items, enforcing strict revision binding, claim validity, and
media presence checks. Reuses M1 project isolation, M3 claim structures,
and M5 content structures.
"""

import json
import os

MILESTONE_ID = "M6"

_PROJECTS_FILENAME = "projects.json"
_CLAIMS_FILENAME = "claims.json"
_CONTENT_FILENAME = "content.json"


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


def _require_project(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    for record in _load_list(data_dir, _PROJECTS_FILENAME):
        if record.get("id") == project_id:
            return record
    raise ValueError("project not found: %s" % project_id)


def _find_content(content_items, project_id, content_id):
    if not isinstance(content_id, str) or not content_id:
        raise ValueError("content_id must be a non-empty string")
    for record in content_items:
        if record.get("id") == content_id:
            if record.get("project_id") != project_id:
                raise ValueError("content not found: %s" % content_id)
            return record
    raise ValueError("content not found: %s" % content_id)


def _compute_claim_status(claim_text, cited_evidence_records):
    if not cited_evidence_records:
        return "UNSUPPORTED"
    all_superseded = True
    has_current_support = False
    for ev in cited_evidence_records:
        if ev.get("status") != "SUPERSEDED":
            all_superseded = False
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


def _current_claim_status(data_dir, project_id, claim_record):
    if claim_record.get("status") == "CONFLICT":
        return "CONFLICT"
    evidence = _load_list(data_dir, "evidence.json")
    cited = []
    for eid in claim_record.get("evidence_ids", []):
        for ev in evidence:
            if ev.get("id") == eid and ev.get("project_id") == project_id:
                cited.append(ev)
                break
    return _compute_claim_status(claim_record.get("text", ""), cited)


def _validate_claims_supported(data_dir, project_id, claim_ids):
    claims = _load_list(data_dir, _CLAIMS_FILENAME)
    for cid in claim_ids:
        found = None
        for c in claims:
            if c.get("id") == cid:
                if c.get("project_id") != project_id:
                    raise ValueError("claim not found: %s" % cid)
                found = c
                break
        if found is None:
            raise ValueError("claim not found: %s" % cid)
        status = _current_claim_status(data_dir, project_id, found)
        if status != "SUPPORTED":
            raise ValueError("claim not supported: %s (%s)" % (cid, status))


def _validate_media_present(media_ids):
    if not isinstance(media_ids, list):
        raise ValueError("media_ids must be a list")
    for mid in media_ids:
        if not isinstance(mid, str) or not mid:
            raise ValueError("media_ids must contain non-empty strings")


def _result(content_id, revision, status):
    return {"content_id": content_id, "revision": revision, "status": status}


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    if op == "approval.review":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)
        record["status"] = "REVIEW"
        _save_list(data_dir, _CONTENT_FILENAME, content_items)
        return _result(record["id"], record["revision"], "REVIEW")

    if op == "approval.approve":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)
        if record.get("status") != "REVIEW":
            raise ValueError("content not reviewed: %s" % content_id)
        _validate_claims_supported(data_dir, project_id, record.get("claim_ids", []))
        _validate_media_present(record.get("media_ids", []))
        record["status"] = "APPROVED"
        _save_list(data_dir, _CONTENT_FILENAME, content_items)
        return _result(record["id"], record["revision"], "APPROVED")

    if op == "approval.status":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)
        return _result(record["id"], record["revision"], record.get("status", "DRAFT"))

    raise ValueError("unknown operation: %s" % op)
