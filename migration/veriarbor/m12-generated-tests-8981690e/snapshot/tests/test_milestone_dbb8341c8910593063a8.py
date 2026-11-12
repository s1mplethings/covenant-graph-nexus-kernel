"""Milestone M11: Media test suite.

Exercises the declared public contract for media.import, media.get, media.list,
validation rules, integrity checks, and integration with M6 approval and M7
publication.
"""

import hashlib
import importlib.util
import json
import os
import sys

import pytest


# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(name, rel_path):
    path = os.path.join(_REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m11 = _load_module("m11_media", os.path.join("milestones", "milestone_dbb8341c8910593063a8", "api.py"))
m1 = _load_module("m1_projects", os.path.join("milestones", "milestone_20f2614f6ae8403d4a4e", "api.py"))
m2 = _load_module("m2_evidence", os.path.join("milestones", "milestone_4e7c26281cf61a85851e", "api.py"))
m3 = _load_module("m3_claims", os.path.join("milestones", "milestone_1369a82cde04a7e5887d", "api.py"))
m4 = _load_module("m4_campaigns", os.path.join("milestones", "milestone_90b8868c7203e2958397", "api.py"))
m5 = _load_module("m5_content", os.path.join("milestones", "milestone_9165a990eed5b9c8801e", "api.py"))
m6 = _load_module("m6_approval", os.path.join("milestones", "milestone_33270fed0c9054f5ae04", "api.py"))
m7 = _load_module("m7_publish", "promotion_publish.py")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


def _make_project(data_dir, name="proj"):
    return m1.handle(data_dir, {"op": "project.create", "name": name})


def _write_file(tmp_path, name, content):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def _import_media(data_dir, project_id, path, kind):
    return m11.handle(data_dir, {
        "op": "media.import",
        "project_id": project_id,
        "path": path,
        "kind": kind,
    })


# ---------------------------------------------------------------------------
# media.import
# ---------------------------------------------------------------------------

def test_import_png_image(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    result = _import_media(data_dir, proj["id"], src, "image")

    assert result["project_id"] == proj["id"]
    assert result["kind"] == "image"
    assert result["status"] == "VALID"
    assert result["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert isinstance(result["id"], str) and result["id"]
    assert isinstance(result["path"], str) and result["path"]


def test_import_jpeg_image(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.jpg", JPEG_BYTES)
    result = _import_media(data_dir, proj["id"], src, "image")
    assert result["status"] == "VALID"
    assert result["sha256"] == hashlib.sha256(JPEG_BYTES).hexdigest()


def test_import_webm_video(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "clip.webm", WEBM_BYTES)
    result = _import_media(data_dir, proj["id"], src, "video")
    assert result["status"] == "VALID"
    assert result["kind"] == "video"


def test_import_mp4_video(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "clip.mp4", MP4_BYTES)
    result = _import_media(data_dir, proj["id"], src, "video")
    assert result["status"] == "VALID"


def test_import_stores_bytes_under_data_dir(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    result = _import_media(data_dir, proj["id"], src, "image")

    stored = os.path.join(data_dir, result["path"])
    assert os.path.exists(stored)
    with open(stored, "rb") as f:
        assert f.read() == PNG_BYTES


def test_import_rejects_empty_file(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "empty.png", b"")
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], src, "image")


def test_import_rejects_signature_mismatch(data_dir, tmp_path):
    proj = _make_project(data_dir)
    # Declared image but bytes are a video signature.
    src = _write_file(tmp_path, "mismatch.png", WEBM_BYTES)
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], src, "image")


def test_import_rejects_unsupported_kind(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], src, "audio")


def test_import_rejects_missing_source(data_dir, tmp_path):
    proj = _make_project(data_dir)
    missing = str(tmp_path / "nope.png")
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], missing, "image")


def test_import_rejects_unknown_project(data_dir, tmp_path):
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    with pytest.raises(ValueError):
        _import_media(data_dir, "does-not-exist", src, "image")


def test_import_rejects_empty_path(data_dir):
    proj = _make_project(data_dir)
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], "", "image")


def test_import_rejects_empty_kind(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    with pytest.raises(ValueError):
        _import_media(data_dir, proj["id"], src, "")


# ---------------------------------------------------------------------------
# media.get
# ---------------------------------------------------------------------------

def test_get_returns_valid_record(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj["id"], src, "image")

    got = m11.handle(data_dir, {
        "op": "media.get",
        "project_id": proj["id"],
        "media_id": imported["id"],
    })
    assert got["id"] == imported["id"]
    assert got["status"] == "VALID"
    assert got["sha256"] == imported["sha256"]


def test_get_marks_broken_when_bytes_modified(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj["id"], src, "image")

    stored = os.path.join(data_dir, imported["path"])
    with open(stored, "wb") as f:
        f.write(PNG_BYTES + b"tampered")

    got = m11.handle(data_dir, {
        "op": "media.get",
        "project_id": proj["id"],
        "media_id": imported["id"],
    })
    assert got["status"] == "BROKEN"


def test_get_marks_broken_when_bytes_missing(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj["id"], src, "image")

    stored = os.path.join(data_dir, imported["path"])
    os.remove(stored)

    got = m11.handle(data_dir, {
        "op": "media.get",
        "project_id": proj["id"],
        "media_id": imported["id"],
    })
    assert got["status"] == "BROKEN"


def test_get_rejects_unknown_media_id(data_dir):
    proj = _make_project(data_dir)
    with pytest.raises(ValueError):
        m11.handle(data_dir, {
            "op": "media.get",
            "project_id": proj["id"],
            "media_id": "missing-id",
        })


def test_get_rejects_empty_media_id(data_dir):
    proj = _make_project(data_dir)
    with pytest.raises(ValueError):
        m11.handle(data_dir, {
            "op": "media.get",
            "project_id": proj["id"],
            "media_id": "",
        })


def test_get_rejects_cross_project_access(data_dir, tmp_path):
    proj_a = _make_project(data_dir, "a")
    proj_b = _make_project(data_dir, "b")
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj_a["id"], src, "image")

    with pytest.raises(ValueError):
        m11.handle(data_dir, {
            "op": "media.get",
            "project_id": proj_b["id"],
            "media_id": imported["id"],
        })


# ---------------------------------------------------------------------------
# media.list
# ---------------------------------------------------------------------------

def test_list_empty(data_dir):
    proj = _make_project(data_dir)
    result = m11.handle(data_dir, {"op": "media.list", "project_id": proj["id"]})
    assert result == {"items": []}


def test_list_returns_project_items(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src1 = _write_file(tmp_path, "a.png", PNG_BYTES)
    src2 = _write_file(tmp_path, "b.webm", WEBM_BYTES)
    m1rec = _import_media(data_dir, proj["id"], src1, "image")
    m2rec = _import_media(data_dir, proj["id"], src2, "video")

    result = m11.handle(data_dir, {"op": "media.list", "project_id": proj["id"]})
    ids = {item["id"] for item in result["items"]}
    assert ids == {m1rec["id"], m2rec["id"]}
    for item in result["items"]:
        assert item["status"] == "VALID"


def test_list_isolates_projects(data_dir, tmp_path):
    proj_a = _make_project(data_dir, "a")
    proj_b = _make_project(data_dir, "b")
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    _import_media(data_dir, proj_a["id"], src, "image")

    result_b = m11.handle(data_dir, {"op": "media.list", "project_id": proj_b["id"]})
    assert result_b == {"items": []}


def test_list_reports_broken_status(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj["id"], src, "image")

    stored = os.path.join(data_dir, imported["path"])
    with open(stored, "wb") as f:
        f.write(b"corrupted")

    result = m11.handle(data_dir, {"op": "media.list", "project_id": proj["id"]})
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == "BROKEN"


def test_list_rejects_unknown_project(data_dir):
    with pytest.raises(ValueError):
        m11.handle(data_dir, {"op": "media.list", "project_id": "nope"})


# ---------------------------------------------------------------------------
# General validation
# ---------------------------------------------------------------------------

def test_unknown_op_raises(data_dir):
    proj = _make_project(data_dir)
    with pytest.raises(ValueError):
        m11.handle(data_dir, {"op": "media.delete", "project_id": proj["id"]})


def test_missing_op_raises(data_dir):
    proj = _make_project(data_dir)
    with pytest.raises(ValueError):
        m11.handle(data_dir, {"project_id": proj["id"]})


def test_invalid_data_dir_raises():
    with pytest.raises(ValueError):
        m11.handle("", {"op": "media.list", "project_id": "x"})


def test_non_dict_request_raises(data_dir):
    with pytest.raises(ValueError):
        m11.handle(data_dir, ["not", "a", "dict"])


def test_milestone_id_literal():
    assert m11.MILESTONE_ID == "M11"


# ---------------------------------------------------------------------------
# Persistence across processes (reload module / fresh read)
# ---------------------------------------------------------------------------

def test_persistence_survives_reload(data_dir, tmp_path):
    proj = _make_project(data_dir)
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    imported = _import_media(data_dir, proj["id"], src, "image")

    # Simulate a fresh process by reloading the module from disk.
    fresh = _load_module("m11_media_fresh", os.path.join(
        "milestones", "milestone_dbb8341c8910593063a8", "api.py"))
    got = fresh.handle(data_dir, {
        "op": "media.get",
        "project_id": proj["id"],
        "media_id": imported["id"],
    })
    assert got["id"] == imported["id"]
    assert got["status"] == "VALID"


# ---------------------------------------------------------------------------
# Integration with M6 approval
# ---------------------------------------------------------------------------

def _setup_content_with_media(data_dir, tmp_path, media_ids):
    """Create project/campaign/content with the given media_ids, return ids."""
    proj = _make_project(data_dir)
    campaign = m4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": proj["id"],
        "name": "c",
        "audience": "a",
        "channels": ["email"],
    })
    content = m5.handle(data_dir, {
        "op": "content.create",
        "project_id": proj["id"],
        "campaign_id": campaign["id"],
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": media_ids,
    })
    return proj, campaign, content


def test_approval_blocks_broken_media(data_dir, tmp_path):
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    proj = _make_project(data_dir)
    imported = _import_media(data_dir, proj["id"], src, "image")

    campaign = m4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": proj["id"],
        "name": "c",
        "audience": "a",
        "channels": ["email"],
    })
    content = m5.handle(data_dir, {
        "op": "content.create",
        "project_id": proj["id"],
        "campaign_id": campaign["id"],
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [imported["id"]],
    })

    # Corrupt the stored media bytes so it becomes BROKEN.
    stored = os.path.join(data_dir, imported["path"])
    with open(stored, "wb") as f:
        f.write(b"corrupted")

    m6.handle(data_dir, {
        "op": "approval.review",
        "project_id": proj["id"],
        "content_id": content["id"],
    })
    with pytest.raises(ValueError):
        m6.handle(data_dir, {
            "op": "approval.approve",
            "project_id": proj["id"],
            "content_id": content["id"],
        })


def test_approval_blocks_missing_media(data_dir, tmp_path):
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    proj = _make_project(data_dir)
    imported = _import_media(data_dir, proj["id"], src, "image")

    campaign = m4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": proj["id"],
        "name": "c",
        "audience": "a",
        "channels": ["email"],
    })
    content = m5.handle(data_dir, {
        "op": "content.create",
        "project_id": proj["id"],
        "campaign_id": campaign["id"],
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [imported["id"]],
    })

    stored = os.path.join(data_dir, imported["path"])
    os.remove(stored)

    m6.handle(data_dir, {
        "op": "approval.review",
        "project_id": proj["id"],
        "content_id": content["id"],
    })
    with pytest.raises(ValueError):
        m6.handle(data_dir, {
            "op": "approval.approve",
            "project_id": proj["id"],
            "content_id": content["id"],
        })


# ---------------------------------------------------------------------------
# Integration with M7 publication
# ---------------------------------------------------------------------------

def test_publish_blocks_broken_media(data_dir, tmp_path):
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    proj = _make_project(data_dir)
    imported = _import_media(data_dir, proj["id"], src, "image")

    campaign = m4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": proj["id"],
        "name": "c",
        "audience": "a",
        "channels": ["email"],
    })
    content = m5.handle(data_dir, {
        "op": "content.create",
        "project_id": proj["id"],
        "campaign_id": campaign["id"],
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [imported["id"]],
    })

    # Approve while media is valid.
    m6.handle(data_dir, {
        "op": "approval.review",
        "project_id": proj["id"],
        "content_id": content["id"],
    })
    m6.handle(data_dir, {
        "op": "approval.approve",
        "project_id": proj["id"],
        "content_id": content["id"],
    })

    # Now corrupt the media bytes.
    stored = os.path.join(data_dir, imported["path"])
    with open(stored, "wb") as f:
        f.write(b"corrupted")

    with pytest.raises(ValueError):
        m7.handle(data_dir, {
            "op": "publish.send",
            "project_id": proj["id"],
            "content_id": content["id"],
            "platform_url": "http://127.0.0.1:1",
            "idempotency_key": "k1",
        })


def test_publish_blocks_missing_media(data_dir, tmp_path):
    src = _write_file(tmp_path, "pic.png", PNG_BYTES)
    proj = _make_project(data_dir)
    imported = _import_media(data_dir, proj["id"], src, "image")

    campaign = m4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": proj["id"],
        "name": "c",
        "audience": "a",
        "channels": ["email"],
    })
    content = m5.handle(data_dir, {
        "op": "content.create",
        "project_id": proj["id"],
        "campaign_id": campaign["id"],
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [imported["id"]],
    })

    m6.handle(data_dir, {
        "op": "approval.review",
        "project_id": proj["id"],
        "content_id": content["id"],
    })
    m6.handle(data_dir, {
        "op": "approval.approve",
        "project_id": proj["id"],
        "content_id": content["id"],
    })

    stored = os.path.join(data_dir, imported["path"])
    os.remove(stored)

    with pytest.raises(ValueError):
        m7.handle(data_dir, {
            "op": "publish.send",
            "project_id": proj["id"],
            "content_id": content["id"],
            "platform_url": "http://127.0.0.1:1",
            "idempotency_key": "k2",
        })


# ---------------------------------------------------------------------------
# GUI integration (early_main.py)
# ---------------------------------------------------------------------------

def test_gui_displays_media_controls():
    early_main = _load_module("early_main_gui", "early_main.py")
    html = early_main.INDEX_HTML
    # The GUI must surface media (image/video) controls or previews.
    lowered = html.lower()
    assert "media" in lowered
    assert ("<img" in lowered) or ("<video" in lowered) or ("image" in lowered)
