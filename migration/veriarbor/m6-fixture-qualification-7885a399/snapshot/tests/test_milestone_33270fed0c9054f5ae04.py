"""Independent test suite for Milestone M6: Approval.

Exercises the declared public contract for approval.review, approval.approve,
approval.status, validation rules, revision binding, claim validity checks,
media presence checks, project isolation, persistence, and error handling.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest


_API_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "milestones",
    "milestone_33270fed0c9054f5ae04",
    "api.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "milestone_33270fed0c9054f5ae04_api", _API_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = _load_module()
handle = api.handle


# ---------------------------------------------------------------------------
# Helpers to build prerequisite state (projects, campaigns, evidence, claims,
# content) directly in the data_dir using the same JSON file conventions that
# the verified M1-M5 modules use.
# ---------------------------------------------------------------------------


def _write_json(data_dir, filename, items):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, filename), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


def _read_json(data_dir, filename):
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    return json.loads(content)


def _make_project(data_dir, project_id="proj1", name="Project One"):
    projects = _read_json(data_dir, "projects.json")
    projects.append({"id": project_id, "name": name})
    _write_json(data_dir, "projects.json", projects)
    return project_id


def _make_campaign(data_dir, project_id, campaign_id="camp1", channels=None):
    if channels is None:
        channels = ["email"]
    campaigns = _read_json(data_dir, "campaigns.json")
    campaigns.append(
        {
            "id": campaign_id,
            "project_id": project_id,
            "name": "Campaign",
            "audience": "audience",
            "channels": channels,
            "status": "ACTIVE",
            "history": [],
        }
    )
    _write_json(data_dir, "campaigns.json", campaigns)
    return campaign_id


def _make_evidence(data_dir, project_id, evidence_id, text, status="CURRENT"):
    evidence = _read_json(data_dir, "evidence.json")
    evidence.append(
        {
            "id": evidence_id,
            "project_id": project_id,
            "source_path": "/tmp/src",
            "version": 1,
            "sha256": "deadbeef",
            "status": status,
            "files": [{"path": "a.txt", "sha256": "abc", "text": text}],
        }
    )
    _write_json(data_dir, "evidence.json", evidence)
    return evidence_id


def _make_claim(data_dir, project_id, claim_id, text, evidence_ids, status):
    claims = _read_json(data_dir, "claims.json")
    claims.append(
        {
            "id": claim_id,
            "project_id": project_id,
            "text": text,
            "evidence_ids": evidence_ids,
            "status": status,
        }
    )
    _write_json(data_dir, "claims.json", claims)
    return claim_id


def _make_content(
    data_dir,
    project_id,
    content_id="content1",
    campaign_id="camp1",
    channel="email",
    text="hello world",
    claim_ids=None,
    media_ids=None,
    revision=1,
    status="DRAFT",
):
    if claim_ids is None:
        claim_ids = []
    if media_ids is None:
        media_ids = []
    content_items = _read_json(data_dir, "content.json")
    revision_record = {
        "id": content_id,
        "project_id": project_id,
        "campaign_id": campaign_id,
        "channel": channel,
        "text": text,
        "claim_ids": list(claim_ids),
        "media_ids": list(media_ids),
        "revision": revision,
        "status": status,
    }
    record = dict(revision_record)
    record["revisions"] = [revision_record]
    content_items.append(record)
    _write_json(data_dir, "content.json", content_items)
    return content_id


def _setup_basic(tmp_path, claim_status="SUPPORTED", media_ids=None):
    data_dir = str(tmp_path)
    project_id = _make_project(data_dir)
    _make_campaign(data_dir, project_id)
    claim_ids = []
    if claim_status is not None:
        _make_evidence(data_dir, project_id, "ev1", "unrelated evidence" if claim_status == "UNSUPPORTED" else "hello world", status="SUPERSEDED" if claim_status == "STALE" else "CURRENT")
        _make_claim(
            data_dir, project_id, "claim1", "hello world", ["ev1"], claim_status
        )
        claim_ids = ["claim1"]
    content_id = _make_content(
        data_dir, project_id, claim_ids=claim_ids, media_ids=media_ids
    )
    return data_dir, project_id, content_id


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exposes_handle_and_milestone_id():
    assert callable(handle)
    assert getattr(api, "MILESTONE_ID", None) == "M6"


# ---------------------------------------------------------------------------
# approval.review
# ---------------------------------------------------------------------------


def test_review_transitions_draft_to_review(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    result = handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    assert result["content_id"] == content_id
    assert result["status"] == "REVIEW"
    assert result["revision"] == 1

    status = handle(
        data_dir,
        {"op": "approval.status", "project_id": project_id, "content_id": content_id},
    )
    assert status["status"] == "REVIEW"
    assert status["content_id"] == content_id
    assert status["revision"] == 1


# ---------------------------------------------------------------------------
# approval.status
# ---------------------------------------------------------------------------


def test_status_reports_draft_initially(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    status = handle(
        data_dir,
        {"op": "approval.status", "project_id": project_id, "content_id": content_id},
    )
    assert status["content_id"] == content_id
    assert status["status"] == "DRAFT"
    assert status["revision"] == 1


# ---------------------------------------------------------------------------
# approval.approve happy path
# ---------------------------------------------------------------------------


def test_approve_after_review_with_supported_claims(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    result = handle(
        data_dir,
        {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
    )
    assert result["content_id"] == content_id
    assert result["status"] == "APPROVED"
    assert result["revision"] == 1

    status = handle(
        data_dir,
        {"op": "approval.status", "project_id": project_id, "content_id": content_id},
    )
    assert status["status"] == "APPROVED"


def test_approve_with_no_claims_and_no_media(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path, claim_status=None)
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    result = handle(
        data_dir,
        {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
    )
    assert result["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# approval.approve failure: not reviewed
# ---------------------------------------------------------------------------


def test_approve_without_review_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
        )


# ---------------------------------------------------------------------------
# approval.approve failure: claim validity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("claim_status", ["UNSUPPORTED", "STALE", "CONFLICT"])
def test_approve_with_invalid_claim_raises(tmp_path, claim_status):
    data_dir, project_id, content_id = _setup_basic(tmp_path, claim_status=claim_status)
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
        )


# ---------------------------------------------------------------------------
# approval.approve failure: missing media
# ---------------------------------------------------------------------------


def test_approve_with_missing_media_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(
        tmp_path, media_ids=["media-does-not-exist"]
    )
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
        )


# ---------------------------------------------------------------------------
# Revision binding: content.edit resets approval to DRAFT
# ---------------------------------------------------------------------------


def test_edit_resets_approval_to_draft(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    handle(
        data_dir,
        {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
    )

    # Simulate M5 content.edit producing a new revision (revision 2, DRAFT).
    content_items = _read_json(data_dir, "content.json")
    for record in content_items:
        if record["id"] == content_id:
            new_rev = dict(record)
            new_rev.pop("revisions", None)
            new_rev["revision"] = 2
            new_rev["status"] = "DRAFT"
            new_rev["text"] = "hello world edited"
            record["revision"] = 2
            record["status"] = "DRAFT"
            record["text"] = "hello world edited"
            record.setdefault("revisions", []).append(new_rev)
    _write_json(data_dir, "content.json", content_items)

    status = handle(
        data_dir,
        {"op": "approval.status", "project_id": project_id, "content_id": content_id},
    )
    assert status["status"] == "DRAFT"
    assert status["revision"] == 2

    # New revision must not be approvable without a fresh review.
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
        )


# ---------------------------------------------------------------------------
# Project isolation
# ---------------------------------------------------------------------------


def test_cross_project_access_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    other_project = _make_project(data_dir, project_id="proj2", name="Project Two")

    for op in ("approval.review", "approval.approve", "approval.status"):
        with pytest.raises(ValueError):
            handle(
                data_dir,
                {"op": op, "project_id": other_project, "content_id": content_id},
            )


# ---------------------------------------------------------------------------
# Persistence across processes
# ---------------------------------------------------------------------------


def test_approval_persists_across_processes(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    handle(
        data_dir,
        {"op": "approval.review", "project_id": project_id, "content_id": content_id},
    )
    handle(
        data_dir,
        {"op": "approval.approve", "project_id": project_id, "content_id": content_id},
    )

    script = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "res = m.handle(sys.argv[2], {'op': 'approval.status', "
        "'project_id': sys.argv[3], 'content_id': sys.argv[4]})\n"
        "print(json.dumps(res))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, _API_PATH, data_dir, project_id, content_id],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["status"] == "APPROVED"
    assert result["content_id"] == content_id


# ---------------------------------------------------------------------------
# Invalid inputs / unknown IDs / unsupported ops
# ---------------------------------------------------------------------------


def test_invalid_data_dir_raises():
    with pytest.raises(ValueError):
        handle("", {"op": "approval.status", "project_id": "p", "content_id": "c"})


def test_non_dict_request_raises(tmp_path):
    with pytest.raises(ValueError):
        handle(str(tmp_path), "not-a-dict")


def test_missing_op_raises(tmp_path):
    with pytest.raises(ValueError):
        handle(str(tmp_path), {"project_id": "p", "content_id": "c"})


def test_unknown_op_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.bogus", "project_id": project_id, "content_id": content_id},
        )


def test_unknown_project_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.status", "project_id": "nope", "content_id": content_id},
        )


def test_unknown_content_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(
            data_dir,
            {"op": "approval.status", "project_id": project_id, "content_id": "nope"},
        )


def test_missing_content_id_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(data_dir, {"op": "approval.status", "project_id": project_id})


def test_missing_project_id_raises(tmp_path):
    data_dir, project_id, content_id = _setup_basic(tmp_path)
    with pytest.raises(ValueError):
        handle(data_dir, {"op": "approval.status", "content_id": content_id})
