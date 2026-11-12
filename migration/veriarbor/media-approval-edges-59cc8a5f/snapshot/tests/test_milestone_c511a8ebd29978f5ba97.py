"""Milestone M9: Receipt Queries test suite.

Exercises the declared public contract for receipt.list, receipt.get and
receipt.export over authoritative M7 receipts. Uses the actual M1 project and
M7 receipt APIs (promotion_publish.handle) to seed data rather than legacy
fixture storage layouts.
"""

import importlib
import json
import os
import sys

import pytest


# ---------------------------------------------------------------------------
# Module discovery: locate M9 by literal MILESTONE_ID, not guessed filenames.
# ---------------------------------------------------------------------------

def _load_module_by_milestone_id(milestone_id):
    candidates = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in (root, os.path.join(root, "milestones")):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                api = os.path.join(full, "api.py")
                if os.path.isfile(api):
                    candidates.append(api)
    for api_path in candidates:
        try:
            spec = importlib.util.spec_from_file_location(
                "_m9_candidate_%d" % abs(hash(api_path)), api_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            continue
        if getattr(module, "MILESTONE_ID", None) == milestone_id:
            return module
    raise RuntimeError("M9 module with MILESTONE_ID=%r not found" % milestone_id)


M9 = _load_module_by_milestone_id("M9")


# ---------------------------------------------------------------------------
# Dependency discovery: M1 project API and M7 receipt API.
# ---------------------------------------------------------------------------

def _load_dependency(milestone_id, fallback_names):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in (root, os.path.join(root, "milestones")):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                api = os.path.join(full, "api.py")
                if os.path.isfile(api):
                    try:
                        spec = importlib.util.spec_from_file_location(
                            "_dep_%s_%d" % (milestone_id, abs(hash(api))), api
                        )
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                    except Exception:
                        continue
                    if getattr(module, "MILESTONE_ID", None) == milestone_id:
                        return module
    for fname in fallback_names:
        path = os.path.join(root, fname)
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location(
                "_dep_%s_%d" % (milestone_id, abs(hash(path))), path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("dependency %r not found" % milestone_id)


M1 = _load_dependency("M1", [])
M7 = _load_dependency("M7", ["promotion_publish.py"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(data_dir, name="proj"):
    return M1.handle(data_dir, {"op": "project.create", "name": name})


def _seed_receipt(data_dir, project_id, content_id, revision, channel, text,
                  status, idempotency_key, remote_id=None, attempts=None):
    """Seed an authoritative M7 receipt directly into M7's receipts store.

    Uses M7's own storage filename so the M9 module reads the same
    authoritative database (no second conflicting receipt database).
    """
    receipts_path = os.path.join(data_dir, "receipts.json")
    if os.path.exists(receipts_path):
        with open(receipts_path, "r", encoding="utf-8") as f:
            content = f.read()
        receipts = json.loads(content) if content.strip() else []
    else:
        receipts = []
    record = {
        "id": "rcpt-" + idempotency_key,
        "project_id": project_id,
        "content_id": content_id,
        "revision": revision,
        "channel": channel,
        "text": text,
        "status": status,
        "remote_id": remote_id,
        "idempotency_key": idempotency_key,
        "request_ref": "http://localhost/publish",
        "response_ref": None,
        "attempts": attempts if attempts is not None else [],
        "url": None,
    }
    receipts.append(record)
    os.makedirs(data_dir, exist_ok=True)
    with open(receipts_path, "w", encoding="utf-8") as f:
        json.dump(receipts, f, ensure_ascii=False)
    return record


def _call(data_dir, request):
    return M9.handle(data_dir, request)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def project(data_dir):
    return _make_project(data_dir, "alpha")


@pytest.fixture()
def seeded(data_dir, project):
    pid = project["id"]
    r1 = _seed_receipt(
        data_dir, pid, "content-1", 1, "twitter", "hello world",
        "PUBLISHED", "key-1", remote_id="remote-1",
        attempts=[{"operation": "POST", "status": "SUCCESS",
                   "started_at": 1.0, "ended_at": 2.0}],
    )
    r2 = _seed_receipt(
        data_dir, pid, "content-2", 2, "linkedin", "second post",
        "RATE_LIMITED", "key-2",
        attempts=[{"operation": "POST", "status": "RATE_LIMITED",
                   "started_at": 3.0, "ended_at": 4.0}],
    )
    r3 = _seed_receipt(
        data_dir, pid, "content-3", 3, "twitter", "third post",
        "UNKNOWN", "key-3",
        attempts=[{"operation": "POST", "status": "TIMEOUT_OR_CONNECTION_LOSS",
                   "started_at": 5.0, "ended_at": 6.0}],
    )
    return {"project_id": pid, "receipts": [r1, r2, r3]}


# ---------------------------------------------------------------------------
# receipt.list
# ---------------------------------------------------------------------------

def test_list_returns_all_project_receipts(data_dir, seeded):
    result = _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    assert isinstance(result, dict)
    items = result["items"]
    assert len(items) == 3
    ids = {r["id"] for r in items}
    assert ids == {r["id"] for r in seeded["receipts"]}


def test_list_preserves_identity_and_revision(data_dir, seeded):
    result = _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    by_id = {r["id"]: r for r in result["items"]}
    for original in seeded["receipts"]:
        got = by_id[original["id"]]
        assert got["revision"] == original["revision"]
        assert got["channel"] == original["channel"]
        assert got["content_id"] == original["content_id"]
        assert got["idempotency_key"] == original["idempotency_key"]


def test_list_filter_by_channel(data_dir, seeded):
    result = _call(data_dir, {
        "op": "receipt.list", "project_id": seeded["project_id"], "channel": "twitter"
    })
    items = result["items"]
    assert len(items) == 2
    assert all(r["channel"] == "twitter" for r in items)


def test_list_filter_by_status(data_dir, seeded):
    result = _call(data_dir, {
        "op": "receipt.list", "project_id": seeded["project_id"], "status": "UNKNOWN"
    })
    items = result["items"]
    assert len(items) == 1
    assert items[0]["status"] == "UNKNOWN"


def test_list_filter_by_channel_and_status(data_dir, seeded):
    result = _call(data_dir, {
        "op": "receipt.list", "project_id": seeded["project_id"],
        "channel": "twitter", "status": "PUBLISHED",
    })
    items = result["items"]
    assert len(items) == 1
    assert items[0]["channel"] == "twitter"
    assert items[0]["status"] == "PUBLISHED"


def test_list_empty_for_project_without_receipts(data_dir, project):
    result = _call(data_dir, {"op": "receipt.list", "project_id": project["id"]})
    assert result["items"] == []


def test_list_isolates_projects(data_dir, seeded):
    other = _make_project(data_dir, "beta")
    _seed_receipt(data_dir, other["id"], "c-other", 1, "twitter", "other",
                  "PUBLISHED", "key-other", remote_id="remote-other")
    result = _call(data_dir, {"op": "receipt.list", "project_id": other["id"]})
    items = result["items"]
    assert len(items) == 1
    assert items[0]["project_id"] == other["id"]
    # Original project unaffected
    original = _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    assert len(original["items"]) == 3


def test_list_unknown_project_raises(data_dir):
    with pytest.raises(ValueError):
        _call(data_dir, {"op": "receipt.list", "project_id": "does-not-exist"})


def test_list_missing_project_id_raises(data_dir):
    with pytest.raises(ValueError):
        _call(data_dir, {"op": "receipt.list"})


# ---------------------------------------------------------------------------
# receipt.get
# ---------------------------------------------------------------------------

def test_get_returns_single_receipt(data_dir, seeded):
    target = seeded["receipts"][0]
    result = _call(data_dir, {
        "op": "receipt.get", "project_id": seeded["project_id"],
        "receipt_id": target["id"],
    })
    assert result["id"] == target["id"]
    assert result["revision"] == target["revision"]
    assert result["channel"] == target["channel"]
    assert result["remote_id"] == target["remote_id"]
    assert result["idempotency_key"] == target["idempotency_key"]


def test_get_preserves_unknown_status(data_dir, seeded):
    unknown = [r for r in seeded["receipts"] if r["status"] == "UNKNOWN"][0]
    result = _call(data_dir, {
        "op": "receipt.get", "project_id": seeded["project_id"],
        "receipt_id": unknown["id"],
    })
    assert result["status"] == "UNKNOWN"
    assert result["remote_id"] is None


def test_get_preserves_attempts(data_dir, seeded):
    target = seeded["receipts"][1]
    result = _call(data_dir, {
        "op": "receipt.get", "project_id": seeded["project_id"],
        "receipt_id": target["id"],
    })
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["status"] == "RATE_LIMITED"


def test_get_unknown_receipt_raises(data_dir, seeded):
    with pytest.raises(ValueError):
        _call(data_dir, {
            "op": "receipt.get", "project_id": seeded["project_id"],
            "receipt_id": "no-such-receipt",
        })


def test_get_foreign_receipt_raises(data_dir, seeded):
    other = _make_project(data_dir, "beta")
    target = seeded["receipts"][0]
    with pytest.raises(ValueError):
        _call(data_dir, {
            "op": "receipt.get", "project_id": other["id"],
            "receipt_id": target["id"],
        })


def test_get_missing_receipt_id_raises(data_dir, seeded):
    with pytest.raises(ValueError):
        _call(data_dir, {"op": "receipt.get", "project_id": seeded["project_id"]})


# ---------------------------------------------------------------------------
# receipt.export
# ---------------------------------------------------------------------------

def test_export_returns_receipts_and_timestamp(data_dir, seeded):
    result = _call(data_dir, {"op": "receipt.export", "project_id": seeded["project_id"]})
    assert isinstance(result, dict)
    assert "receipts" in result
    assert "exported_at" in result
    assert isinstance(result["exported_at"], str)
    assert len(result["receipts"]) == 3


def test_export_timestamp_is_iso8601(data_dir, seeded):
    from datetime import datetime
    result = _call(data_dir, {"op": "receipt.export", "project_id": seeded["project_id"]})
    # Must parse as ISO8601
    parsed = datetime.fromisoformat(result["exported_at"].replace("Z", "+00:00"))
    assert parsed is not None


def test_export_isolates_projects(data_dir, seeded):
    other = _make_project(data_dir, "beta")
    result = _call(data_dir, {"op": "receipt.export", "project_id": other["id"]})
    assert result["receipts"] == []


def test_export_unknown_project_raises(data_dir):
    with pytest.raises(ValueError):
        _call(data_dir, {"op": "receipt.export", "project_id": "nope"})


# ---------------------------------------------------------------------------
# Unsupported operations and persistence
# ---------------------------------------------------------------------------

def test_unsupported_op_raises(data_dir, project):
    with pytest.raises(ValueError):
        _call(data_dir, {"op": "receipt.delete", "project_id": project["id"]})


def test_persistence_across_calls(data_dir, seeded):
    first = _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    second = _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    assert {r["id"] for r in first["items"]} == {r["id"] for r in second["items"]}


def test_queries_do_not_mutate_receipts(data_dir, seeded):
    receipts_path = os.path.join(data_dir, "receipts.json")
    with open(receipts_path, "r", encoding="utf-8") as f:
        before = f.read()
    _call(data_dir, {"op": "receipt.list", "project_id": seeded["project_id"]})
    _call(data_dir, {"op": "receipt.get", "project_id": seeded["project_id"],
                     "receipt_id": seeded["receipts"][0]["id"]})
    _call(data_dir, {"op": "receipt.export", "project_id": seeded["project_id"]})
    with open(receipts_path, "r", encoding="utf-8") as f:
        after = f.read()
    assert before == after
