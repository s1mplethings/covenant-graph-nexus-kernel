"""Milestone M9: Receipt Queries.

Read-only query operations over the authoritative M7 publication receipts
(receipts.json written by promotion_publish). Never creates a second
conflicting receipt database; all reads go through the M7 store.

Operations: receipt.list, receipt.get, receipt.export.
"""

import json
import os
from datetime import datetime, timezone

MILESTONE_ID = "M9"

_PROJECTS_FILENAME = "projects.json"
_RECEIPTS_FILENAME = "receipts.json"


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


def _require_project(data_dir, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    for record in _load_list(data_dir, _PROJECTS_FILENAME):
        if record.get("id") == project_id:
            return record
    raise ValueError("project not found: %s" % project_id)


def _public_receipt(record):
    """Return the authoritative M7 receipt fields exactly as recorded."""
    return {
        "id": record.get("id"),
        "project_id": record.get("project_id"),
        "content_id": record.get("content_id"),
        "revision": record.get("revision"),
        "channel": record.get("channel"),
        "text": record.get("text"),
        "status": record.get("status"),
        "remote_id": record.get("remote_id"),
        "idempotency_key": record.get("idempotency_key"),
        "request_ref": record.get("request_ref"),
        "response_ref": record.get("response_ref"),
        "attempts": list(record.get("attempts", [])),
        "url": record.get("url"),
    }


def _project_receipts(data_dir, project_id):
    receipts = _load_list(data_dir, _RECEIPTS_FILENAME)
    return [r for r in receipts if r.get("project_id") == project_id]


def _validate_filter(value, name):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty string" % name)
    return value


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    if op == "receipt.list":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        channel = _validate_filter(request.get("channel"), "channel")
        status = _validate_filter(request.get("status"), "status")

        items = []
        for record in _project_receipts(data_dir, project_id):
            if channel is not None and record.get("channel") != channel:
                continue
            if status is not None and record.get("status") != status:
                continue
            items.append(_public_receipt(record))
        return {"items": items}

    if op == "receipt.get":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        receipt_id = request.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("receipt_id must be a non-empty string")

        for record in _load_list(data_dir, _RECEIPTS_FILENAME):
            if record.get("id") == receipt_id:
                if record.get("project_id") != project_id:
                    raise ValueError("receipt not found: %s" % receipt_id)
                return _public_receipt(record)
        raise ValueError("receipt not found: %s" % receipt_id)

    if op == "receipt.export":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        receipts = [_public_receipt(r) for r in _project_receipts(data_dir, project_id)]
        exported_at = datetime.now(timezone.utc).isoformat()
        return {"receipts": receipts, "exported_at": exported_at}

    raise ValueError("unknown operation: %s" % op)
