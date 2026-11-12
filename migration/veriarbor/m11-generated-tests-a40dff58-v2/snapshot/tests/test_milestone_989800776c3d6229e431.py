"""Milestone M8: Scheduler test suite.

Exercises the declared public contract for schedule.create, schedule.list,
schedule.cancel, schedule.reschedule and schedule.run_due, including
timezone-aware timestamp validation, approval gating, project isolation,
run_due idempotency across restart, UNKNOWN non-retryability, sibling
preservation, and cross-process persistence.
"""

import importlib.util
import json
import os
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(name, rel_path):
    path = os.path.join(REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M8 = _load_module("m8_scheduler", os.path.join("milestones", "milestone_989800776c3d6229e431", "api.py"))
M1 = _load_module("m1_projects", os.path.join("milestones", "milestone_20f2614f6ae8403d4a4e", "api.py"))
M4 = _load_module("m4_campaigns", os.path.join("milestones", "milestone_90b8868c7203e2958397", "api.py"))
M5 = _load_module("m5_content", os.path.join("milestones", "milestone_9165a990eed5b9c8801e", "api.py"))
M6 = _load_module("m6_approval", os.path.join("milestones", "milestone_33270fed0c9054f5ae04", "api.py"))


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


def _make_project(data_dir, name="proj"):
    return M1.handle(data_dir, {"op": "project.create", "name": name})


def _make_approved_content(data_dir, project_id):
    campaign = M4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": project_id,
        "name": "camp",
        "audience": "aud",
        "channels": ["twitter"],
    })
    content = M5.handle(data_dir, {
        "op": "content.create",
        "project_id": project_id,
        "campaign_id": campaign["id"],
        "channel": "twitter",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [],
    })
    M6.handle(data_dir, {
        "op": "approval.review",
        "project_id": project_id,
        "content_id": content["id"],
    })
    M6.handle(data_dir, {
        "op": "approval.approve",
        "project_id": project_id,
        "content_id": content["id"],
    })
    return content


def _make_draft_content(data_dir, project_id):
    campaign = M4.handle(data_dir, {
        "op": "campaign.create",
        "project_id": project_id,
        "name": "camp",
        "audience": "aud",
        "channels": ["twitter"],
    })
    return M5.handle(data_dir, {
        "op": "content.create",
        "project_id": project_id,
        "campaign_id": campaign["id"],
        "channel": "twitter",
        "text": "draft text",
        "claim_ids": [],
        "media_ids": [],
    })


class FakePlatform:
    """In-process fake M7 platform used to control publish outcomes."""

    def __init__(self, status="PUBLISHED"):
        self.status = status
        self.calls = []

    def __call__(self, data_dir, request):
        self.calls.append(dict(request))
        if self.status == "PUBLISHED":
            return {
                "id": "receipt-%d" % len(self.calls),
                "status": "PUBLISHED",
                "remote_id": "remote-%d" % len(self.calls),
            }
        return {
            "id": "receipt-%d" % len(self.calls),
            "status": self.status,
            "remote_id": None,
        }


@pytest.fixture()
def fake_platform(monkeypatch):
    platform = FakePlatform("PUBLISHED")
    monkeypatch.setattr(M8, "_publish_handle", lambda: platform)
    return platform


# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------


def test_milestone_id_is_m8():
    assert M8.MILESTONE_ID == "M8"


def test_handle_is_callable():
    assert callable(M8.handle)


# ---------------------------------------------------------------------------
# schedule.create
# ---------------------------------------------------------------------------


def test_create_returns_pending_record(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    record = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-1",
    })
    assert record["status"] == "PENDING"
    assert record["project_id"] == project["id"]
    assert record["content_id"] == content["id"]
    assert record["platform_url"] == "http://localhost:9999"
    assert record["idempotency_key"] == "key-1"
    assert record["when"] == "2030-01-01T00:00:00+00:00"
    assert record["id"]


def test_create_accepts_z_suffix(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    record = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00Z",
        "idempotency_key": "key-z",
    })
    assert record["status"] == "PENDING"


def test_create_rejects_naive_timestamp(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": content["id"],
            "platform_url": "http://localhost:9999",
            "when": "2030-01-01T00:00:00",
            "idempotency_key": "key-naive",
        })


def test_create_rejects_malformed_timestamp(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": content["id"],
            "platform_url": "http://localhost:9999",
            "when": "not-a-timestamp",
            "idempotency_key": "key-bad",
        })


def test_create_rejects_unapproved_content(data_dir):
    project = _make_project(data_dir)
    content = _make_draft_content(data_dir, project["id"])
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": content["id"],
            "platform_url": "http://localhost:9999",
            "when": "2030-01-01T00:00:00+00:00",
            "idempotency_key": "key-draft",
        })


def test_create_rejects_unknown_project(data_dir):
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": "missing",
            "content_id": "c",
            "platform_url": "http://localhost:9999",
            "when": "2030-01-01T00:00:00+00:00",
            "idempotency_key": "k",
        })


def test_create_rejects_unknown_content(data_dir):
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": "missing",
            "platform_url": "http://localhost:9999",
            "when": "2030-01-01T00:00:00+00:00",
            "idempotency_key": "k",
        })


def test_create_rejects_blank_platform_url(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": content["id"],
            "platform_url": "   ",
            "when": "2030-01-01T00:00:00+00:00",
            "idempotency_key": "k",
        })


def test_create_rejects_blank_idempotency_key(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.create",
            "project_id": project["id"],
            "content_id": content["id"],
            "platform_url": "http://localhost:9999",
            "when": "2030-01-01T00:00:00+00:00",
            "idempotency_key": "",
        })


# ---------------------------------------------------------------------------
# schedule.list
# ---------------------------------------------------------------------------


def test_list_returns_created_schedules(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-list",
    })
    result = M8.handle(data_dir, {"op": "schedule.list", "project_id": project["id"]})
    assert "items" in result
    ids = [item["id"] for item in result["items"]]
    assert created["id"] in ids


def test_list_is_project_isolated(data_dir):
    p1 = _make_project(data_dir, "p1")
    p2 = _make_project(data_dir, "p2")
    c1 = _make_approved_content(data_dir, p1["id"])
    c2 = _make_approved_content(data_dir, p2["id"])
    s1 = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": p1["id"],
        "content_id": c1["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "k1",
    })
    s2 = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": p2["id"],
        "content_id": c2["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "k2",
    })
    items1 = M8.handle(data_dir, {"op": "schedule.list", "project_id": p1["id"]})["items"]
    items2 = M8.handle(data_dir, {"op": "schedule.list", "project_id": p2["id"]})["items"]
    assert [i["id"] for i in items1] == [s1["id"]]
    assert [i["id"] for i in items2] == [s2["id"]]


def test_list_rejects_unknown_project(data_dir):
    with pytest.raises(ValueError):
        M8.handle(data_dir, {"op": "schedule.list", "project_id": "missing"})


# ---------------------------------------------------------------------------
# schedule.cancel
# ---------------------------------------------------------------------------


def test_cancel_sets_cancelled(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-cancel",
    })
    cancelled = M8.handle(data_dir, {
        "op": "schedule.cancel",
        "project_id": project["id"],
        "schedule_id": created["id"],
    })
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["id"] == created["id"]


def test_cancel_rejects_unknown_schedule(data_dir):
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.cancel",
            "project_id": project["id"],
            "schedule_id": "missing",
        })


def test_cancel_rejects_cross_project(data_dir):
    p1 = _make_project(data_dir, "p1")
    p2 = _make_project(data_dir, "p2")
    c1 = _make_approved_content(data_dir, p1["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": p1["id"],
        "content_id": c1["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "k",
    })
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.cancel",
            "project_id": p2["id"],
            "schedule_id": created["id"],
        })


# ---------------------------------------------------------------------------
# schedule.reschedule
# ---------------------------------------------------------------------------


def test_reschedule_updates_when_and_history(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-resched",
    })
    updated = M8.handle(data_dir, {
        "op": "schedule.reschedule",
        "project_id": project["id"],
        "schedule_id": created["id"],
        "when": "2031-06-01T12:00:00+00:00",
    })
    assert updated["id"] == created["id"]
    assert updated["when"] == "2031-06-01T12:00:00+00:00"
    assert len(updated["history"]) == 1
    assert updated["history"][0]["when"] == "2030-01-01T00:00:00+00:00"


def test_reschedule_does_not_create_duplicate(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-resched2",
    })
    M8.handle(data_dir, {
        "op": "schedule.reschedule",
        "project_id": project["id"],
        "schedule_id": created["id"],
        "when": "2031-06-01T12:00:00+00:00",
    })
    items = M8.handle(data_dir, {"op": "schedule.list", "project_id": project["id"]})["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]


def test_reschedule_rejects_naive_timestamp(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-resched3",
    })
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.reschedule",
            "project_id": project["id"],
            "schedule_id": created["id"],
            "when": "2031-06-01T12:00:00",
        })


def test_reschedule_rejects_unknown_schedule(data_dir):
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.reschedule",
            "project_id": project["id"],
            "schedule_id": "missing",
            "when": "2031-06-01T12:00:00+00:00",
        })


# ---------------------------------------------------------------------------
# schedule.run_due
# ---------------------------------------------------------------------------


def test_run_due_processes_due_schedule(data_dir, fake_platform):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-run",
    })
    result = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    assert len(result["items"]) == 1
    processed = result["items"][0]
    assert processed["id"] == created["id"]
    assert processed["status"] == "PUBLISHED"
    assert processed["receipt_id"]
    assert processed["result_status"] == "PUBLISHED"
    assert len(fake_platform.calls) == 1


def test_run_due_skips_future_schedule(data_dir, fake_platform):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-future",
    })
    result = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2029-01-01T00:00:00+00:00",
    })
    assert result["items"] == []
    assert fake_platform.calls == []


def test_run_due_skips_cancelled_schedule(data_dir, fake_platform):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-cancel-run",
    })
    M8.handle(data_dir, {
        "op": "schedule.cancel",
        "project_id": project["id"],
        "schedule_id": created["id"],
    })
    result = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    assert result["items"] == []
    assert fake_platform.calls == []


def test_run_due_rejects_naive_now(data_dir):
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        M8.handle(data_dir, {
            "op": "schedule.run_due",
            "project_id": project["id"],
            "now": "2030-01-02T00:00:00",
        })


def test_run_due_idempotent_across_repeated_calls(data_dir, fake_platform):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-idem",
    })
    first = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    assert len(first["items"]) == 1
    second = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-03T00:00:00+00:00",
    })
    assert second["items"] == []
    assert len(fake_platform.calls) == 1


def test_run_due_idempotent_across_restart(data_dir, fake_platform):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-restart",
    })
    M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    # Simulate restart by reloading the module fresh.
    fresh = _load_module("m8_scheduler_restart", os.path.join("milestones", "milestone_989800776c3d6229e431", "api.py"))
    fresh._publish_handle = lambda: fake_platform
    second = fresh.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-03T00:00:00+00:00",
    })
    assert second["items"] == []
    assert len(fake_platform.calls) == 1


def test_run_due_unknown_not_retried(data_dir, monkeypatch):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    platform = FakePlatform("UNKNOWN")
    monkeypatch.setattr(M8, "_publish_handle", lambda: platform)
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "key-unknown",
    })
    first = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    assert len(first["items"]) == 1
    assert first["items"][0]["status"] == "UNKNOWN"
    assert first["items"][0]["result_status"] == "UNKNOWN"
    assert len(platform.calls) == 1
    # A second run must not silently retry the UNKNOWN schedule.
    second = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-03T00:00:00+00:00",
    })
    assert second["items"] == []
    assert len(platform.calls) == 1


def test_run_due_preserves_successful_siblings(data_dir, monkeypatch):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    platform = FakePlatform("PUBLISHED")
    monkeypatch.setattr(M8, "_publish_handle", lambda: platform)
    s1 = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "sib-1",
    })
    s2 = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "sib-2",
    })
    M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": project["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    items = M8.handle(data_dir, {"op": "schedule.list", "project_id": project["id"]})["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[s1["id"]]["status"] == "PUBLISHED"
    assert by_id[s2["id"]]["status"] == "PUBLISHED"
    assert len(platform.calls) == 2


def test_run_due_project_isolated(data_dir, fake_platform):
    p1 = _make_project(data_dir, "p1")
    p2 = _make_project(data_dir, "p2")
    c1 = _make_approved_content(data_dir, p1["id"])
    c2 = _make_approved_content(data_dir, p2["id"])
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": p1["id"],
        "content_id": c1["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "iso-1",
    })
    M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": p2["id"],
        "content_id": c2["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "iso-2",
    })
    result = M8.handle(data_dir, {
        "op": "schedule.run_due",
        "project_id": p1["id"],
        "now": "2030-01-02T00:00:00+00:00",
    })
    assert len(result["items"]) == 1
    assert len(fake_platform.calls) == 1
    p2_items = M8.handle(data_dir, {"op": "schedule.list", "project_id": p2["id"]})["items"]
    assert p2_items[0]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# General validation
# ---------------------------------------------------------------------------


def test_unknown_op_raises(data_dir):
    project = _make_project(data_dir)
    with pytest.raises(ValueError):
        M8.handle(data_dir, {"op": "schedule.bogus", "project_id": project["id"]})


def test_missing_op_raises(data_dir):
    with pytest.raises(ValueError):
        M8.handle(data_dir, {"project_id": "x"})


def test_invalid_data_dir_raises():
    with pytest.raises(ValueError):
        M8.handle("", {"op": "schedule.list", "project_id": "x"})


def test_invalid_request_raises(data_dir):
    with pytest.raises(ValueError):
        M8.handle(data_dir, "not-a-dict")


# ---------------------------------------------------------------------------
# Cross-process persistence
# ---------------------------------------------------------------------------


def test_persistence_across_processes(data_dir):
    project = _make_project(data_dir)
    content = _make_approved_content(data_dir, project["id"])
    created = M8.handle(data_dir, {
        "op": "schedule.create",
        "project_id": project["id"],
        "content_id": content["id"],
        "platform_url": "http://localhost:9999",
        "when": "2030-01-01T00:00:00+00:00",
        "idempotency_key": "persist-key",
    })

    script = textwrap.dedent(
        """
        import importlib.util, json, os, sys
        repo = sys.argv[1]
        data_dir = sys.argv[2]
        project_id = sys.argv[3]
        path = os.path.join(repo, 'milestones', 'milestone_989800776c3d6229e431', 'api.py')
        spec = importlib.util.spec_from_file_location('m8_sub', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.handle(data_dir, {'op': 'schedule.list', 'project_id': project_id})
        print(json.dumps(result))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, REPO_ROOT, data_dir, project["id"]],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    ids = [item["id"] for item in result["items"]]
    assert created["id"] in ids
