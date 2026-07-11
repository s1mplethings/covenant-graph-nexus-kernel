#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import check_connectivity
import provider_api_smoke
import telegram_live_bridge as bridge


VN_REQUEST = "帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的\n补充：\n本地模型，桌面界面，文件导出"
START_TEXT = "开始生成"
FORBIDDEN_TOPIC_TERMS = ("CSGO", "csgo", "CS2", "cs2", "demo 鉴挂", "鉴挂", "视角异常", "命中事件", "风险评分")
FORBIDDEN_PUBLIC_INTERNALS = ("TLS", "SSLError", "provider", "backend", "internal", "pipeline", "manifest", "runner", "后台")
RETRYABLE_MARKERS = ("SSLError", "SSLV3_ALERT_BAD_RECORD_MAC", "timeout", "timed out", "502", "503", "504", "connection reset", "connection aborted", "empty response")


class CaptureTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.photos: list[dict[str, str]] = []
        self.documents: list[dict[str, str]] = []
        self.videos: list[dict[str, str]] = []
        self.actions: list[dict[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append({"chat_id": str(chat_id), "text": str(text)})
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append({"chat_id": str(chat_id), "action": str(action)})

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append({"chat_id": str(chat_id), "path": str(path), "caption": str(caption)})
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append({"chat_id": str(chat_id), "path": str(path), "caption": str(caption)})
        return True

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append({"chat_id": str(chat_id), "path": str(path), "caption": str(caption)})
        return True


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self._started = False
        self._finished = False

    def start(self) -> None:
        self._started = True
        self.target(*self.args, **self.kwargs)
        self._finished = True

    def join(self, timeout: float | None = None) -> None:
        del timeout
        return None

    def is_alive(self) -> bool:
        return self._started and not self._finished


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            value = {"raw": line}
        if isinstance(value, dict):
            events.append(value)
    return events


def public_gate_from_session(session: dict[str, Any]) -> dict[str, Any]:
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    gate = generation.get("delivery_gate")
    return gate if isinstance(gate, dict) else {}


def artifact_audit(project_dir: pathlib.Path, sent: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    files = [path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file()] if project.exists() else []
    lower_files = [item.lower() for item in files]
    sent_document_paths = [pathlib.Path(item["path"]).name for item in sent.get("documents", [])]
    return {
        "project_dir_exists": project.exists(),
        "entrypoint": any(item in {"app.py", "main.py"} for item in lower_files),
        "dependency_file": any(item in {"requirements.txt", "pyproject.toml"} for item in lower_files),
        "src": any(item.startswith(("src/", "ui/", "models/", "data/")) for item in lower_files),
        "tests": any(item.startswith("tests/") for item in lower_files),
        "test_report": "test_report.md" in lower_files,
        "ui_screenshot": any("screenshot" in item and item.endswith((".png", ".jpg", ".jpeg", ".webp")) for item in lower_files),
        "background_image": any("background" in item and item.endswith((".png", ".jpg", ".jpeg", ".webp")) for item in lower_files),
        "sprite_image": any(("sprite" in item or "立绘" in item or "character" in item) and item.endswith((".png", ".jpg", ".jpeg", ".webp")) for item in lower_files),
        "zip": "final_project_bundle.zip" in lower_files or "final_project_bundle.zip" in sent_document_paths,
        "files": files[:300],
    }


def public_text_contains_any(messages: list[dict[str, str]], needles: tuple[str, ...]) -> bool:
    text = "\n".join(item.get("text", "") for item in messages)
    return any(needle in text for needle in needles)


def retry_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        blob = json.dumps(event, ensure_ascii=False)
        if event.get("kind") == "provider_retry" or any(marker.lower() in blob.lower() for marker in RETRYABLE_MARKERS):
            out.append(event)
    return out


def strip_secret_fields(doc: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(doc)
    cleaned.pop("api_key_mask", None)
    return cleaned


def run(args: argparse.Namespace) -> dict[str, Any]:
    os.environ.setdefault("CGKN_OPENAI_BASE_URL", "https://api.gptsapi.net/v1")
    creds = check_connectivity._resolve_api_credentials()
    if not str(creds.get("api_key", "")).strip():
        return {
            "ok": False,
            "status": "missing_api_key",
            "error": "CGKN_OPENAI_API_KEY is required for the real provider e2e.",
            "api_key_source": creds.get("api_key_source", ""),
            "base_url": creds.get("base_url", ""),
        }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = pathlib.Path(args.output_dir or ROOT / "examples" / "test_results" / f"vn_real_provider_e2e_{run_id}").resolve()
    if output_root.exists() and args.clean:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    session_dir = output_root / "sessions"
    log_dir = output_root / "logs"
    chat_id = args.chat_id
    client = CaptureTelegramClient()

    smoke = provider_api_smoke.run_smoke(args.model, args.timeout, args.smoke_attempts)
    smoke = strip_secret_fields(smoke)

    original_thread = bridge.threading.Thread
    bridge.threading.Thread = InlineThread
    try:
        bridge.handle_text(client, chat_id, VN_REQUEST, session_dir, log_dir, args.model, args.timeout)
        first_session = bridge.load_session(session_dir, chat_id)
        first_status = str(first_session.get("generation", {}).get("status", ""))
        first_messages = list(client.messages)

        bridge.handle_text(client, chat_id, START_TEXT, session_dir, log_dir, args.model, args.timeout)
    finally:
        bridge.threading.Thread = original_thread

    session = bridge.load_session(session_dir, chat_id)
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    project_dir = pathlib.Path(str(generation.get("project_dir") or (log_dir / "agent_projects" / bridge.safe_id(chat_id))))
    sent = {
        "messages": client.messages,
        "photos": client.photos,
        "documents": client.documents,
        "videos": client.videos,
        "actions": client.actions,
    }
    events = read_jsonl(bridge.agent_session_path(session_dir, chat_id))
    gate = public_gate_from_session(session)
    audit = artifact_audit(project_dir, sent)
    retries = retry_events(events)
    public_internal_leak = public_text_contains_any(client.messages, FORBIDDEN_PUBLIC_INTERNALS)
    topic_leak = public_text_contains_any(first_messages, FORBIDDEN_TOPIC_TERMS)
    attachment_ext_ok = all(
        pathlib.Path(item["path"]).suffix.lower().lstrip(".") in {"png", "jpg", "jpeg", "webp", "gif", "mp4", "webm", "zip"}
        for item in client.photos + client.documents + client.videos
    )
    success_ready = (
        str(generation.get("status", "")).lower() in {"ready", "ready_with_warnings", "delivered"}
        and bool(gate.get("delivery_allowed", True))
        and all(bool(audit[key]) for key in ("entrypoint", "dependency_file", "src", "tests", "test_report", "ui_screenshot", "background_image", "sprite_image", "zip"))
        and attachment_ext_ok
        and not topic_leak
        and not public_internal_leak
    )
    retryable_rework_verified = (
        str(generation.get("status", "")).lower() == "rework_blocked"
        and not gate.get("delivery_allowed", False)
        and not client.photos
        and not client.documents
        and not client.videos
        and not public_internal_leak
        and bool(retries)
    )

    package = {
        "kind": "VnRealProviderE2ELogPackage",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": success_ready,
        "status": "PASS" if success_ready else ("REWORK_VERIFIED_NON_PASS" if retryable_rework_verified else "FAIL"),
        "model": args.model,
        "endpoint": check_connectivity._openai_compatible_endpoint(str(creds.get("base_url", "")), model=args.model),
        "api_key_source": creds.get("api_key_source", ""),
        "smoke": smoke,
        "first_message": {
            "generation_status": first_status,
            "waiting_confirmation": first_status == "waiting_confirmation",
            "topic_leak": topic_leak,
            "messages": first_messages,
        },
        "session_path": str(bridge.session_path(session_dir, chat_id)),
        "agent_session_path": str(bridge.agent_session_path(session_dir, chat_id)),
        "project_dir": str(project_dir),
        "generation": generation,
        "public_delivery_gate": gate,
        "build_integrity_audit": generation.get("build_integrity_audit", {}),
        "qa_integrity_audit": generation.get("qa_integrity_audit", {}),
        "artifact_audit": audit,
        "provider_retry_events": retries,
        "sent": {
            "photos": len(client.photos),
            "documents": len(client.documents),
            "videos": len(client.videos),
            "records": sent,
            "attachment_ext_ok": attachment_ext_ok,
        },
        "public_internal_leak": public_internal_leak,
        "retryable_rework_verified": retryable_rework_verified,
        "notes": [
            "This script does not write API key contents.",
            "TLS/retry exhaustion is intentionally reported as non-PASS even when REWORK safety is verified.",
        ],
    }
    log_path = output_root / "vn_real_provider_e2e_log_package.json"
    log_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    package["log_package_path"] = str(log_path)
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description="Real Telegram VN e2e through configured OpenAI-compatible provider.")
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--smoke-attempts", type=int, default=3)
    parser.add_argument("--chat-id", default="vn-real-provider-e2e")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    package = run(args)
    print(json.dumps(package, ensure_ascii=False, indent=2))
    if package.get("status") == "missing_api_key":
        return 2
    return 0 if package.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
