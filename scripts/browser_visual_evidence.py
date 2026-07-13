from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from contracts.status import EvidenceStatus
from contracts.visual_evidence import KIND, PRODUCER, SCHEMA_VERSION
from scripts import customer_runtime_runner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _wait(url: str, seconds: float = 5.0) -> bool:
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:  # noqa: S310 - localhost probe
                return int(response.status) == 200
        except Exception:
            time.sleep(0.1)
    return False


def run(project_dir: str | pathlib.Path, *, runtime_ref: str | pathlib.Path | None = None) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    runtime_path = pathlib.Path(runtime_ref) if runtime_ref else project / "customer_runtime.json"
    runtime_inspection = customer_runtime_runner.inspect(runtime_path)
    runtime_doc = runtime_inspection.get("details", {}) if isinstance(runtime_inspection.get("details"), dict) else {}
    candidate_hash = str(runtime_doc.get("candidate_hash") or customer_runtime_runner._tree_hash(project))
    commit_sha = str(runtime_doc.get("commit_sha") or customer_runtime_runner._commit_sha(project))
    run_id = str(runtime_doc.get("run_id") or f"visual-run-{uuid.uuid4().hex}")
    port = customer_runtime_runner._free_port()
    argv = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
    url = f"http://127.0.0.1:{port}/"
    proc = subprocess.Popen(argv, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    screenshot = project / "screenshots" / "browser_visual_evidence.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    started = _now()
    status = EvidenceStatus.FAIL.value
    dom_assertions: list[dict[str, Any]] = []
    network_requests: list[str] = []
    browser_info: dict[str, str] = {"engine": "chromium", "version": "unknown"}
    error = ""
    try:
        if not _wait(url):
            error = "runtime url did not become ready"
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch()
                browser_info["version"] = browser.version
                page = browser.new_page(viewport={"width": 960, "height": 640})
                page.on("request", lambda request: network_requests.append(request.url))
                page.goto(url, wait_until="networkidle")
                body_text = page.locator("body").inner_text(timeout=3000)
                dom_assertions.append({"selector": "body", "contains_text": bool(body_text.strip()), "text_hash": _sha256_text(body_text)})
                page.screenshot(path=str(screenshot), full_page=True)
                browser.close()
                status = EvidenceStatus.PASS.value if body_text.strip() and screenshot.exists() else EvidenceStatus.FAIL.value
    except Exception as exc:
        error = str(exc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    finished = _now()
    evidence: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": str(runtime_doc.get("candidate_id") or project.name),
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "created_at": finished,
        "status": status,
        "artifact_hash": "",
        "customer_runtime_ref": str(runtime_path),
        "customer_runtime_hash": _sha256_file(runtime_path) if runtime_path.exists() else "",
        "browser": browser_info,
        "url": url,
        "actions": [{"type": "goto", "url": url}],
        "dom_assertions": dom_assertions,
        "network_requests": network_requests,
        "screenshot_path": str(screenshot),
        "screenshot_hash": _sha256_file(screenshot) if screenshot.exists() else "",
        "viewport": {"width": 960, "height": 640},
        "started_at": started,
        "finished_at": finished,
        "formal_evidence": True,
        "error": error,
    }
    evidence["artifact_hash"] = _sha256_text(json.dumps({**evidence, "artifact_hash": ""}, sort_keys=True, ensure_ascii=False))
    path = project / "visual_evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["result_file"] = str(path)
    return evidence


def inspect(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    path = project / "visual_evidence.json"
    if not path.exists():
        return {"status": "FAIL", "missing": ["visual_evidence.json"]}
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"status": "FAIL", "missing": ["valid_json"], "error": str(exc)}
    missing: list[str] = []
    if doc.get("kind") != KIND:
        missing.append("kind")
    if doc.get("schema_version") != SCHEMA_VERSION:
        missing.append("schema_version")
    if doc.get("formal_evidence") is not True:
        missing.append("formal_evidence")
    if not doc.get("dom_assertions"):
        missing.append("dom_assertions")
    screenshot = pathlib.Path(str(doc.get("screenshot_path", "")))
    if not screenshot.exists() or _sha256_file(screenshot) != doc.get("screenshot_hash"):
        missing.append("screenshot_hash")
    if doc.get("status") != EvidenceStatus.PASS.value:
        missing.append("status")
    return {"status": "PASS" if not missing else "FAIL", "missing": missing, "details": doc}
