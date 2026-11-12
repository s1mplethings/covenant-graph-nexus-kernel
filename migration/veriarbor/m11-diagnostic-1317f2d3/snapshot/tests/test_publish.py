"""M7 test suite: exercises the declared public contract for promotion_publish.

Covers publish.send/get/list/reconcile/retry, serve_platform routes, and the
early_main.py GUI endpoints (/health, /api/action).
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import promotion_publish as pp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_json(data_dir, filename, items):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, filename), "w", encoding="utf-8") as f:
        json.dump(items, f)


def _seed_project(data_dir, project_id="proj1"):
    _write_json(data_dir, "projects.json", [{"id": project_id, "name": "P"}])
    return project_id


def _seed_approved_content(data_dir, project_id="proj1", content_id="c1", revision=1):
    record = {
        "id": content_id,
        "project_id": project_id,
        "campaign_id": "camp1",
        "channel": "email",
        "text": "hello world",
        "claim_ids": [],
        "media_ids": [],
        "revision": revision,
        "status": "APPROVED",
        "revisions": [],
    }
    _write_json(data_dir, "content.json", [record])
    return record


class _Platform:
    def __init__(self, data_dir):
        self.port = _free_port()
        self.data_dir = data_dir
        self.thread = threading.Thread(
            target=pp.serve_platform,
            args=("127.0.0.1", self.port, data_dir),
            daemon=True,
        )
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.port
        self._wait_ready()

    def _wait_ready(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("platform did not start")


@pytest.fixture
def data_dir(tmp_path):
    d = str(tmp_path / "data")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def platform(data_dir):
    return _Platform(data_dir)


# ---------------------------------------------------------------------------
# publish.send
# ---------------------------------------------------------------------------


def test_send_success_publishes_and_returns_receipt(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send",
        "project_id": pid,
        "content_id": "c1",
        "platform_url": platform.url,
        "idempotency_key": "k1",
    })
    assert receipt["status"] == "PUBLISHED"
    assert receipt["remote_id"]
    assert receipt["idempotency_key"] == "k1"
    assert receipt["project_id"] == pid
    assert receipt["content_id"] == "c1"
    assert receipt["attempts"]


def test_send_rate_limited_on_429(data_dir, monkeypatch):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)

    monkeypatch.setattr(pp.urllib.request, "urlopen", fake_urlopen)
    receipt = pp.handle(data_dir, {
        "op": "publish.send",
        "project_id": pid,
        "content_id": "c1",
        "platform_url": "http://127.0.0.1:1",
        "idempotency_key": "k429",
    })
    assert receipt["status"] == "RATE_LIMITED"


def test_send_unknown_on_connection_loss(data_dir, monkeypatch):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(pp.urllib.request, "urlopen", fake_urlopen)
    receipt = pp.handle(data_dir, {
        "op": "publish.send",
        "project_id": pid,
        "content_id": "c1",
        "platform_url": "http://127.0.0.1:1",
        "idempotency_key": "kunk",
    })
    assert receipt["status"] == "UNKNOWN"


def test_send_idempotent_key_does_not_resend(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    req = {
        "op": "publish.send",
        "project_id": pid,
        "content_id": "c1",
        "platform_url": platform.url,
        "idempotency_key": "dup",
    }
    first = pp.handle(data_dir, req)
    second = pp.handle(data_dir, req)
    assert first["id"] == second["id"]
    assert first["remote_id"] == second["remote_id"]
    # Only one publication recorded on the platform.
    pubs = pp._load_list(data_dir, "publications.json")
    assert len([p for p in pubs if p["idempotency_key"] == "dup"]) == 1


def test_send_reused_key_changed_payload_raises(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    pp.handle(data_dir, {
        "op": "publish.send",
        "project_id": pid,
        "content_id": "c1",
        "platform_url": platform.url,
        "idempotency_key": "reuse",
    })
    # Change content revision -> payload differs.
    _seed_approved_content(data_dir, pid, revision=2)
    with pytest.raises(ValueError):
        pp.handle(data_dir, {
            "op": "publish.send",
            "project_id": pid,
            "content_id": "c1",
            "platform_url": platform.url,
            "idempotency_key": "reuse",
        })


def test_send_requires_approved_content(data_dir, platform):
    pid = _seed_project(data_dir)
    _write_json(data_dir, "content.json", [{
        "id": "c1", "project_id": pid, "campaign_id": "camp1",
        "channel": "email", "text": "x", "claim_ids": [], "media_ids": [],
        "revision": 1, "status": "DRAFT", "revisions": [],
    }])
    with pytest.raises(ValueError):
        pp.handle(data_dir, {
            "op": "publish.send",
            "project_id": pid,
            "content_id": "c1",
            "platform_url": platform.url,
            "idempotency_key": "k",
        })


# ---------------------------------------------------------------------------
# publish.get / publish.list
# ---------------------------------------------------------------------------


def test_get_retrieves_receipt(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "g1",
    })
    got = pp.handle(data_dir, {
        "op": "publish.get", "project_id": pid, "receipt_id": receipt["id"],
    })
    assert got["id"] == receipt["id"]
    assert got["status"] == "PUBLISHED"


def test_get_unknown_receipt_raises(data_dir):
    pid = _seed_project(data_dir)
    with pytest.raises(ValueError):
        pp.handle(data_dir, {"op": "publish.get", "project_id": pid, "receipt_id": "nope"})


def test_get_cross_project_raises(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "x1",
    })
    _write_json(data_dir, "projects.json", [
        {"id": pid, "name": "P"}, {"id": "proj2", "name": "Q"},
    ])
    with pytest.raises(ValueError):
        pp.handle(data_dir, {"op": "publish.get", "project_id": "proj2", "receipt_id": receipt["id"]})


def test_list_returns_project_receipts(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "l1",
    })
    result = pp.handle(data_dir, {"op": "publish.list", "project_id": pid})
    assert len(result["items"]) == 1
    assert result["items"][0]["idempotency_key"] == "l1"


# ---------------------------------------------------------------------------
# publish.reconcile
# ---------------------------------------------------------------------------


def test_reconcile_confirms_published(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "r1",
    })
    result = pp.handle(data_dir, {
        "op": "publish.reconcile", "project_id": pid,
        "receipt_id": receipt["id"], "platform_url": platform.url,
    })
    assert result["status"] == "PUBLISHED"
    assert result["remote_id"]


def test_reconcile_records_absence_on_404(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    # Create a receipt whose key is not on the platform.
    receipts = [{
        "id": "rid", "project_id": pid, "content_id": "c1", "revision": 1,
        "channel": "email", "text": "hello world", "status": "UNKNOWN",
        "remote_id": None, "idempotency_key": "absent-key",
        "request_ref": None, "response_ref": None, "attempts": [], "url": None,
    }]
    _write_json(data_dir, "receipts.json", receipts)
    result = pp.handle(data_dir, {
        "op": "publish.reconcile", "project_id": pid,
        "receipt_id": "rid", "platform_url": platform.url,
    })
    assert result["status"] == "ABSENT"


# ---------------------------------------------------------------------------
# publish.retry
# ---------------------------------------------------------------------------


def test_retry_resends_failed_branch(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipts = [{
        "id": "rid", "project_id": pid, "content_id": "c1", "revision": 1,
        "channel": "email", "text": "hello world", "status": "RATE_LIMITED",
        "remote_id": None, "idempotency_key": "retry-key",
        "request_ref": None, "response_ref": None, "attempts": [], "url": None,
    }]
    _write_json(data_dir, "receipts.json", receipts)
    result = pp.handle(data_dir, {
        "op": "publish.retry", "project_id": pid,
        "receipt_id": "rid", "platform_url": platform.url,
    })
    assert result["status"] == "PUBLISHED"
    assert result["remote_id"]


def test_retry_published_is_noop(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "done",
    })
    result = pp.handle(data_dir, {
        "op": "publish.retry", "project_id": pid,
        "receipt_id": receipt["id"], "platform_url": platform.url,
    })
    assert result["status"] == "PUBLISHED"
    assert result["remote_id"] == receipt["remote_id"]


# ---------------------------------------------------------------------------
# serve_platform routes
# ---------------------------------------------------------------------------


def test_platform_publish_and_publications_routes(platform):
    payload = json.dumps({
        "idempotency_key": "pk", "project_id": "p", "content_id": "c",
        "revision": 1, "channel": "email", "text": "t",
    }).encode("utf-8")
    req = urllib.request.Request(
        platform.url + "/publish", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body["remote_id"]

    with urllib.request.urlopen(
        platform.url + "/publications?key=pk", timeout=5
    ) as resp:
        pub = json.loads(resp.read().decode("utf-8"))
    assert pub["id"] == body["remote_id"]

    with urllib.request.urlopen(
        platform.url + "/metrics?remote_id=" + body["remote_id"], timeout=5
    ) as resp:
        metrics = json.loads(resp.read().decode("utf-8"))
    assert metrics["remote_id"] == body["remote_id"]


def test_platform_publications_404_for_unknown_key(platform):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(platform.url + "/publications?key=missing", timeout=5)
    assert exc.value.code == 404


# ---------------------------------------------------------------------------
# Persistence across process restarts
# ---------------------------------------------------------------------------


def test_receipts_persist_across_restart(data_dir, platform):
    pid = _seed_project(data_dir)
    _seed_approved_content(data_dir, pid)
    receipt = pp.handle(data_dir, {
        "op": "publish.send", "project_id": pid, "content_id": "c1",
        "platform_url": platform.url, "idempotency_key": "persist",
    })
    # Simulate a fresh process by reloading from disk.
    got = pp.handle(data_dir, {
        "op": "publish.get", "project_id": pid, "receipt_id": receipt["id"],
    })
    assert got["id"] == receipt["id"]
    assert got["status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_op_raises(data_dir):
    pid = _seed_project(data_dir)
    with pytest.raises(ValueError):
        pp.handle(data_dir, {"op": "publish.bogus", "project_id": pid})


def test_unknown_project_raises(data_dir):
    with pytest.raises(ValueError):
        pp.handle(data_dir, {"op": "publish.list", "project_id": "missing"})


# ---------------------------------------------------------------------------
# early_main.py GUI
# ---------------------------------------------------------------------------


def _start_gui(data_dir):
    port = _free_port()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(root, "early_main.py"),
         "--serve", "--port", str(port), "--data", data_dir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = "http://127.0.0.1:%d" % port
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=0.5) as resp:
                if resp.getcode() == 200:
                    return proc, base
        except Exception:
            time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("GUI did not start")


@pytest.fixture
def gui(tmp_path):
    data_dir = str(tmp_path / "gui_data")
    os.makedirs(data_dir, exist_ok=True)
    proc, base = _start_gui(data_dir)
    try:
        yield base, data_dir
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _action(base, payload):
    req = urllib.request.Request(
        base + "/api/action",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_gui_health(gui):
    base, _ = gui
    with urllib.request.urlopen(base + "/health", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body == {"status": "ok"}


def test_gui_workflow_creates_and_publishes(gui):
    base, _ = gui
    project = _action(base, {"milestone": "M1", "op": "project.create", "name": "Proj"})
    assert project["name"] == "Proj"
    pid = project["id"]

    campaign = _action(base, {
        "milestone": "M4", "op": "campaign.create", "project_id": pid,
        "name": "Camp", "audience": "all", "channels": ["email"],
    })
    cid = campaign["id"]

    content = _action(base, {
        "milestone": "M5", "op": "content.create", "project_id": pid,
        "campaign_id": cid, "channel": "email", "text": "hello",
        "claim_ids": [], "media_ids": [],
    })
    content_id = content["id"]

    _action(base, {"milestone": "M6", "op": "approval.review",
                   "project_id": pid, "content_id": content_id})
    approved = _action(base, {"milestone": "M6", "op": "approval.approve",
                             "project_id": pid, "content_id": content_id})
    assert approved["status"] == "APPROVED"

    # Start a platform for publishing.
    platform = _Platform(os.path.join(os.path.dirname(base), "platform_data"))
    receipt = _action(base, {
        "milestone": "M7", "op": "publish.send", "project_id": pid,
        "content_id": content_id, "platform_url": platform.url,
        "idempotency_key": "gui-key",
    })
    assert receipt["status"] == "PUBLISHED"
    assert receipt["remote_id"]


def test_gui_invalid_action_raises(gui):
    base, _ = gui
    with pytest.raises(urllib.error.HTTPError):
        _action(base, {"milestone": "M1", "op": "project.get", "project_id": "missing"})
