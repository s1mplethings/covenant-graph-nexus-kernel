"""Tests for Milestone M5: Content Studio.

Exercises the declared public contract for content.create, content.get,
content.revisions, content.edit, content.compare, and content.list,
including validation, isolation, persistence, and error handling.
"""

import importlib.util
import os
import subprocess
import sys

import pytest


_API_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "milestones",
    "milestone_9165a990eed5b9c8801e",
    "api.py",
)


def _load_api():
    spec = importlib.util.spec_from_file_location("m5_api", _API_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = _load_api()


def _make_project(data_dir, name="Proj"):
    return api.handle(data_dir, {"op": "project.create", "name": name})


def _make_campaign(data_dir, project_id, channels=None, name="Camp", audience="Aud"):
    if channels is None:
        channels = ["email", "web"]
    return api.handle(
        data_dir,
        {
            "op": "campaign.create",
            "project_id": project_id,
            "name": name,
            "audience": audience,
            "channels": channels,
        },
    )


def _make_claim(data_dir, project_id, text="claim text"):
    return api.handle(
        data_dir,
        {"op": "claim.create", "project_id": project_id, "text": text, "evidence_ids": []},
    )


def _create_content(data_dir, project_id, campaign_id, channel="email", text="hello", claim_ids=None, media_ids=None):
    req = {
        "op": "content.create",
        "project_id": project_id,
        "campaign_id": campaign_id,
        "channel": channel,
        "text": text,
    }
    if claim_ids is not None:
        req["claim_ids"] = claim_ids
    if media_ids is not None:
        req["media_ids"] = media_ids
    return api.handle(data_dir, req)


def test_milestone_id():
    assert api.MILESTONE_ID == "M5"


def test_create_success(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    claim = _make_claim(data_dir, project["id"])

    result = _create_content(
        data_dir,
        project["id"],
        campaign["id"],
        channel="email",
        text="Hello world",
        claim_ids=[claim["id"]],
        media_ids=["m1"],
    )

    assert result["id"]
    assert result["project_id"] == project["id"]
    assert result["campaign_id"] == campaign["id"]
    assert result["channel"] == "email"
    assert result["text"] == "Hello world"
    assert result["claim_ids"] == [claim["id"]]
    assert result["media_ids"] == ["m1"]
    assert result["revision"] == 1
    assert result["status"] == "DRAFT"


def test_create_defaults_empty_lists(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    result = _create_content(data_dir, project["id"], campaign["id"])
    assert result["claim_ids"] == []
    assert result["media_ids"] == []


def test_create_missing_project(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    with pytest.raises(ValueError):
        _create_content(data_dir, "nonexistent", campaign["id"])


def test_create_missing_campaign(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        _create_content(data_dir, project["id"], "nonexistent")


def test_create_campaign_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p2["id"])
    with pytest.raises(ValueError):
        _create_content(data_dir, p1["id"], campaign["id"])


def test_create_inactive_campaign(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    api.handle(
        data_dir,
        {"op": "campaign.archive", "project_id": project["id"], "campaign_id": campaign["id"]},
    )
    with pytest.raises(ValueError):
        _create_content(data_dir, project["id"], campaign["id"])


def test_create_unpermitted_channel(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"], channels=["email"])
    with pytest.raises(ValueError):
        _create_content(data_dir, project["id"], campaign["id"], channel="web")


def test_create_blank_text(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    with pytest.raises(ValueError):
        _create_content(data_dir, project["id"], campaign["id"], text="   ")


def test_create_missing_claim(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    with pytest.raises(ValueError):
        _create_content(data_dir, project["id"], campaign["id"], claim_ids=["nope"])


def test_create_claim_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p1["id"])
    claim = _make_claim(data_dir, p2["id"])
    with pytest.raises(ValueError):
        _create_content(data_dir, p1["id"], campaign["id"], claim_ids=[claim["id"]])


def test_get_success(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"], text="abc")
    got = api.handle(
        data_dir,
        {"op": "content.get", "project_id": project["id"], "content_id": created["id"]},
    )
    assert got["id"] == created["id"]
    assert got["text"] == "abc"
    assert got["revision"] == 1


def test_get_missing(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.get", "project_id": project["id"], "content_id": "nope"},
        )


def test_get_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p1["id"])
    created = _create_content(data_dir, p1["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.get", "project_id": p2["id"], "content_id": created["id"]},
        )


def test_revisions_success(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"], text="v1")
    result = api.handle(
        data_dir,
        {"op": "content.revisions", "project_id": project["id"], "content_id": created["id"]},
    )
    assert "items" in result
    assert len(result["items"]) == 1
    assert result["items"][0]["revision"] == 1
    assert result["items"][0]["text"] == "v1"


def test_revisions_missing(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.revisions", "project_id": project["id"], "content_id": "nope"},
        )


def test_revisions_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p1["id"])
    created = _create_content(data_dir, p1["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.revisions", "project_id": p2["id"], "content_id": created["id"]},
        )


def test_edit_creates_revision(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"], text="v1")

    edited = api.handle(
        data_dir,
        {
            "op": "content.edit",
            "project_id": project["id"],
            "content_id": created["id"],
            "text": "v2",
        },
    )
    assert edited["id"] == created["id"]
    assert edited["text"] == "v2"
    assert edited["revision"] == 2
    assert edited["status"] == "DRAFT"

    revs = api.handle(
        data_dir,
        {"op": "content.revisions", "project_id": project["id"], "content_id": created["id"]},
    )
    assert len(revs["items"]) == 2
    assert revs["items"][0]["text"] == "v1"
    assert revs["items"][1]["text"] == "v2"


def test_edit_updates_claims(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    c1 = _make_claim(data_dir, project["id"], "c1")
    c2 = _make_claim(data_dir, project["id"], "c2")
    created = _create_content(data_dir, project["id"], campaign["id"], claim_ids=[c1["id"]])
    edited = api.handle(
        data_dir,
        {
            "op": "content.edit",
            "project_id": project["id"],
            "content_id": created["id"],
            "text": "new",
            "claim_ids": [c2["id"]],
        },
    )
    assert edited["claim_ids"] == [c2["id"]]


def test_edit_missing(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.edit", "project_id": project["id"], "content_id": "nope", "text": "x"},
        )


def test_edit_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p1["id"])
    created = _create_content(data_dir, p1["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.edit", "project_id": p2["id"], "content_id": created["id"], "text": "x"},
        )


def test_edit_blank_text(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {"op": "content.edit", "project_id": project["id"], "content_id": created["id"], "text": "  "},
        )


def test_edit_invalid_claim(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {
                "op": "content.edit",
                "project_id": project["id"],
                "content_id": created["id"],
                "text": "x",
                "claim_ids": ["nope"],
            },
        )


def test_compare_success(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"], text="v1")
    api.handle(
        data_dir,
        {"op": "content.edit", "project_id": project["id"], "content_id": created["id"], "text": "v2"},
    )
    result = api.handle(
        data_dir,
        {
            "op": "content.compare",
            "project_id": project["id"],
            "content_id": created["id"],
            "from_revision": 1,
            "to_revision": 2,
        },
    )
    assert result["before"]["revision"] == 1
    assert result["before"]["text"] == "v1"
    assert result["after"]["revision"] == 2
    assert result["after"]["text"] == "v2"


def test_compare_missing_content(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {
                "op": "content.compare",
                "project_id": project["id"],
                "content_id": "nope",
                "from_revision": 1,
                "to_revision": 2,
            },
        )


def test_compare_other_project(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    campaign = _make_campaign(data_dir, p1["id"])
    created = _create_content(data_dir, p1["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {
                "op": "content.compare",
                "project_id": p2["id"],
                "content_id": created["id"],
                "from_revision": 1,
                "to_revision": 1,
            },
        )


def test_compare_invalid_revision(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"])
    with pytest.raises(ValueError):
        api.handle(
            data_dir,
            {
                "op": "content.compare",
                "project_id": project["id"],
                "content_id": created["id"],
                "from_revision": 1,
                "to_revision": 99,
            },
        )


def test_list_all(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    c1 = _create_content(data_dir, project["id"], campaign["id"], text="a")
    c2 = _create_content(data_dir, project["id"], campaign["id"], text="b")
    result = api.handle(data_dir, {"op": "content.list", "project_id": project["id"]})
    ids = {item["id"] for item in result["items"]}
    assert ids == {c1["id"], c2["id"]}


def test_list_filter_campaign(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    camp1 = _make_campaign(data_dir, project["id"], name="C1")
    camp2 = _make_campaign(data_dir, project["id"], name="C2")
    c1 = _create_content(data_dir, project["id"], camp1["id"], text="a")
    _create_content(data_dir, project["id"], camp2["id"], text="b")
    result = api.handle(
        data_dir,
        {"op": "content.list", "project_id": project["id"], "campaign_id": camp1["id"]},
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == c1["id"]


def test_list_isolation(tmp_path):
    data_dir = str(tmp_path)
    p1 = _make_project(data_dir, "P1")
    p2 = _make_project(data_dir, "P2")
    camp1 = _make_campaign(data_dir, p1["id"])
    _create_content(data_dir, p1["id"], camp1["id"])
    result = api.handle(data_dir, {"op": "content.list", "project_id": p2["id"]})
    assert result["items"] == []


def test_unknown_op(tmp_path):
    data_dir = str(tmp_path)
    with pytest.raises(ValueError):
        api.handle(data_dir, {"op": "content.bogus"})


def test_persistence_across_processes(tmp_path):
    data_dir = str(tmp_path)
    project = _make_project(data_dir)
    campaign = _make_campaign(data_dir, project["id"])
    created = _create_content(data_dir, project["id"], campaign["id"], text="persisted")

    script = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('m5_api', %r)\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "res = m.handle(%r, {'op': 'content.get', 'project_id': %r, 'content_id': %r})\n"
        "print(res['text'])\n"
    ) % (_API_PATH, data_dir, project["id"], created["id"])

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "persisted"
