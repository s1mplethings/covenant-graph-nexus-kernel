"""Content Studio module (M5).

Provides persistent, isolated content management with revision history,
validation against project/campaign/claim constraints, and support for
create, get, list, edit, revisions, and compare operations.
Reuses M1 project isolation, M3 claim structures, and M4 campaign structures.
"""

import json
import os
import uuid

MILESTONE_ID = "M5"

_PROJECTS_FILENAME = "projects.json"
_CAMPAIGNS_FILENAME = "campaigns.json"
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


def _find_campaign(data_dir, project_id, campaign_id):
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("campaign_id must be a non-empty string")
    for record in _load_list(data_dir, _CAMPAIGNS_FILENAME):
        if record.get("id") == campaign_id:
            if record.get("project_id") != project_id:
                raise ValueError("campaign not found: %s" % campaign_id)
            return record
    raise ValueError("campaign not found: %s" % campaign_id)


def _validate_claim_ids(data_dir, project_id, claim_ids):
    if not isinstance(claim_ids, list):
        raise ValueError("claim_ids must be a list")
    claims = _load_list(data_dir, _CLAIMS_FILENAME)
    for cid in claim_ids:
        if not isinstance(cid, str) or not cid:
            raise ValueError("claim_ids must contain non-empty strings")
        found = False
        for c in claims:
            if c.get("id") == cid:
                if c.get("project_id") != project_id:
                    raise ValueError("claim not found: %s" % cid)
                found = True
                break
        if not found:
            raise ValueError("claim not found: %s" % cid)


def _validate_media_ids(media_ids):
    if not isinstance(media_ids, list):
        raise ValueError("media_ids must be a list")
    for mid in media_ids:
        if not isinstance(mid, str) or not mid:
            raise ValueError("media_ids must contain non-empty strings")


def _validate_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")


def _validate_channel(campaign, channel):
    if not isinstance(channel, str) or not channel:
        raise ValueError("channel must be a non-empty string")
    if channel not in campaign.get("channels", []):
        raise ValueError("channel not permitted: %s" % channel)


def _find_content(content_items, project_id, content_id):
    if not isinstance(content_id, str) or not content_id:
        raise ValueError("content_id must be a non-empty string")
    for record in content_items:
        if record.get("id") == content_id:
            if record.get("project_id") != project_id:
                raise ValueError("content not found: %s" % content_id)
            return record
    raise ValueError("content not found: %s" % content_id)


def _public_content(record):
    return {
        "id": record["id"],
        "project_id": record["project_id"],
        "campaign_id": record["campaign_id"],
        "channel": record["channel"],
        "text": record["text"],
        "claim_ids": list(record["claim_ids"]),
        "media_ids": list(record["media_ids"]),
        "revision": record["revision"],
        "status": record["status"],
    }


def _public_revision(rev):
    return {
        "id": rev["id"],
        "project_id": rev["project_id"],
        "campaign_id": rev["campaign_id"],
        "channel": rev["channel"],
        "text": rev["text"],
        "claim_ids": list(rev["claim_ids"]),
        "media_ids": list(rev["media_ids"]),
        "revision": rev["revision"],
        "status": rev["status"],
    }


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    if op == "content.create":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)

        campaign_id = request.get("campaign_id")
        campaign = _find_campaign(data_dir, project_id, campaign_id)
        if campaign.get("status") != "ACTIVE":
            raise ValueError("campaign is not active: %s" % campaign_id)

        channel = request.get("channel")
        _validate_channel(campaign, channel)

        text = request.get("text")
        _validate_text(text)

        claim_ids = request.get("claim_ids")
        if claim_ids is None:
            claim_ids = []
        _validate_claim_ids(data_dir, project_id, claim_ids)

        media_ids = request.get("media_ids")
        if media_ids is None:
            media_ids = []
        _validate_media_ids(media_ids)

        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        content_id = uuid.uuid4().hex
        revision_record = {
            "id": content_id,
            "project_id": project_id,
            "campaign_id": campaign_id,
            "channel": channel,
            "text": text,
            "claim_ids": list(claim_ids),
            "media_ids": list(media_ids),
            "revision": 1,
            "status": "DRAFT",
        }
        record = {
            "id": content_id,
            "project_id": project_id,
            "campaign_id": campaign_id,
            "channel": channel,
            "text": text,
            "claim_ids": list(claim_ids),
            "media_ids": list(media_ids),
            "revision": 1,
            "status": "DRAFT",
            "revisions": [revision_record],
        }
        content_items.append(record)
        _save_list(data_dir, _CONTENT_FILENAME, content_items)
        return _public_content(record)

    if op == "content.get":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)
        return _public_content(record)

    if op == "content.revisions":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)
        items = [_public_revision(r) for r in record.get("revisions", [])]
        return {"items": items}

    if op == "content.edit":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)

        campaign_id = record["campaign_id"]
        campaign = _find_campaign(data_dir, project_id, campaign_id)
        if campaign.get("status") != "ACTIVE":
            raise ValueError("campaign is not active: %s" % campaign_id)

        channel = record["channel"]
        _validate_channel(campaign, channel)

        text = request.get("text")
        _validate_text(text)

        if "claim_ids" in request and request.get("claim_ids") is not None:
            claim_ids = request.get("claim_ids")
            _validate_claim_ids(data_dir, project_id, claim_ids)
        else:
            claim_ids = list(record["claim_ids"])

        if "media_ids" in request and request.get("media_ids") is not None:
            media_ids = request.get("media_ids")
            _validate_media_ids(media_ids)
        else:
            media_ids = list(record["media_ids"])

        new_revision_number = record["revision"] + 1
        revision_record = {
            "id": content_id,
            "project_id": project_id,
            "campaign_id": campaign_id,
            "channel": channel,
            "text": text,
            "claim_ids": list(claim_ids),
            "media_ids": list(media_ids),
            "revision": new_revision_number,
            "status": "DRAFT",
        }

        record["text"] = text
        record["claim_ids"] = list(claim_ids)
        record["media_ids"] = list(media_ids)
        record["revision"] = new_revision_number
        record["status"] = "DRAFT"
        if not isinstance(record.get("revisions"), list):
            record["revisions"] = []
        record["revisions"].append(revision_record)

        _save_list(data_dir, _CONTENT_FILENAME, content_items)
        return _public_content(record)

    if op == "content.compare":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        content_id = request.get("content_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        record = _find_content(content_items, project_id, content_id)

        from_revision = request.get("from_revision")
        to_revision = request.get("to_revision")
        if not isinstance(from_revision, int) or isinstance(from_revision, bool):
            raise ValueError("from_revision must be an integer")
        if not isinstance(to_revision, int) or isinstance(to_revision, bool):
            raise ValueError("to_revision must be an integer")

        revisions = record.get("revisions", [])
        before = None
        after = None
        for r in revisions:
            if r.get("revision") == from_revision:
                before = r
            if r.get("revision") == to_revision:
                after = r
        if before is None:
            raise ValueError("revision not found: %s" % from_revision)
        if after is None:
            raise ValueError("revision not found: %s" % to_revision)

        return {"before": _public_revision(before), "after": _public_revision(after)}

    if op == "content.list":
        project_id = request.get("project_id")
        _require_project(data_dir, project_id)
        campaign_id = request.get("campaign_id")
        content_items = _load_list(data_dir, _CONTENT_FILENAME)
        items = []
        for record in content_items:
            if record.get("project_id") != project_id:
                continue
            if campaign_id is not None and record.get("campaign_id") != campaign_id:
                continue
            items.append(_public_content(record))
        return {"items": items}

    raise ValueError("unknown operation: %s" % op)
