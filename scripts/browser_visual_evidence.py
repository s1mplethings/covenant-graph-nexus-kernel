from __future__ import annotations

import json
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from contracts.status import EvidenceStatus
from contracts.visual_evidence import KIND, PRODUCER, SCHEMA_VERSION
from scripts import canonical_evidence_hash, customer_runtime_runner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return canonical_evidence_hash.sha256_bytes(data)


def _sha256_file(path: pathlib.Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _wait(url: str, seconds: float = 5.0) -> bool:
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:  # noqa: S310 - localhost live runtime probe
                return int(response.status) == 200
        except Exception:
            time.sleep(0.1)
    return False


def capture_receipt_hash(receipt: dict[str, Any]) -> str:
    return canonical_evidence_hash.canonical_json_hash(receipt, ())


def capture_live_runtime(
    live_runtime: customer_runtime_runner.LiveRuntimeHandle,
    *,
    screenshot_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    if isinstance(live_runtime, dict):
        raise TypeError("capture_live_runtime requires LiveRuntimeHandle")
    required_attrs = (
        "run_id",
        "candidate_id",
        "candidate_hash",
        "commit_sha",
        "source_project_root",
        "execution_root",
        "pid",
        "port",
        "url",
        "process",
        "startup_argv",
        "started_at",
        "source_candidate_hash",
        "copied_candidate_hash",
        "copied_manifest_hash",
        "is_alive",
        "execution_root_exists",
        "candidate_hash_verified",
        "is_isolated",
    )
    if any(not hasattr(live_runtime, attr) for attr in required_attrs):
        raise TypeError("capture_live_runtime requires LiveRuntimeHandle")
    started = _now()
    screenshot = pathlib.Path(screenshot_path) if screenshot_path else live_runtime.source_project_root / "screenshots" / "browser_visual_evidence.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    runtime_alive_before = live_runtime.is_alive()
    execution_root_exists_before = live_runtime.execution_root_exists()
    network_requests: list[str] = []
    dom_assertions: list[dict[str, Any]] = []
    browser_info: dict[str, str] = {"engine": "chromium", "version": "unknown"}
    error = ""
    status = EvidenceStatus.FAIL.value
    if not runtime_alive_before:
        error = "runtime_not_live"
    elif not execution_root_exists_before:
        error = "execution_root_missing"
    elif not live_runtime.candidate_hash_verified() or not live_runtime.is_isolated():
        error = "runtime_handle_invalid"
    elif not _wait(live_runtime.url):
        error = "runtime_url_not_healthy"
    else:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch()
                browser_info["version"] = browser.version
                page = browser.new_page(viewport={"width": 960, "height": 640})
                page.on("request", lambda request: network_requests.append(request.url))
                page.goto(live_runtime.url, wait_until="networkidle")
                body_text = page.locator("body").inner_text(timeout=3000)
                dom_assertions.append({"selector": "body", "contains_text": bool(body_text.strip()), "text_hash": _sha256_text(body_text)})
                page.screenshot(path=str(screenshot), full_page=True)
                browser.close()
                status = EvidenceStatus.PASS.value if body_text.strip() and screenshot.exists() else EvidenceStatus.FAIL.value
                if status != EvidenceStatus.PASS.value:
                    error = "dom_or_screenshot_missing"
        except Exception as exc:
            error = str(exc)
            status = EvidenceStatus.BLOCKED_ENVIRONMENT.value if "Executable doesn't exist" in error else EvidenceStatus.FAIL.value
    runtime_alive_after = live_runtime.is_alive()
    if status == EvidenceStatus.PASS.value and not runtime_alive_after:
        status = EvidenceStatus.FAIL.value
        error = "runtime_not_live_after_capture"
    captured_at = _now()
    receipt: dict[str, Any] = {
        "capture_id": f"browser-capture-{uuid.uuid4().hex}",
        "runtime_pid": live_runtime.pid,
        "runtime_url": live_runtime.url,
        "runtime_port": live_runtime.port,
        "runtime_execution_root": str(live_runtime.execution_root),
        "runtime_alive_before_capture": runtime_alive_before,
        "runtime_alive_after_capture": runtime_alive_after,
        "screenshot_path": str(screenshot),
        "screenshot_hash": _sha256_file(screenshot) if screenshot.exists() else "",
        "dom_assertions": dom_assertions,
        "dom_assertion_hash": canonical_evidence_hash.canonical_json_hash({"dom_assertions": dom_assertions}, ()),
        "network_requests": network_requests,
        "network_origin": _origin(live_runtime.url),
        "browser_engine": browser_info["engine"],
        "browser_version": browser_info["version"],
        "started_at": started,
        "captured_at": captured_at,
        "capture_status": status,
        "error": error,
    }
    return receipt


def run(project_dir: str | pathlib.Path, *, runtime_ref: str | pathlib.Path | None = None) -> dict[str, Any]:
    return {
        "status": EvidenceStatus.NOT_EVALUATED.value,
        "reason": "live_runtime_required",
        "runtime_ref": str(runtime_ref or pathlib.Path(project_dir) / "customer_runtime.json"),
    }


def finalize_evidence(
    project_dir: str | pathlib.Path,
    *,
    runtime_result: dict[str, Any],
    capture_receipt: dict[str, Any] | None,
    required: bool = True,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    if not required:
        return {"status": EvidenceStatus.NOT_EVALUATED.value, "reason": "not_required", "not_required": True}
    receipt = capture_receipt if isinstance(capture_receipt, dict) else {}
    runtime_ref = pathlib.Path(str(runtime_result.get("result_file") or project / "customer_runtime.json"))
    runtime_hash = _sha256_file(runtime_ref) if runtime_ref.exists() else ""
    status = str(receipt.get("capture_status") or EvidenceStatus.FAIL.value)
    screenshot = pathlib.Path(str(receipt.get("screenshot_path") or project / "screenshots" / "browser_visual_evidence.png"))
    evidence: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": str(runtime_result.get("run_id") or ""),
        "candidate_id": str(runtime_result.get("candidate_id") or ""),
        "candidate_hash": str(runtime_result.get("candidate_hash") or ""),
        "candidate_hash_observed": canonical_evidence_hash.candidate_source_hash(project),
        "candidate_hash_verified": canonical_evidence_hash.candidate_source_hash(project) == str(runtime_result.get("candidate_hash") or ""),
        "commit_sha": str(runtime_result.get("commit_sha") or ""),
        "producer": PRODUCER,
        "created_at": _now(),
        "status": status,
        "artifact_hash": "",
        "runtime_pid": int(receipt.get("runtime_pid") or 0),
        "runtime_url": str(receipt.get("runtime_url") or ""),
        "runtime_port": int(receipt.get("runtime_port") or 0),
        "runtime_execution_root": str(receipt.get("runtime_execution_root") or ""),
        "browser_capture_id": str(receipt.get("capture_id") or ""),
        "browser_capture_hash": capture_receipt_hash(receipt) if receipt else "",
        "runtime_alive_before_capture": bool(receipt.get("runtime_alive_before_capture") or False),
        "runtime_alive_after_capture": bool(receipt.get("runtime_alive_after_capture") or False),
        "customer_runtime_ref": str(runtime_ref),
        "customer_runtime_hash": runtime_hash,
        "screenshot_path": str(screenshot),
        "screenshot_hash": str(receipt.get("screenshot_hash") or ""),
        "dom_assertions": receipt.get("dom_assertions", []) if isinstance(receipt.get("dom_assertions"), list) else [],
        "network_requests": receipt.get("network_requests", []) if isinstance(receipt.get("network_requests"), list) else [],
        "network_origin": str(receipt.get("network_origin") or ""),
        "actions": [{"type": "goto", "url": str(receipt.get("runtime_url") or "")}],
        "browser": {"engine": str(receipt.get("browser_engine") or "chromium"), "version": str(receipt.get("browser_version") or "unknown")},
        "viewport": {"width": 960, "height": 640},
        "capture_receipt": receipt,
        "capture_error": str(receipt.get("error") or ""),
        "formal_evidence": True,
    }
    evidence["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(evidence, ("artifact_hash",))
    path = project / "visual_evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["result_file"] = str(path)
    return evidence


def inspect(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
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
    expected_hash = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    if not doc.get("artifact_hash") or doc.get("artifact_hash") != expected_hash:
        missing.append("artifact_hash_mismatch")
    if doc.get("formal_evidence") is not True:
        missing.append("formal_evidence")
    if doc.get("status") != EvidenceStatus.PASS.value:
        missing.append("status")
    if not doc.get("dom_assertions"):
        missing.append("dom_assertions")
    screenshot = pathlib.Path(str(doc.get("screenshot_path", "")))
    if not screenshot.is_file() or screenshot.is_symlink() or _sha256_file(screenshot) != doc.get("screenshot_hash"):
        missing.append("screenshot_hash")
    runtime_ref = pathlib.Path(str(doc.get("customer_runtime_ref", "")))
    runtime_doc: dict[str, Any] = {}
    if not runtime_ref.is_file() or runtime_ref.is_symlink():
        missing.append("customer_runtime_ref")
    else:
        if _sha256_file(runtime_ref) != doc.get("customer_runtime_hash"):
            missing.append("customer_runtime_hash")
        runtime_inspection = customer_runtime_runner.inspect(runtime_ref)
        runtime_doc = runtime_inspection.get("details", {}) if isinstance(runtime_inspection.get("details"), dict) else {}
        if runtime_inspection.get("status") != "PASS":
            missing.append("customer_runtime_ref_inspect")
    receipt = doc.get("capture_receipt", {})
    if not isinstance(receipt, dict):
        receipt = {}
        missing.append("capture_receipt")
    if doc.get("browser_capture_hash") != capture_receipt_hash(receipt):
        missing.append("browser_capture_hash")
    if doc.get("browser_capture_id") != runtime_doc.get("browser_capture_id") or doc.get("browser_capture_id") != receipt.get("capture_id"):
        missing.append("browser_capture_id")
    if int(doc.get("runtime_pid", 0) or 0) != int(runtime_doc.get("pid", 0) or 0):
        missing.append("runtime_pid")
    if doc.get("runtime_url") != runtime_doc.get("url"):
        missing.append("runtime_url")
    if int(doc.get("runtime_port", 0) or 0) != int(runtime_doc.get("port", 0) or 0):
        missing.append("runtime_port")
    if doc.get("runtime_execution_root") != runtime_doc.get("execution_root"):
        missing.append("runtime_execution_root")
    if doc.get("browser_capture_hash") != runtime_doc.get("browser_capture_hash"):
        missing.append("browser_capture_hash")
    if doc.get("runtime_alive_before_capture") is not True or receipt.get("runtime_alive_before_capture") is not True:
        missing.append("runtime_alive_before_capture")
    if doc.get("runtime_alive_after_capture") is not True or receipt.get("runtime_alive_after_capture") is not True:
        missing.append("runtime_alive_after_capture")
    if doc.get("run_id") != runtime_doc.get("run_id"):
        missing.append("run_id")
    if doc.get("candidate_id") != runtime_doc.get("candidate_id"):
        missing.append("candidate_id")
    if doc.get("candidate_hash") != runtime_doc.get("candidate_hash"):
        missing.append("candidate_hash")
    if doc.get("commit_sha") != runtime_doc.get("commit_sha"):
        missing.append("commit_sha")
    current_candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    if doc.get("candidate_hash") != current_candidate_hash:
        missing.append("candidate_hash_current")
    if doc.get("candidate_hash_observed") and doc.get("candidate_hash_observed") != doc.get("candidate_hash"):
        missing.append("candidate_hash_observed")
    if doc.get("candidate_hash_verified") is not True:
        missing.append("candidate_hash_verified")
    expected_origin = _origin(str(doc.get("runtime_url") or ""))
    if doc.get("network_origin") != expected_origin:
        missing.append("network_origin")
    requests = doc.get("network_requests", []) if isinstance(doc.get("network_requests"), list) else []
    if not requests or any(_origin(str(request)) != expected_origin for request in requests):
        missing.append("network_requests")
    return {"status": "PASS" if not missing else "FAIL", "missing": sorted(set(missing)), "details": doc}
