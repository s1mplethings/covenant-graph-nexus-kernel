#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import agent_conversation_loop
import product_studio_reply
import project_memory_md

DEFAULT_SESSION_DIR = ROOT / "examples" / "test_results" / "telegram_live_sessions"
DEFAULT_LOG_DIR = ROOT / "examples" / "test_results" / "telegram_live_logs"
DEFAULT_MEMORY_DIR = ROOT / "examples" / "project_memory"
DEFAULT_UPLOAD_DIR = ROOT / "examples" / "test_results" / "telegram_live_uploads"
POLICY_PATH = ROOT / "config" / "customer_agent_policy.md"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
GENERATION_TOTAL_TIMEOUT_SECONDS = 900

DEFAULT_CUSTOMER_AGENT_POLICY = """# Customer Agent Policy

The assistant behaves like a product design and engineering partner, not a form-based customer support script.
It is the front-office interface for the CGNK project generation and delivery workflow.

- Represent the CGNK workflow that can clarify requirements, maintain project memory, generate projects, run checks, and deliver preview media.
- Understand the user's goal first, then propose a first-version product and technical plan.
- Infer reasonable defaults for optional fields instead of asking the user to fill every field.
- Ask only questions that block generation.
- Accept uploaded images, documents, videos, audio, and data files as project input when Telegram provides them.
- When enough information exists, proceed naturally; do not require a fixed command phrase.
- Delivery messages should present product capabilities, test status, preview artifacts, and next-step suggestions.
- Never expose API stack traces or internal transport errors to the user.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_customer_agent_policy() -> str:
    if POLICY_PATH.exists():
        try:
            text = POLICY_PATH.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text[:12000]
        except Exception:
            pass
    return DEFAULT_CUSTOMER_AGENT_POLICY


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + "\n")


def read_json(path: pathlib.Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return doc if isinstance(doc, dict) else default


def safe_id(raw: Any) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:120] or "telegram-session"


def safe_file_name(raw: Any, fallback: str) -> str:
    value = pathlib.Path(str(raw or "")).name
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip(".-")
    return value[:160] or fallback


def unique_path(path: pathlib.Path) -> pathlib.Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


def extension_for_mime(mime_type: str, default: str = ".bin") -> str:
    mime = mime_type.lower().strip()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    }.get(mime, default)


def resolve_token(explicit: str = "") -> str:
    token = explicit.strip() if explicit else ""
    if token:
        return token
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "CGNK_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_TOKEN",
        "BOT_TOKEN",
    ):
        token = str(os.environ.get(name, "")).strip()
        if token:
            return token
    raise RuntimeError("missing Telegram bot token; set TELEGRAM_BOT_TOKEN")


class TelegramClient:
    def __init__(self, token: str, timeout: int) -> None:
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"
        self.timeout = timeout
        try:
            import requests

            self.session = requests.Session()
        except Exception:
            self.session = None

    def redact_for_log(self, text: Any) -> str:
        value = str(text)
        if self.token:
            value = value.replace(self.token, "<telegram-token>")
        return re.sub(r"/bot[^/\s]+", "/bot<telegram-token>", value)

    def call(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                if self.session is not None:
                    resp = self.session.post(f"{self.base}/{method}", data=payload or {}, timeout=self.timeout)
                    doc = resp.json()
                else:
                    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{self.base}/{method}",
                        data=data,
                        method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        doc = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
        else:
            raise RuntimeError(f"Telegram {method} transport failed: {self.redact_for_log(last_exc)}")
        if not isinstance(doc, dict) or not doc.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {doc}")
        return doc

    def send_message(self, chat_id: int | str, text: str) -> bool:
        last_error = ""
        for attempt in range(3):
            try:
                self.call(
                    "sendMessage",
                    {
                        "chat_id": str(chat_id),
                        "text": text[:3900],
                        "disable_web_page_preview": "true",
                    },
                )
                return True
            except Exception as exc:
                last_error = str(exc)
                time.sleep(1.5 * (attempt + 1))
        print(f"telegram send_message failed chat_id={chat_id}: {last_error}", flush=True)
        return False

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        try:
            self.call("sendChatAction", {"chat_id": str(chat_id), "action": action})
        except Exception:
            pass

    def get_file_info(self, file_id: str) -> dict[str, Any]:
        doc = self.call("getFile", {"file_id": file_id})
        result = doc.get("result", {})
        return result if isinstance(result, dict) else {}

    def download_file(self, file_path: str, target: pathlib.Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        quoted = urllib.parse.quote(file_path, safe="/")
        url = f"{self.file_base}/{quoted}"
        tmp = target.with_suffix(target.suffix + ".tmp")
        if self.session is not None:
            with self.session.get(url, stream=True, timeout=max(self.timeout, 120)) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
        else:
            with urllib.request.urlopen(url, timeout=max(self.timeout, 120)) as resp, tmp.open("wb") as fh:
                shutil.copyfileobj(resp, fh)
        tmp.replace(target)

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if not path.exists() or not path.is_file():
            return False
        boundary = "----CGNKTelegramBoundary"
        fields = {"chat_id": str(chat_id), "caption": caption[:900]}
        suffix = path.suffix.lower()
        content_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"{self.base}/sendPhoto",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        for attempt in range(3):
            try:
                if self.session is not None:
                    with path.open("rb") as fh:
                        resp = self.session.post(
                            f"{self.base}/sendPhoto",
                            data=fields,
                            files={"photo": (path.name, fh, content_type)},
                            timeout=self.timeout,
                        )
                    doc = resp.json()
                else:
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        doc = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except Exception:
                if attempt == 2:
                    return False
                time.sleep(min(8.0, 2.0 * (attempt + 1)))
        return bool(isinstance(doc, dict) and doc.get("ok"))

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if not path.exists() or not path.is_file():
            return False
        fields = {"chat_id": str(chat_id), "caption": caption[:900]}
        content_type = "application/octet-stream"
        doc: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                if self.session is not None:
                    with path.open("rb") as fh:
                        resp = self.session.post(
                            f"{self.base}/sendDocument",
                            data=fields,
                            files={"document": (path.name, fh, content_type)},
                            timeout=max(self.timeout, 120),
                        )
                    doc = resp.json()
                else:
                    boundary = "----CGNKTelegramBoundary"
                    body = bytearray()
                    for key, value in fields.items():
                        body.extend(f"--{boundary}\r\n".encode())
                        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                        body.extend(str(value).encode("utf-8"))
                        body.extend(b"\r\n")
                    body.extend(f"--{boundary}\r\n".encode())
                    body.extend(
                        (
                            f'Content-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
                            f"Content-Type: {content_type}\r\n\r\n"
                        ).encode()
                    )
                    body.extend(path.read_bytes())
                    body.extend(b"\r\n")
                    body.extend(f"--{boundary}--\r\n".encode())
                    req = urllib.request.Request(
                        f"{self.base}/sendDocument",
                        data=bytes(body),
                        method="POST",
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    )
                    with urllib.request.urlopen(req, timeout=max(self.timeout, 120)) as resp:
                        doc = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except Exception:
                if attempt == 2:
                    return False
                time.sleep(min(8.0, 2.0 * (attempt + 1)))
        return bool(isinstance(doc, dict) and doc.get("ok"))

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if not path.exists() or not path.is_file():
            return False
        boundary = "----CGNKTelegramBoundary"
        fields = {"chat_id": str(chat_id), "caption": caption[:900], "supports_streaming": "true"}
        suffix = path.suffix.lower()
        content_type = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
        }.get(suffix, "application/octet-stream")
        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="video"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"{self.base}/sendVideo",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        for attempt in range(3):
            try:
                if self.session is not None:
                    with path.open("rb") as fh:
                        resp = self.session.post(
                            f"{self.base}/sendVideo",
                            data=fields,
                            files={"video": (path.name, fh, content_type)},
                            timeout=max(self.timeout, 120),
                        )
                    doc = resp.json()
                else:
                    with urllib.request.urlopen(req, timeout=max(self.timeout, 120)) as resp:
                        doc = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except Exception:
                if attempt == 2:
                    return False
                time.sleep(min(12.0, 3.0 * (attempt + 1)))
        return bool(isinstance(doc, dict) and doc.get("ok"))

    def get_updates(self, offset: int, poll_timeout: int) -> list[dict[str, Any]]:
        doc = self.call("getUpdates", {"offset": str(offset), "timeout": str(poll_timeout)})
        result = doc.get("result", [])
        return result if isinstance(result, list) else []


def default_session(chat_id: int | str) -> dict[str, Any]:
    return {
        "kind": "TelegramOnlyCustomerSession",
        "chat_id": str(chat_id),
        "created_at": now(),
        "updated_at": now(),
        "messages": [],
        "attachments": [],
        "memory_events": [],
        "whiteboard_versions": [],
        "whiteboard": {
            "project_summary": "",
            "known_facts": [],
            "open_questions": [],
            "default_assumptions": [],
            "first_version_plan": [],
            "blocking_questions": [],
            "user_rules": [],
            "acceptance_criteria": [],
            "change_requests": [],
            "decision_log": [],
            "delivery_requirements": [],
            "ready_to_generate": False,
        },
        "generation": {"status": "idle"},
        "active_run": None,
        "pending_decision": None,
        "intake_tickets": [],
        "backend_memos": [],
        "backend_controls": [],
    }


def session_path(session_dir: pathlib.Path, chat_id: int | str) -> pathlib.Path:
    return session_dir / f"{safe_id(chat_id)}.json"


def agent_session_path(session_dir: pathlib.Path, chat_id: int | str) -> pathlib.Path:
    return session_dir / safe_id(chat_id) / "agent_session.jsonl"


def append_agent_session_event(session_dir: pathlib.Path, chat_id: int | str, event: dict[str, Any]) -> pathlib.Path:
    path = agent_session_path(session_dir, chat_id)
    doc = {"kind": "event", "chat_id": str(chat_id), **event}
    doc.setdefault("created_at", now())
    append_jsonl(path, doc)
    return path


def load_session(session_dir: pathlib.Path, chat_id: int | str) -> dict[str, Any]:
    return read_json(session_path(session_dir, chat_id), default_session(chat_id))


def save_session(session_dir: pathlib.Path, session: dict[str, Any]) -> None:
    session["updated_at"] = now()
    try:
        session["project_memory"] = project_memory_md.write_project_memory(session, DEFAULT_MEMORY_DIR)
    except Exception as exc:
        print(f"project memory update failed: {exc}", flush=True)
    write_json(session_path(session_dir, session.get("chat_id", "")), session)


def attachment_kind_label(kind: str) -> str:
    return {
        "image": "图片/参考图",
        "document": "文档资料",
        "video": "视频素材",
        "audio": "音频素材",
        "animation": "动图/动画素材",
    }.get(kind, "用户上传资料")


def summarize_message_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    caption = str(message.get("caption", "")).strip()
    specs: list[dict[str, Any]] = []
    photos = message.get("photo", [])
    if isinstance(photos, list) and photos:
        candidates = [item for item in photos if isinstance(item, dict) and item.get("file_id")]
        if candidates:
            photo = max(candidates, key=lambda item: int(item.get("file_size") or 0))
            file_unique_id = str(photo.get("file_unique_id", "")).strip()
            specs.append(
                {
                    "type": "image",
                    "telegram_field": "photo",
                    "file_id": str(photo.get("file_id", "")),
                    "file_unique_id": file_unique_id,
                    "file_name": f"photo_{file_unique_id or int(time.time())}.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": int(photo.get("file_size") or 0),
                    "caption": caption,
                }
            )
    for field, kind in (
        ("document", "document"),
        ("video", "video"),
        ("animation", "animation"),
        ("audio", "audio"),
        ("voice", "audio"),
    ):
        item = message.get(field)
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        mime_type = str(item.get("mime_type", "")).strip()
        fallback_name = f"{field}_{item.get('file_unique_id') or int(time.time())}{extension_for_mime(mime_type)}"
        specs.append(
            {
                "type": kind,
                "telegram_field": field,
                "file_id": str(item.get("file_id", "")),
                "file_unique_id": str(item.get("file_unique_id", "")).strip(),
                "file_name": str(item.get("file_name") or fallback_name),
                "mime_type": mime_type,
                "file_size": int(item.get("file_size") or 0),
                "duration": item.get("duration"),
                "caption": caption,
            }
        )
    return specs


def download_message_attachments(
    client: TelegramClient,
    chat_id: int | str,
    message: dict[str, Any],
    upload_dir: pathlib.Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    specs = summarize_message_attachments(message)
    if not specs:
        return downloaded, skipped
    safe_chat = safe_id(chat_id)
    message_id = safe_id(message.get("message_id", "message"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = upload_dir / safe_chat
    for index, spec in enumerate(specs, start=1):
        file_size = int(spec.get("file_size") or 0)
        if file_size > MAX_UPLOAD_BYTES:
            skipped.append({**spec, "reason": "too_large", "max_bytes": MAX_UPLOAD_BYTES})
            continue
        file_id = str(spec.get("file_id", "")).strip()
        if not file_id:
            skipped.append({**spec, "reason": "missing_file_id"})
            continue
        info = client.get_file_info(file_id)
        remote_path = str(info.get("file_path", "")).strip()
        if not remote_path:
            skipped.append({**spec, "reason": "missing_file_path"})
            continue
        remote_suffix = pathlib.Path(remote_path).suffix
        mime_suffix = extension_for_mime(str(spec.get("mime_type", "")), "")
        raw_name = str(spec.get("file_name") or f"{spec.get('telegram_field', 'upload')}{remote_suffix or mime_suffix or '.bin'}")
        safe_name = safe_file_name(raw_name, f"upload_{index}{remote_suffix or mime_suffix or '.bin'}")
        if not pathlib.Path(safe_name).suffix and (remote_suffix or mime_suffix):
            safe_name += remote_suffix or mime_suffix
        target = unique_path(target_dir / f"{stamp}_{message_id}_{index}_{safe_name}")
        client.download_file(remote_path, target)
        downloaded.append(
            {
                "type": spec.get("type", "file"),
                "telegram_field": spec.get("telegram_field", ""),
                "file_unique_id": spec.get("file_unique_id", ""),
                "file_name": safe_name,
                "mime_type": spec.get("mime_type", ""),
                "file_size": target.stat().st_size if target.exists() else file_size,
                "caption": spec.get("caption", ""),
                "local_path": str(target),
                "message_id": message.get("message_id"),
                "created_at": now(),
            }
        )
    return downloaded, skipped


def recent_attachments(session: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    values = session.get("attachments", [])
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[-limit:]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "type": item.get("type", ""),
                "file_name": item.get("file_name", ""),
                "mime_type": item.get("mime_type", ""),
                "file_size": item.get("file_size", 0),
                "caption": item.get("caption", ""),
                "local_path": item.get("local_path", ""),
                "created_at": item.get("created_at", ""),
            }
        )
    return out


def attachment_requirement_lines(session: dict[str, Any], limit: int = 30) -> list[str]:
    lines: list[str] = []
    for item in recent_attachments(session, limit=limit):
        kind = attachment_kind_label(str(item.get("type", "")))
        name = str(item.get("file_name", "")).strip() or "未命名上传"
        path = str(item.get("local_path", "")).strip()
        mime = str(item.get("mime_type", "")).strip()
        caption = str(item.get("caption", "")).strip()
        detail = f"- {kind}: {name}"
        if mime:
            detail += f"; mime_type: {mime}"
        if path:
            detail += f"; local_path: {path}"
        if caption:
            detail += f"; caption: {caption[:300]}"
        lines.append(detail)
    return lines


def record_attachments_as_project_input(session: dict[str, Any], attachments: list[dict[str, Any]]) -> None:
    if not attachments:
        return
    stored = session.setdefault("attachments", [])
    if not isinstance(stored, list):
        stored = []
    stored.extend(attachments)
    session["attachments"] = stored[-120:]
    whiteboard = session.setdefault("whiteboard", {})
    if not isinstance(whiteboard, dict):
        whiteboard = {}
    fact_lines = []
    for item in attachments:
        kind = attachment_kind_label(str(item.get("type", "")))
        name = str(item.get("file_name", "")).strip() or "未命名上传"
        path = str(item.get("local_path", "")).strip()
        caption = str(item.get("caption", "")).strip()
        fact = f"用户上传了{kind}作为项目输入: {name}"
        if path:
            fact += f" ({path})"
        if caption:
            fact += f"; 说明: {caption[:240]}"
        fact_lines.append(fact)
    whiteboard["known_facts"] = unique_strings((whiteboard.get("known_facts", []) if isinstance(whiteboard.get("known_facts", []), list) else []) + fact_lines)
    whiteboard["decision_log"] = unique_strings(
        (whiteboard.get("decision_log", []) if isinstance(whiteboard.get("decision_log", []), list) else [])
        + ["已将用户上传文件保存为后端项目输入，后续方案、生成和修改应优先参考这些资料。"],
        limit=120,
    )
    session["whiteboard"] = whiteboard
    append_memory_event(
        session,
        "user_attachment_received",
        data={
            "attachments": recent_attachments({"attachments": attachments}, limit=len(attachments)),
            "count": len(attachments),
        },
    )


def attachment_user_text(attachments: list[dict[str, Any]], caption: str = "") -> str:
    caption = caption.strip()
    labels = [attachment_kind_label(str(item.get("type", ""))) for item in attachments]
    label_summary = "、".join(unique_strings(labels, limit=8)) or "资料"
    if caption:
        return f"用户上传了{label_summary}作为项目资料，并补充说明: {caption}"
    return f"用户上传了{label_summary}作为项目资料，请把这些资料纳入后端需求和后续生成。"


def inside_workspace(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def chat_history_targets(chat_id: int | str, session_dir: pathlib.Path, log_dir: pathlib.Path) -> list[pathlib.Path]:
    safe_chat = safe_id(chat_id)
    slug = f"telegram-live-{safe_chat}"
    project_slug = f"telegram_{slug}"
    targets = [
        session_path(session_dir, chat_id),
        log_dir / f"{slug}_generation_result.json",
        log_dir / f"{project_slug}_preview.png",
        ROOT / "generated" / project_slug,
        ROOT / "examples" / "runtime_runs" / project_slug,
        ROOT / "examples" / "test_results" / f"{project_slug}_composition.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_execution.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_requirement_blueprint.json",
        ROOT / "examples" / "test_results" / f"{project_slug}_context_prompt.json",
        DEFAULT_UPLOAD_DIR / safe_chat,
    ]
    current = read_json(session_path(session_dir, chat_id), {})
    memory = current.get("project_memory", {}) if isinstance(current, dict) else {}
    if isinstance(memory, dict):
        for key in ("project_memory_md", "project_memory_artifact"):
            raw = str(memory.get(key, "")).strip()
            if raw:
                targets.append(pathlib.Path(raw))
    return targets


def clear_chat_history(
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    *,
    include_outputs: bool,
    delete: bool,
) -> dict[str, Any]:
    archive_dir = ROOT / "generated" / "telegram_history_archives" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") / safe_id(chat_id)
    raw_targets = chat_history_targets(chat_id, session_dir, log_dir)
    if not include_outputs:
        raw_targets = [session_path(session_dir, chat_id)]
    unique = []
    seen: set[str] = set()
    for target in raw_targets:
        path = target.resolve()
        key = str(path).lower()
        if key not in seen and path.exists():
            seen.add(key)
            unique.append(path)
    cleared: list[str] = []
    skipped: list[str] = []
    for path in unique:
        if not inside_workspace(path):
            skipped.append(str(path))
            continue
        if delete:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        else:
            rel = path.relative_to(ROOT.resolve())
            target = archive_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        cleared.append(str(path))
    return {
        "mode": "delete" if delete else "archive",
        "include_outputs": include_outputs,
        "cleared": cleared,
        "skipped": skipped,
        "archive_dir": "" if delete or not cleared else str(archive_dir),
    }


def reset_summary_text(result: dict[str, Any]) -> str:
    cleared = len(result.get("cleared", []))
    skipped = len(result.get("skipped", []))
    mode = "永久删除" if result.get("mode") == "delete" else "归档"
    scope = "会话和生成历史" if result.get("include_outputs") else "当前会话"
    lines = [f"已{mode}{scope}，重新开始。", f"处理条目: {cleared}"]
    if skipped:
        lines.append(f"跳过非工作区路径: {skipped}")
    archive_dir = str(result.get("archive_dir", "")).strip()
    if archive_dir:
        lines.append(f"归档目录: {archive_dir}")
    return "\n".join(lines)


def append_memory_event(session: dict[str, Any], event_type: str, text: str = "", data: dict[str, Any] | None = None) -> None:
    events = session.setdefault("memory_events", [])
    if not isinstance(events, list):
        events = []
    event: dict[str, Any] = {"type": event_type, "created_at": now()}
    if text:
        event["text"] = text[:4000]
    if data:
        event["data"] = data
    events.append(event)
    session["memory_events"] = events[-250:]


def truth_ledger_path(session_dir: pathlib.Path, chat_id: int | str) -> pathlib.Path:
    return session_dir / f"{safe_id(chat_id)}.truth_ledger.jsonl"


def append_truth_ledger(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    stage: str,
    claim: str,
    *,
    status: str = "observed",
    evidence_ref: str = "",
    can_user_see: bool = False,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "kind": "TruthLedgerEntry",
        "created_at": now(),
        "chat_id": str(session.get("chat_id", "")),
        "stage": stage,
        "claim": claim,
        "status": status,
        "evidence_ref": evidence_ref,
        "can_user_see": bool(can_user_see),
        "data": data or {},
    }
    path = truth_ledger_path(session_dir, session.get("chat_id", ""))
    append_jsonl(path, entry)
    session["truth_ledger_path"] = str(path)
    append_memory_event(session, "truth_ledger_entry", data={k: entry[k] for k in ("stage", "claim", "status", "evidence_ref")})
    return entry


def read_truth_ledger(session_dir: pathlib.Path, chat_id: int | str) -> list[dict[str, Any]]:
    path = truth_ledger_path(session_dir, chat_id)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            entries.append(doc)
    return entries


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def delivery_evidence_state(entries: list[dict[str, Any]]) -> dict[str, Any]:
    required = {
        "package": False,
        "screenshot": False,
        "verify_report": False,
        "verify_passed": False,
    }
    refs: dict[str, str] = {}
    sent_record = False
    for entry in entries:
        status = str(entry.get("status", "")).lower()
        stage = str(entry.get("stage", "")).lower()
        data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
        artifact = str(data.get("artifact") or stage).lower()
        if status not in {"observed", "pass", "sent"}:
            continue
        if bool(data.get("verify_passed")) or stage == "verify_passed" or artifact == "verify_passed":
            required["verify_passed"] = True
            refs["verify_passed"] = str(entry.get("evidence_ref", ""))
        for key in required:
            if key in artifact or key in stage:
                required[key] = True
                refs[key] = str(entry.get("evidence_ref", ""))
        if stage == "delivery_attachment_sent" or artifact == "delivery_attachment_sent":
            sent_record = True
    ready = all(required.values())
    return {
        "delivery_ready": ready,
        "required": required,
        "missing": [key for key, present in required.items() if not present],
        "refs": refs,
        "sent_record": sent_record,
    }


def classify_customer_message(text: str, session: dict[str, Any]) -> dict[str, Any]:
    stripped = str(text or "").strip()
    compact = re.sub(r"[\s,.!?。！？~～]+", "", stripped.lower())
    generation_status = str(session.get("generation", {}).get("status", "idle")).lower()
    if stripped in {"/new", "/reset", "/restart", "/delete_history", "/help", "/status"}:
        intent = "status_query" if stripped == "/status" else "admin_command"
    elif is_smalltalk(stripped):
        intent = "greeting"
    elif compact in {"现在怎么样了", "怎么样了", "进度怎么样", "当前状态", "状态", "status", "howisitgoing", "有结果了吗", "好了没"}:
        intent = "status_query"
    elif compact in {"升级", "交给agent", "调用api", "用provider", "人工介入", "请求升级", "escalate"} or "升级" in compact:
        intent = "escalation_request"
    elif is_generate_command(stripped) or is_human_start_confirmation(stripped, session):
        intent = "generation_confirmation"
    elif generation_status in {"queued", "running"}:
        intent = "project_update"
    elif substantive_user_turn_count(session) == 0:
        intent = "new_project_request"
    else:
        intent = "project_update"
    return {"kind": "CustomerMessageClassification", "intent": intent, "text": stripped, "classified_at": now()}


def active_run(session: dict[str, Any]) -> dict[str, Any] | None:
    run = session.get("active_run")
    return run if isinstance(run, dict) else None


def create_active_run(session: dict[str, Any], ticket: dict[str, Any], text: str) -> dict[str, Any]:
    run = {
        "kind": "TelegramHumanFrontdeskRun",
        "id": f"run-{safe_id(session.get('chat_id', 'chat'))}-{len(session.get('intake_tickets', []))}",
        "ticket_id": str(ticket.get("id", "")),
        "status": "intake_open",
        "driver": "frontdesk_intake",
        "goal": text,
        "created_at": now(),
        "updated_at": now(),
        "local_retry_count": 0,
        "local_retry_exhausted": False,
    }
    session["active_run"] = run
    session["generation"] = {"status": "idle", "driver": "not_started", "generation_mode": "unstarted"}
    return run


def update_active_run_status(session: dict[str, Any], status: str, **fields: Any) -> dict[str, Any]:
    run = active_run(session) or {
        "kind": "TelegramHumanFrontdeskRun",
        "id": f"run-{safe_id(session.get('chat_id', 'chat'))}-manual",
        "created_at": now(),
        "driver": "frontdesk_intake",
    }
    run.update(fields)
    run["status"] = status
    run["updated_at"] = now()
    session["active_run"] = run
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    generation["status"] = status
    session["generation"] = generation
    return run


def mark_generation_retry(
    session: dict[str, Any],
    *,
    reason: str,
    max_retries: int = 2,
) -> bool:
    run = active_run(session) or {
        "kind": "TelegramHumanFrontdeskRun",
        "id": f"run-{safe_id(session.get('chat_id', 'chat'))}-manual",
        "created_at": now(),
    }
    retry_count = int(run.get("local_retry_count") or 0) + 1
    run["local_retry_count"] = retry_count
    run["last_retry_reason"] = reason
    run["updated_at"] = now()
    exhausted = retry_count >= max_retries
    run["local_retry_exhausted"] = exhausted
    session["active_run"] = run
    return not exhausted


def assert_api_generation_ready(generation_mode: str) -> None:
    if str(generation_mode or "api").lower() != "api":
        return
    creds = check_connectivity._resolve_api_credentials()
    if not str(creds.get("api_key", "")).strip():
        raise RuntimeError("api_generation_mode requires configured OpenAI-compatible API key")


def current_pending_decision(session: dict[str, Any]) -> dict[str, Any] | None:
    pending = session.get("pending_decision")
    if isinstance(pending, dict) and str(pending.get("status", "")) == "pending" and str(pending.get("question", "")).strip():
        return pending
    questions = session.get("whiteboard", {}).get("blocking_questions", []) if isinstance(session.get("whiteboard"), dict) else []
    if isinstance(questions, list) and questions:
        question = str(questions[0]).strip()
        if question:
            pending = {"kind": "PendingDecision", "status": "pending", "question": question, "created_at": now()}
            session["pending_decision"] = pending
            return pending
    return None


def create_intake_ticket(session_dir: pathlib.Path, session: dict[str, Any], text: str) -> dict[str, Any]:
    tickets = session.setdefault("intake_tickets", [])
    ticket_id = f"ticket-{safe_id(session.get('chat_id', 'chat'))}-{len(tickets) + 1}"
    ticket = {
        "kind": "CustomerIntakeTicket",
        "id": ticket_id,
        "created_at": now(),
        "raw_user_message": text,
        "status": "open",
    }
    tickets.append(ticket)
    session["intake_tickets"] = tickets[-40:]
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    next_whiteboard = merge_whiteboard(
        whiteboard,
        {
            "project_summary": text,
            "known_facts": [f"用户提出的新项目需求: {text}"],
            "first_version_plan": [
                "先建立 intake ticket；后台同步并行启动真实生成，前台继续确认细节并把补充写入修订控制命令。",
            ],
            "decision_log": ["项目需求进入后即并行启动后台生成；正式生成只能由 API/provider 或已配置的本地模型后端执行。"],
            "ready_to_generate": False,
        },
    )
    session["whiteboard"] = enforce_backend_updates_from_user_text(session, next_whiteboard)
    append_whiteboard_version(session, session["whiteboard"])
    append_memory_event(session, "intake_ticket_created", data={"ticket_id": ticket_id, "raw_user_message": text[:1200]})
    append_truth_ledger(
        session_dir,
        session,
        "intake_ticket",
        "新项目需求已进入本地 intake",
        evidence_ref=ticket_id,
        data={"artifact": "intake_ticket", "ticket_id": ticket_id},
    )
    return ticket


def append_backend_memo(session_dir: pathlib.Path, session: dict[str, Any], stage: str, text: str) -> dict[str, Any]:
    memo = {"kind": "HumanBackendMemo", "created_at": now(), "stage": stage, "text": text}
    memos = session.setdefault("backend_memos", [])
    memos.append(memo)
    session["backend_memos"] = memos[-80:]
    append_memory_event(session, "backend_memo", text, {"stage": stage})
    append_truth_ledger(
        session_dir,
        session,
        "backend_memo",
        "后台同事式进度 memo 已生成",
        evidence_ref=stage,
        data={"artifact": "human_backend_memo"},
    )
    return memo


def latest_backend_memo(session: dict[str, Any]) -> str:
    memos = session.get("backend_memos", [])
    if not isinstance(memos, list) or not memos:
        return ""
    last = memos[-1]
    return str(last.get("text", "")) if isinstance(last, dict) else ""


def append_backend_control(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    action: str,
    *,
    payload: dict[str, Any] | None = None,
    status: str = "logged",
    reason: str = "",
) -> dict[str, Any]:
    controls = session.setdefault("backend_controls", [])
    if not isinstance(controls, list):
        controls = []
    run = active_run(session) or {}
    control = {
        "kind": "BackendControlLog",
        "id": f"ctrl-{safe_id(session.get('chat_id', 'chat'))}-{len(controls) + 1}",
        "action": action,
        "status": status,
        "log_only": True,
        "reason": reason,
        "active_run_id": str(run.get("id", "")),
        "ticket_id": str(run.get("ticket_id", "")),
        "created_at": now(),
        "updated_at": now(),
        "payload": payload or {},
    }
    controls.append(control)
    session["backend_controls"] = controls[-120:]
    if isinstance(run, dict) and run:
        run["last_control_id"] = control["id"]
        run["last_control_action"] = action
        run["updated_at"] = now()
        session["active_run"] = run
    append_memory_event(
        session,
        "backend_control_logged",
        data={"control_id": control["id"], "action": action, "status": status, "reason": reason},
    )
    append_truth_ledger(
        session_dir,
        session,
        "backend_control",
        "前台事件已写入兼容日志，正式生成由 agent_session 和 agent loop 推进。",
        evidence_ref=control["id"],
        data={"artifact": "backend_control_log", "control_id": control["id"], "action": action, "status": status, "log_only": True},
    )
    return control


def update_backend_control_status(
    session: dict[str, Any],
    control_id: str,
    status: str,
    *,
    reason: str = "",
    result_path: str = "",
) -> None:
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list):
        return
    for control in reversed(controls):
        if isinstance(control, dict) and str(control.get("id", "")) == str(control_id):
            control["status"] = status
            control["updated_at"] = now()
            if reason:
                control["reason"] = reason
            if result_path:
                control["result_path"] = result_path
            break
    session["backend_controls"] = controls


def latest_backend_control(session: dict[str, Any]) -> dict[str, Any]:
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list) or not controls:
        return {}
    last = controls[-1]
    return last if isinstance(last, dict) else {}


def has_open_backend_control(session: dict[str, Any], actions: set[str]) -> bool:
    # Legacy status display only. Telegram generation_confirmation must not use
    # backend_controls as a queue or blocker.
    controls = session.get("backend_controls", [])
    if not isinstance(controls, list):
        return False
    for control in reversed(controls):
        if not isinstance(control, dict):
            continue
        if str(control.get("action", "")) in actions and str(control.get("status", "")).lower() in {"queued", "running", "applied"}:
            return True
    return False


def generation_control_payload(session: dict[str, Any], requirement: str, generation_mode: str = "api") -> dict[str, Any]:
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    return {
        "requirement": requirement[:12000],
        "project_summary": str(whiteboard.get("project_summary", ""))[:2000],
        "acceptance_criteria": whiteboard.get("acceptance_criteria", []) if isinstance(whiteboard.get("acceptance_criteria"), list) else [],
        "delivery_requirements": whiteboard.get("delivery_requirements", []) if isinstance(whiteboard.get("delivery_requirements"), list) else [],
        "change_requests": whiteboard.get("change_requests", []) if isinstance(whiteboard.get("change_requests"), list) else [],
        "attachments": recent_attachments(session, limit=20),
        "control_flags": {
            "generation_mode": "agent_conversation_loop",
            "backend_controls_are_log_only": True,
        },
    }


def frontdesk_compose(event: str, session: dict[str, Any], facts: dict[str, Any] | None = None, backend_memo: str = "") -> str:
    facts = facts or {}
    if event == "greeting":
        return "你好，我在。你直接说想做的项目和最重要的效果就行，我会按一个可交付项目来整理和推进。"
    if event == "status_requested":
        generation = active_run(session) or (session.get("generation", {}) if isinstance(session.get("generation"), dict) else {})
        evidence = facts.get("evidence_state", {}) if isinstance(facts.get("evidence_state"), dict) else {}
        status = str(generation.get("status", "idle"))
        status_label = {
            "idle": "还没开始生成",
            "queued": "已排队",
            "running": "正在处理",
            "waiting_decision": "等你确认一个关键问题",
            "failed": "已中断",
            "pass": "可以交付",
        }.get(status.lower(), status)
        missing_labels = {
            "package": "可运行项目文件",
            "screenshot": "效果预览",
            "verify_report": "测试结论",
            "verify_passed": "测试通过确认",
        }
        missing = "、".join(missing_labels.get(str(item), str(item)) for item in evidence.get("missing", [])) or "无"
        return f"当前状态：{status_label}。还缺：{missing}。没有可运行结果、预览或测试结论前，我不会说已经完成。"
    if event == "pending_decision":
        question = str(facts.get("question", "")).strip()
        return f"这里先确认一个关键点：{question}"
    if event == "intake_ticket_created":
        summary = str(facts.get("project_summary") or latest_user_text(session) or "这个项目").strip()
        if facts.get("backend_parallel_started"):
            return (
                f"收到，方向我记下来了：{summary}\n"
                "我会继续和你确认细节；后台也已经并行接到这版需求，开始按可运行项目、依赖库、实现方法、预览和测试证据推进。"
                "没有做出能检查的结果前，我不会把它说成完成。"
            )
        return f"收到，方向我记下来了：{summary}\n我会按本地可运行的第一版来整理：核心功能、输入输出、可见预览和测试标准都会一起考虑。没有做出能检查的结果前，我不会把它说成完成。"
    if event == "simulator_started":
        return "当前状态：正在处理。我开始按这版需求往下推进；还没有可运行项目、效果预览和测试结论，所以不会提前说完成。"
    if event == "blocked":
        reason = str(facts.get("reason", "当前证据不足或流程被阻断"))
        return f"这轮先停住：{reason}。我会把已确认的需求保留下来，下一次可以从这个方向继续。"
    if event == "delivery_ready":
        return "可交付材料已经齐了，我会直接发项目结果、效果预览和测试结论。"
    if event == "unsupported_attachment_received":
        return "我收到了非文本消息。当前可接收图片、文档、视频、音频这几类资料；你也可以补一句它要怎么用于项目。"
    if event == "generation_failed":
        return str(facts.get("user_visible_cause") or "后台流程中断，当前不能交付。我已经记录问题，后续可以重试或升级处理。")
    return str(facts.get("message") or backend_memo or "我已记录，会继续按当前项目上下文处理。")


def pre_send_guard(text: str) -> str:
    guarded = str(text or "").strip()
    guarded = re.sub(r"[A-Za-z]:\\[^\s，。；；]+", "本地工作区记录", guarded)
    guarded = re.sub(r"/(?:[^/\s，。；]+/){2,}[^/\s，。；]+", "本地工作区记录", guarded)
    replacements = {
        "provider_user_message": "回复",
        "customer_service_reply": "回复",
        "truth_ledger.jsonl": "交付记录",
        "intake ticket": "项目记录",
        "simulator team": "制作流程",
        "local_simulator_team": "制作流程",
        "simulator": "制作流程",
        "agent/provider": "后续处理",
        "provider": "后续处理",
        "API": "外部接口",
        "后台 memo:": "",
        "package": "可运行项目文件",
        "verify report": "测试结论",
        "truth ledger": "交付记录",
        "证据账本": "交付记录",
        "BLOCKED": "暂停",
    }
    for old, new in replacements.items():
        guarded = guarded.replace(old, new)
    guarded = guarded.replace("JSON", "结构化记录")
    return guarded[:3900] or "我已记录。"


def send_customer_reply(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    *,
    event: str,
    facts: dict[str, Any] | None = None,
    backend_memo: str = "",
    source: str = "frontdesk_composer",
    direct_text: str = "",
) -> bool:
    text = pre_send_guard(direct_text or frontdesk_compose(event, session, facts, backend_memo))
    session.setdefault("messages", []).append({"role": "assistant", "text": text, "created_at": now(), "source": source, "event": event})
    append_memory_event(session, "assistant_message", text, {"source": source, "event": event})
    append_truth_ledger(
        session_dir,
        session,
        "frontdesk_outbound",
        "用户可见回复已通过客服 composer 和发送前 guard",
        evidence_ref=event,
        can_user_see=True,
        data={"artifact": "frontdesk_reply", "event": event},
    )
    ok = client.send_message(chat_id, text)
    append_truth_ledger(
        session_dir,
        session,
        "sent_record",
        "客服出口发送结果已记录",
        status="sent" if ok else "failed",
        evidence_ref=event,
        can_user_see=ok,
        data={"artifact": "sent_record", "event": event, "transport": "telegram_message"},
    )
    save_session(session_dir, session)
    return ok


def provider_escalation_allowed(session_dir: pathlib.Path, chat_id: int | str, classification: dict[str, Any]) -> bool:
    return str(classification.get("intent")) == "escalation_request"


def maybe_auto_deliver_if_ready(client: TelegramClient, chat_id: int | str, session_dir: pathlib.Path) -> dict[str, Any]:
    session = load_session(session_dir, chat_id)
    evidence = delivery_evidence_state(read_truth_ledger(session_dir, chat_id))
    if evidence["delivery_ready"] and not evidence.get("sent_record"):
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="delivery_ready",
            facts={"evidence_state": evidence},
            backend_memo=latest_backend_memo(session),
        )
        send_delivery_artifacts(client, chat_id, session_dir, session, evidence)
        evidence = delivery_evidence_state(read_truth_ledger(session_dir, chat_id))
    return evidence


def _evidence_path(raw: str) -> pathlib.Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = pathlib.Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path if path.exists() and path.is_file() else None


def make_project_package(project_dir: pathlib.Path, log_dir: pathlib.Path) -> pathlib.Path:
    source = pathlib.Path(project_dir)
    if not source.exists() or not source.is_dir():
        raise RuntimeError(f"project directory is missing for delivery package: {source}")
    package_base = log_dir / f"{safe_id(source.name)}_final_project_bundle"
    zip_path = pathlib.Path(str(package_base) + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(package_base), "zip", root_dir=str(source))
    return zip_path


def ensure_verify_report(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path:
    existing = pathlib.Path(str(result.get("effect_report_path", "")))
    if existing.exists() and existing.is_file():
        return existing
    report = log_dir / f"{safe_id(result.get('project_dir', 'project'))}_verify_report.json"
    write_json(
        report,
        {
            "kind": "VerifyReport",
            "status": str(result.get("status", "")).upper(),
            "project_dir": result.get("project_dir", ""),
            "runtime_dir": result.get("runtime_dir", ""),
            "generated_files": result.get("generated_files", []),
            "agent_usage": result.get("agent_usage", {}),
        },
    )
    return report


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def emit_delivery_evidence(
    session_dir: pathlib.Path,
    session: dict[str, Any],
    result: dict[str, Any],
    screenshot: pathlib.Path | None,
    log_dir: pathlib.Path,
) -> dict[str, str]:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    package = make_project_package(project_dir, log_dir)
    verify_report = ensure_verify_report(result, log_dir)
    refs = {
        "package": str(package),
        "verify_report": str(verify_report),
        "verify_passed": str(verify_report),
    }
    if screenshot:
        refs["screenshot"] = str(screenshot)
    for artifact, path in refs.items():
        append_truth_ledger(
            session_dir,
            session,
            artifact,
            f"{artifact} evidence recorded",
            status="pass",
            evidence_ref=path,
            data={"artifact": artifact, "verify_passed": artifact == "verify_passed"},
        )
    save_session(session_dir, session)
    return refs


def send_delivery_artifacts(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = evidence.get("refs", {}) if isinstance(evidence.get("refs"), dict) else {}
    sent: list[dict[str, Any]] = []
    screenshot = _evidence_path(str(refs.get("screenshot", "")))
    if screenshot:
        client.send_chat_action(chat_id, "upload_photo")
        if client.send_photo(chat_id, screenshot, "效果预览"):
            sent.append({"kind": "photo", "path": str(screenshot)})
    for key, caption in (("package", "可运行项目文件"), ("verify_report", "测试结论")):
        path = _evidence_path(str(refs.get(key, "")))
        if not path:
            continue
        client.send_chat_action(chat_id, "upload_document")
        if client.send_document(chat_id, path, caption):
            sent.append({"kind": "document", "artifact": key, "path": str(path)})
    if sent:
        append_truth_ledger(
            session_dir,
            session,
            "delivery_attachment_sent",
            "真实交付附件已通过 Telegram 发送",
            status="sent",
            evidence_ref="telegram_delivery",
            can_user_see=True,
            data={"artifact": "delivery_attachment_sent", "sent": sent},
        )
        append_memory_event(session, "delivery_attachment_sent", data={"sent": sent})
        save_session(session_dir, session)
    return sent


def read_delivery_manifest(path: str | pathlib.Path) -> dict[str, Any]:
    manifest_path = pathlib.Path(str(path))
    if not manifest_path.exists():
        return {}
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def send_delivery_from_manifest(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    package = _evidence_path(str(manifest.get("package_path", "")))
    manifest_path = _evidence_path(str(manifest.get("manifest_path", "")))
    readme = _evidence_path(str(manifest.get("readme_path", "")))
    startup_command = str(manifest.get("startup_command", "")).strip()
    known_limits = manifest.get("known_limits", []) if isinstance(manifest.get("known_limits"), list) else []
    lines = ["项目包已经生成，可以直接下载。"]
    if startup_command:
        lines.append(f"启动方式：{startup_command}")
    if known_limits:
        lines.append("已记录的限制：" + "；".join(str(item) for item in known_limits[:4]))
    send_customer_reply(
        client,
        chat_id,
        session_dir,
        session,
        event="delivery_manifest_ready",
        facts={"manifest": manifest},
        source="local_packager_manifest",
        direct_text="\n".join(lines),
    )
    session = load_session(session_dir, chat_id)
    for path, caption, kind in (
        (package, "可运行项目文件", "package"),
        (manifest_path, "交付清单", "delivery_manifest"),
        (readme, "项目说明", "readme"),
    ):
        if not path:
            continue
        client.send_chat_action(chat_id, "upload_document")
        if client.send_document(chat_id, path, caption):
            sent.append({"kind": kind, "path": str(path)})
            append_truth_ledger(
                session_dir,
                session,
                kind,
                f"{kind} sent from local delivery manifest",
                status="sent",
                evidence_ref=str(path),
                can_user_see=True,
                data={"artifact": kind, "source": "delivery_manifest"},
            )
    if sent:
        append_memory_event(session, "delivery_manifest_sent", data={"sent": sent, "manifest": manifest})
    save_session(session_dir, session)
    return sent


def append_whiteboard_version(session: dict[str, Any], whiteboard: dict[str, Any]) -> None:
    versions = session.setdefault("whiteboard_versions", [])
    if not isinstance(versions, list):
        versions = []
    versions.append({"created_at": now(), "whiteboard": whiteboard})
    session["whiteboard_versions"] = versions[-80:]


def unique_strings(values: list[Any], limit: int = 120) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[-limit:]


def merge_whiteboard(previous: dict[str, Any], next_whiteboard: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    append_keys = {
        "known_facts",
        "default_assumptions",
        "first_version_plan",
        "user_rules",
        "acceptance_criteria",
        "change_requests",
        "decision_log",
        "delivery_requirements",
    }
    replace_keys = {"open_questions", "blocking_questions"}
    for key, value in next_whiteboard.items():
        if key in append_keys:
            prior = previous.get(key, [])
            merged[key] = unique_strings((prior if isinstance(prior, list) else []) + (value if isinstance(value, list) else []))
        elif key in replace_keys:
            merged[key] = unique_strings(value if isinstance(value, list) else [], limit=40)
        elif key == "project_summary":
            text = str(value).strip()
            merged[key] = text or str(previous.get(key, "")).strip()
        else:
            merged[key] = value
    for key in append_keys | replace_keys:
        merged.setdefault(key, [])
    merged.setdefault("project_summary", "")
    merged.setdefault("ready_to_generate", False)
    return merged


def read_project_memory_excerpt(session: dict[str, Any], limit: int = 6000) -> str:
    project_memory = session.get("project_memory", {})
    if not isinstance(project_memory, dict):
        return ""
    path = pathlib.Path(str(project_memory.get("project_memory_md", "")))
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def combined_requirement(session: dict[str, Any]) -> str:
    whiteboard = session.get("whiteboard", {})
    if isinstance(whiteboard, dict):
        parts: list[str] = []
        project_memory = session.get("project_memory", {})
        if isinstance(project_memory, dict):
            md_path = str(project_memory.get("project_memory_md", "")).strip()
            artifact_path = str(project_memory.get("project_memory_artifact", "")).strip()
            if md_path or artifact_path:
                parts.append(
                    "项目长期规格文档:\n"
                    + (f"- markdown: {md_path}\n" if md_path else "")
                    + (f"- artifact_json: {artifact_path}" if artifact_path else "")
                )
        summary = str(whiteboard.get("project_summary", "")).strip()
        if summary:
            parts.append(summary)
        attachment_lines = attachment_requirement_lines(session)
        if attachment_lines:
            parts.append("用户上传资料和本地输入:\n" + "\n".join(attachment_lines))
        for key, label in (
            ("known_facts", "已确认事实"),
            ("default_assumptions", "默认假设"),
            ("first_version_plan", "第一版方案"),
            ("user_rules", "用户长期规则"),
            ("acceptance_criteria", "验收标准"),
            ("change_requests", "用户纠正和后续修改"),
            ("delivery_requirements", "交付展示要求"),
            ("decision_log", "已采用决策记录"),
        ):
            values = whiteboard.get(key, [])
            lines = [f"- {item}" for item in values if isinstance(item, str) and item.strip()]
            if lines:
                parts.append(label + ":\n" + "\n".join(lines))
        memory_excerpt = read_project_memory_excerpt(session)
        if memory_excerpt:
            parts.append("项目长期规格 MD 摘要:\n" + memory_excerpt)
        if parts:
            return "\n".join(parts).strip()
    lines: list[str] = []
    for msg in session.get("messages", []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            text = str(msg.get("text", "")).strip()
            if text and not text.startswith("/") and not is_generate_command(text) and not is_smalltalk(text):
                lines.append(text)
    return "\n".join(lines).strip()


def is_smalltalk(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", text.lower())
    return compact in {
        "你好",
        "您好",
        "hello",
        "hi",
        "hey",
        "在吗",
        "测试",
        "test",
        "有人吗",
    }


def is_generate_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    if compact in {"/generate", "/build"}:
        return True
    control_phrases = {
        "开始生成",
        "可以生成",
        "直接生成",
        "生成项目",
        "开始吧",
        "开工",
        "做吧",
    }
    if compact in control_phrases:
        return True
    # Long requirement text can naturally contain words like "生成图片".
    # Treat generation triggers as commands only when the whole message is a short control phrase.
    return len(compact) <= 10 and any(phrase == compact for phrase in control_phrases)


def assistant_invited_start(session: dict[str, Any]) -> bool:
    for msg in reversed(session.get("messages", [])):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        text = str(msg.get("text", "")).strip()
        if role == "assistant":
            compact = re.sub(r"\s+", "", text.lower())
            return any(token in compact for token in ("可以开始", "开始做", "确认后", "我这边开始", "我来推进"))
        if role == "user":
            continue
    return False


def is_human_start_confirmation(text: str, session: dict[str, Any]) -> bool:
    if not assistant_invited_start(session):
        return False
    compact = re.sub(r"[\s,.!?。！？~～]+", "", text.lower())
    confirmations = {
        "可以",
        "没问题",
        "对",
        "是的",
        "确认",
        "确认无误",
        "就这样",
        "按这个做",
        "帮我做",
        "帮我做吧",
        "好的",
        "ok",
        "yes",
        "go",
    }
    return compact in confirmations


def parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        doc = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return None
        try:
            doc = json.loads(match.group(0))
        except Exception:
            return None
    return doc if isinstance(doc, dict) else None


def provider_text(messages: list[dict[str, str]], model: str, timeout: int) -> str:
    creds = check_connectivity._resolve_api_credentials()
    token = creds.get("api_key", "")
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for Telegram customer service")
    root = str(creds.get("base_url", "")).rstrip("/")
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = root + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.25, "max_tokens": 900}
    else:
        endpoint = root + "/responses"
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {"model": model, "input": prompt, "temperature": 0.25, "max_output_tokens": 900}
    last_error = ""
    for attempt in range(6):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            break
        last_error = error
        time.sleep(min(20.0, 2.0 * (attempt + 1)))
    else:
        raise RuntimeError(last_error)
    text = check_connectivity._extract_text(doc)
    if not text:
        raise RuntimeError("empty customer-service response")
    return text


def recent_dialogue(session: dict[str, Any], limit: int = 12) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in session.get("messages", [])[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        text = str(msg.get("text", "")).strip()
        if text.startswith("客服 API 暂时没有返回合格回复") or text.startswith("API_CUSTOMER_SERVICE_FAILED"):
            continue
        if "请回复" in text or "开始生成" in text:
            continue
        if role == "user" and is_generate_command(text):
            continue
        if role in {"user", "assistant"} and text:
            out.append({"role": role, "content": text})
    return out


def latest_user_text(session: dict[str, Any]) -> str:
    for msg in reversed(session.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "user":
            text = str(msg.get("text", "")).strip()
            if text and not text.startswith("/"):
                return text
    return ""


def meaningful_terms(text: str) -> set[str]:
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").lower())
    terms: set[str] = set()
    for part in raw.split():
        if len(part) >= 3:
            terms.add(part)
        if re.search(r"[\u4e00-\u9fff]", part):
            for size in (2, 3, 4):
                for i in range(0, max(0, len(part) - size + 1)):
                    terms.add(part[i : i + size])
    stop = {"这个", "那个", "然后", "就是", "可以", "需要", "项目", "生成", "帮我", "做个", "一个"}
    return {term for term in terms if term not in stop}


def reply_looks_off_topic(session: dict[str, Any], reply: str, whiteboard: dict[str, Any]) -> bool:
    user_text = latest_user_text(session)
    if not user_text or len(user_text) < 6:
        return False
    project_summary = str(whiteboard.get("project_summary", ""))
    source_terms = meaningful_terms(user_text) | set(list(meaningful_terms(project_summary))[:40])
    if not source_terms:
        return False
    reply_terms = meaningful_terms(reply)
    overlap = source_terms & reply_terms
    if overlap:
        return False
    generic_markers = ("我可以", "请提供", "需要更多信息", "无法", "不确定", "抱歉")
    return any(marker in reply for marker in generic_markers) or len(reply_terms) < 6


def grounded_customer_fallback(session: dict[str, Any], whiteboard: dict[str, Any]) -> str:
    user_text = latest_user_text(session)
    summary = str(whiteboard.get("project_summary", "")).strip() or user_text
    defaults = whiteboard.get("default_assumptions", [])
    plan = whiteboard.get("first_version_plan", [])
    default_text = "；".join(str(item) for item in defaults[:3] if str(item).strip()) or "先采用本地优先、可测试、带预览交付的默认方案"
    plan_text = "；".join(str(item) for item in plan[:3] if str(item).strip()) or "先整理第一版需求、生成项目文件、跑测试并交付预览"
    return (
        f"我按你刚才说的方向继续整理：{summary[:260]}。\n"
        f"这轮先不偏题展开，我会按这些默认值推进：{default_text}。\n"
        f"第一版重点是：{plan_text}。如果你有必须保留或不允许的点，直接补一句，我会写进后续生成。"
    )[:1200]


def visual_delivery_requirements_from_text(text: str) -> list[str]:
    compact = str(text or "").lower()
    requirements: list[str] = []
    if any(token in compact for token in ("图片", "照片", "图像", "生成图", "ai图", "立绘", "背景图", "image", "photo")):
        requirements.append("交付时必须直接发送图片/照片预览 artifact，不只返回路径")
    if any(token in compact for token in ("截图", "预览图", "高光帧", "frame", "screenshot")):
        requirements.append("交付时必须直接发送截图或关键帧预览")
    if any(token in compact for token in ("视频", "短视频", "录像", "mp4", "webm", "video")):
        requirements.append("交付时必须直接发送视频预览 artifact，不只返回路径")
    if any(token in compact for token in ("可视化", "预览", "展示效果", "demo")):
        requirements.append("交付时必须提供可视化预览或摘要图兜底")
    return unique_strings(requirements, limit=12)


def normalize_question_fields(whiteboard: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(whiteboard)
    blocking = unique_strings(normalized.get("blocking_questions", []) if isinstance(normalized.get("blocking_questions"), list) else [], limit=20)
    open_questions = unique_strings(normalized.get("open_questions", []) if isinstance(normalized.get("open_questions"), list) else [], limit=40)
    if len(blocking) > 1:
        open_questions = unique_strings(open_questions + blocking[1:], limit=40)
        blocking = blocking[:1]
    normalized["blocking_questions"] = blocking
    normalized["open_questions"] = open_questions
    return normalized


def enforce_backend_updates_from_user_text(session: dict[str, Any], whiteboard: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_question_fields(whiteboard)
    text = latest_user_text(session)
    visual_requirements = visual_delivery_requirements_from_text(text)
    if visual_requirements:
        delivery = normalized.get("delivery_requirements", [])
        acceptance = normalized.get("acceptance_criteria", [])
        normalized["delivery_requirements"] = unique_strings((delivery if isinstance(delivery, list) else []) + visual_requirements, limit=120)
        normalized["acceptance_criteria"] = unique_strings((acceptance if isinstance(acceptance, list) else []) + visual_requirements, limit=120)
        append_memory_event(
            session,
            "backend_delivery_requirements_updated",
            data={"source": "latest_user_text", "requirements": visual_requirements},
        )
    if any(token in text for token in ("必须", "不允许", "不要", "一定要", "后续", "修改", "不是", "我要的是")):
        changes = normalized.get("change_requests", [])
        normalized["change_requests"] = unique_strings((changes if isinstance(changes, list) else []) + [text], limit=120)
    return normalized


def substantive_user_turn_count(session: dict[str, Any]) -> int:
    count = 0
    for msg in session.get("messages", []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        text = str(msg.get("text", "")).strip()
        if text and not text.startswith("/") and not is_smalltalk(text) and not is_generate_command(text):
            count += 1
    return count


def customer_service_reply(session: dict[str, Any], model: str, timeout: int) -> tuple[str, dict[str, Any], str]:
    policy = read_customer_agent_policy()
    system = """你是 CGNK 项目生成与交付团队的 Telegram 前台接口，更像项目负责人和产品/工程搭档，不是闲聊机器人，也不是表单客服。
你的目标是把用户的一句话想法主动发展成可生成、可测试、可交付预览的第一版项目方案。

自我认知：
- 你代表 CGNK 后台项目工作流，负责理解需求、形成方案、维护项目记忆、协调生成、测试和交付。
- 你可以说“我这边会生成/测试/交付/记录”，但不要假装有人类团队正在手工开发；应表达为后台工作流会执行。
- 你的主要任务不是陪聊，而是推进项目落地：默认值、边界、验收点、图片/视频/截图交付、后续修改都要落到白板。
- 用户问你是谁或能做什么时，回答你是 CGNK 项目交付接口，可以帮助生成项目、测试、预览、保存长期记忆和清理/重启会话。

核心策略：
- 不要逐项审问字段，不要“复述一句再问一个缺口”的客服脚本。
- 先做专业判断：拆解产品层、技术层、默认方案和第一版边界。
- 对可默认的信息直接给默认假设并继续，不要阻塞用户。
- 只有缺失信息会导致完全无法生成时，才问一个阻塞问题。
- 必须维护持续记忆：保留 current_whiteboard 里已有的用户规则、验收标准、修改请求、交付要求和决策记录。
- 用户用“不是、我要的是、为什么没有、后续修改、必须、不允许”等方式纠正时，要写入 change_requests 或 acceptance_criteria。
- 对你的产品/技术判断用一句可审计摘要写入 decision_log；这不是隐藏思维链，而是给后续 agent 复用的决策记录。
- 输出要体现你懂这个项目。例如游戏视频高光项目，应主动给出视频输入、事件检测、高光评分、剪辑导出、MP4/H.264、通用信号检测等方案。
- 不要要求用户回复固定口令，不要写“请回复开始生成”。
- 如果信息足以生成第一版，回复里自然说明“我按这个方向开始做第一版”，并把 action 设为 "start_generation"。
- 当 action 是 "start_generation" 时，reply 不能只有一句“开始做”；要简短列出将生成的第一版能力、默认假设和测试/预览目标。
- 如果用户只是第一次提出项目想法，先给出你建议的第一版方案和默认假设，通常不要立刻启动生成；等用户继续补充、确认方向或没有提出硬性限制后，再把 action 设为 "start_generation"。
- 回复必须紧扣最近一条用户消息和 current_whiteboard，不要把话题切到无关产品、无关技术栈或通用客服话术。
- 如果最近用户在纠正你，先承认修正点并更新白板，再继续推进；不要沿用旧理解。
- 如果用户要求图片、视频、预览或可视化，必须把它写入 delivery_requirements 和 acceptance_criteria。
- 用户上传图片、文档、视频、音频或数据文件时，必须把它当作项目输入资料；结合 caption 和 current_attachments 更新 known_facts、验收点或修改要求，不要回复“只能收文字”。
- 不要暴露内部模块名、API/provider 名称、路径堆栈。
- 输出必须是 JSON 对象，不要 Markdown，不要额外文字。

可默认字段策略：
- game_type: 默认“通用游戏视频”，除非用户指定某个游戏。
- output_format: 默认 MP4/H.264。
- clip_duration: 默认 15-60 秒，可在产品里做成可调参数。
- highlight_signals: 默认组合 audio_peak、scene_change、motion_intensity、ocr_text、manual_timestamp。
- preview: 默认需要结果预览，优先生成高光帧截图和短视频预览。

JSON 结构：
{
  "reply": "发给用户的自然回复，像懂项目的人在推进方案",
  "action": "continue_chat 或 start_generation",
  "whiteboard": {
    "project_summary": "面向生成器的一段完整项目需求；没有项目需求时为空字符串",
    "known_facts": ["已经确认的重要事实"],
    "default_assumptions": ["你主动采用的默认值"],
    "first_version_plan": ["第一版会做什么"],
    "blocking_questions": ["真正阻塞生成的问题；通常为空"],
    "open_questions": ["不阻塞生成、后续可调的问题"],
    "user_rules": ["用户明确要求长期遵守的行为规则"],
    "acceptance_criteria": ["本项目必须满足的验收标准"],
    "change_requests": ["用户后续纠正、补充和修改要求"],
    "delivery_requirements": ["用户要求如何展示过程、图片、视频、测试结果"],
    "decision_log": ["可审计的方案决策摘要"],
    "ready_to_generate": false
  }
}
"""
    system += "\n\n当前热加载行为策略如下，必须优先遵守：\n" + policy
    whiteboard = session.get("whiteboard", {})
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_whiteboard": whiteboard if isinstance(whiteboard, dict) else {},
                    "substantive_user_turn_count": substantive_user_turn_count(session),
                    "recent_memory_events": session.get("memory_events", [])[-40:],
                    "current_attachments": recent_attachments(session, limit=30),
                    "attachment_requirement_lines": attachment_requirement_lines(session),
                    "project_memory": session.get("project_memory", {}),
                    "project_memory_excerpt": read_project_memory_excerpt(session, limit=5000),
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
        *recent_dialogue(session, limit=30),
    ]
    raw = provider_text(messages, model, timeout)
    doc = parse_json_object(raw)
    if not doc:
        return raw[:900], whiteboard if isinstance(whiteboard, dict) else {}, "continue_chat"
    reply = str(doc.get("reply", "")).strip()
    if not reply:
        raise RuntimeError("customer-service provider returned empty reply")
    action = str(doc.get("action", "continue_chat")).strip()
    if action not in {"continue_chat", "start_generation"}:
        action = "continue_chat"
    next_whiteboard = doc.get("whiteboard", {})
    if not isinstance(next_whiteboard, dict):
        next_whiteboard = whiteboard if isinstance(whiteboard, dict) else {}
    elif isinstance(whiteboard, dict):
        next_whiteboard = merge_whiteboard(whiteboard, next_whiteboard)
    rejected_off_topic = reply_looks_off_topic(session, reply, next_whiteboard)
    if rejected_off_topic:
        append_memory_event(
            session,
            "customer_reply_rejected",
            data={"reason": "off_topic_guard", "provider_reply": reply[:900], "latest_user_text": latest_user_text(session)[:900]},
        )
        reply = grounded_customer_fallback(session, next_whiteboard)
        action = "continue_chat"
    if not rejected_off_topic and bool(next_whiteboard.get("ready_to_generate")) and not next_whiteboard.get("blocking_questions"):
        action = "start_generation"
    if action == "start_generation" and not str(next_whiteboard.get("project_summary", "")).strip():
        action = "continue_chat"
        next_whiteboard["ready_to_generate"] = False
    next_whiteboard = enforce_backend_updates_from_user_text(session, next_whiteboard)
    if next_whiteboard.get("blocking_questions"):
        action = "continue_chat"
    return reply, next_whiteboard, action


def provider_user_message(
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
) -> str:
    policy = read_customer_agent_policy()
    system = """你是 CGNK 项目生成与交付团队的 Telegram 前台接口。
根据事件和事实生成一条自然、简短、像项目负责人/产品工程搭档的中文消息。

规则：
- 自我定位要稳定：你代表 CGNK 后台工作流推进需求、生成、测试、预览和交付，不是普通聊天机器人。
- 不要使用固定口令、模板腔、机器人流程话术。
- 不要要求用户回复固定词，例如“开始生成”。
- 不要暴露内部模块名。
- 如果是交付结果，不要只报路径；要概括本次项目做了什么、测试是否通过、用户能看到什么效果、缺了什么预览、下一步建议。
- 交付结果里可以保留关键路径和状态，方便用户检查，但路径不是主体。
- 如果没有截图或预览，解释为“本轮测试没有产出 preview artifact”，并建议下一步补预览图/短视频任务。
- 如果是失败，只能使用 facts.user_visible_cause、facts.impact、facts.next_step 说明原因和下一步；不要根据内部错误猜测成图片模型、项目代码或用户需求问题。
- 失败回复不要贴底层堆栈，不要暴露内部参数名，不要承诺本地模板兜底。
- 只输出要发给用户的一条消息，不要 JSON，不要 Markdown 表格。
"""
    system += "\n\n当前热加载行为策略如下，必须优先遵守：\n" + policy
    payload = {
        "event": event,
        "facts": facts,
        "whiteboard": session.get("whiteboard", {}),
        "recent_dialogue": recent_dialogue(session, limit=20),
        "recent_memory_events": session.get("memory_events", [])[-40:],
        "current_attachments": recent_attachments(session, limit=30),
        "attachment_requirement_lines": attachment_requirement_lines(session),
        "project_memory": session.get("project_memory", {}),
        "project_memory_excerpt": read_project_memory_excerpt(session, 5000),
    }
    text = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model,
        timeout,
    ).strip()
    if not text:
        raise RuntimeError("provider returned empty user-facing message")
    return text[:1200]


def send_provider_message(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
) -> bool:
    try:
        text = provider_user_message(event=event, session=session, facts=facts, model=model, timeout=min(timeout, 60))
    except Exception as exc:
        print(f"user-message provider failed: {exc}", flush=True)
        return False
    append_backend_memo(session_dir, session, f"provider_{event}", text)
    return send_customer_reply(
        client,
        chat_id,
        session_dir,
        session,
        event=event,
        facts=facts,
        source="provider_user_message",
        direct_text="",
        backend_memo=text,
    )


def send_provider_or_technical_error(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
    technical_error: str,
) -> None:
    if send_provider_message(client, chat_id, session_dir, event=event, session=session, facts=facts, model=model, timeout=timeout):
        return
    send_customer_reply(
        client,
        chat_id,
        session_dir,
        session,
        event=event,
        facts={"message": "刚才连接中断了一下，我已经把问题记录下来了。你可以继续补充需求，我会接着处理。", "technical_error": technical_error},
        source="frontdesk_composer",
    )


def log_bridge_error(log_dir: pathlib.Path, event: str, chat_id: int | str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    append_jsonl(
        log_dir / "bridge_errors.jsonl",
        {
            "created_at": now(),
            "event": event,
            "chat_id": str(chat_id),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "context": context or {},
        },
    )


def is_valid_image_file(path: pathlib.Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        head = path.read_bytes()[:16]
    except Exception:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return True
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return True
    return False


def delivery_image_candidates(result: dict[str, Any]) -> list[pathlib.Path]:
    candidates: list[tuple[int, pathlib.Path]] = []
    agent_usage = result.get("agent_usage", {})
    if isinstance(agent_usage, dict):
        screenshots = [pathlib.Path(str(item)) for item in agent_usage.get("screenshots", []) if str(item).strip()]
        for path in screenshots:
            if path.exists():
                candidates.append((0, path))
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    if project_dir.exists():
        preferred_dirs = [
            project_dir / "static" / "output",
            project_dir / "static" / "generated",
            project_dir / "output",
            project_dir / "outputs",
            project_dir / "generated",
        ]
        for directory in preferred_dirs:
            if directory.exists():
                candidates.extend((1, p) for p in directory.rglob("*.png"))
                candidates.extend((1, p) for p in directory.rglob("*.jpg"))
                candidates.extend((1, p) for p in directory.rglob("*.jpeg"))
    example_outputs = result.get("example_outputs", {})
    if isinstance(example_outputs, dict):
        for key in ("image_preview", "frame_preview"):
            path = pathlib.Path(str(example_outputs.get(key, "")))
            if path.exists():
                candidates.append((2, path))
    online_inputs = result.get("online_input_examples", {})
    if isinstance(online_inputs, dict):
        for item in online_inputs.get("examples", []):
            if isinstance(item, dict) and str(item.get("modality", "")).lower() == "image":
                path = pathlib.Path(str(item.get("local_path", "")))
                if path.exists():
                    candidates.append((4, path))
    for key in ("project_dir", "runtime_dir", "run_dir"):
        raw_root = str(result.get(key, "")).strip()
        if not raw_root:
            continue
        root = pathlib.Path(raw_root)
        if root.exists():
            candidates.extend((3, p) for p in root.rglob("*.png"))
            candidates.extend((3, p) for p in root.rglob("*.jpg"))
            candidates.extend((3, p) for p in root.rglob("*.jpeg"))
    root_pngs = sorted(ROOT.glob("*telegram*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    candidates.extend((5, p) for p in root_pngs[:5])
    unique: dict[str, tuple[int, pathlib.Path]] = {}
    for priority, path in candidates:
        try:
            key = str(path.resolve()).lower()
            existing = unique.get(key)
            if existing is None or priority < existing[0]:
                unique[key] = (priority, path)
        except Exception:
            continue
    valid = [(priority, p) for priority, p in unique.values() if is_valid_image_file(p)]
    return [p for _, p in sorted(valid, key=lambda item: (item[0], -item[1].stat().st_mtime))]


def find_delivery_image(result: dict[str, Any]) -> pathlib.Path | None:
    candidates = delivery_image_candidates(result)
    if not candidates:
        return None
    return candidates[0]


def find_delivery_video(result: dict[str, Any]) -> pathlib.Path | None:
    candidates: list[tuple[int, pathlib.Path]] = []
    agent_usage = result.get("agent_usage", {})
    if isinstance(agent_usage, dict):
        path = pathlib.Path(str(agent_usage.get("workflow_video", "")))
        if path.exists():
            candidates.append((0, path))
    example_outputs = result.get("example_outputs", {})
    if isinstance(example_outputs, dict):
        path = pathlib.Path(str(example_outputs.get("video_preview", "")))
        if path.exists():
            candidates.append((2, path))
    for key in ("project_dir", "runtime_dir", "run_dir"):
        raw_root = str(result.get(key, "")).strip()
        if not raw_root:
            continue
        root = pathlib.Path(raw_root)
        if root.exists():
            candidates.extend((1, p) for p in root.rglob("*.mp4"))
            candidates.extend((1, p) for p in root.rglob("*.webm"))
            candidates.extend((1, p) for p in root.rglob("*.mov"))
    valid = [(priority, p) for priority, p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0]
    if not valid:
        return None
    return sorted(valid, key=lambda item: (item[0], -item[1].stat().st_mtime))[0][1]


def render_project_preview_image(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path | None:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    index = project_dir / "index.html"
    if not index.exists():
        return None
    out = log_dir / f"{safe_id(project_dir.name)}_preview.png"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.goto(index.resolve().as_uri(), wait_until="networkidle")
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    except Exception as exc:
        print(f"preview render failed: {exc}", flush=True)
        return None
    if out.exists() and out.stat().st_size > 0:
        return out
    return None


def wrap_text(text: str, width: int = 36, max_lines: int = 18) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if not clean:
        return []
    lines: list[str] = []
    current = ""
    for ch in clean:
        ch_width = 2 if re.match(r"[\u4e00-\u9fff]", ch) else 1
        cur_width = sum(2 if re.match(r"[\u4e00-\u9fff]", c) else 1 for c in current)
        if cur_width + ch_width > width:
            lines.append(current)
            current = ch
            if len(lines) >= max_lines:
                break
        else:
            current += ch
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def make_delivery_summary_image(result: dict[str, Any], log_dir: pathlib.Path) -> pathlib.Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    out = log_dir / f"{safe_id(result.get('project_dir', 'project'))}_delivery_summary.png"
    facts = project_delivery_facts(result)
    title = pathlib.Path(str(result.get("project_dir", "CGNK Project"))).name or "CGNK Project"
    summary = str(facts.get("effect_report_summary", {}).get("summary", "") if isinstance(facts.get("effect_report_summary"), dict) else "")
    if not summary:
        summary = "项目已生成，运行产物、测试图和效果报告已写入本地目录。"
    files = facts.get("files", [])
    image = Image.new("RGB", (1280, 720), (246, 247, 249))
    draw = ImageDraw.Draw(image)
    try:
        font_title = ImageFont.truetype("arial.ttf", 44)
        font_body = ImageFont.truetype("arial.ttf", 24)
        font_small = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()
    draw.rectangle((0, 0, 1280, 96), fill=(29, 36, 48))
    draw.text((48, 26), title[:52], fill=(255, 255, 255), font=font_title)
    draw.text((48, 132), "生成状态: PASS", fill=(21, 102, 68), font=font_body)
    y = 182
    for line in wrap_text(summary, width=58, max_lines=5):
        draw.text((48, y), line, fill=(42, 50, 64), font=font_body)
        y += 34
    y += 18
    draw.text((48, y), "主要产物", fill=(29, 36, 48), font=font_body)
    y += 38
    for item in [str(row) for row in files[:10]]:
        draw.text((72, y), f"- {item[:80]}", fill=(82, 96, 111), font=font_small)
        y += 28
    draw.text((48, 660), "这是自动生成的交付摘要图；如果项目产出真实截图或视频，会优先发送真实预览。", fill=(82, 96, 111), font=font_small)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out if is_valid_image_file(out) else None


def unique_media_paths(paths: list[pathlib.Path], limit: int = 3) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
        if len(out) >= limit:
            break
    return out


def read_short_file(path: pathlib.Path, limit: int = 1800) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit].strip()


def project_delivery_facts(result: dict[str, Any]) -> dict[str, Any]:
    project_dir = pathlib.Path(str(result.get("project_dir", "")))
    files: list[str] = []
    if project_dir.exists():
        files = [
            str(path.relative_to(project_dir)).replace("\\", "/")
            for path in sorted(project_dir.rglob("*"))
            if path.is_file()
        ][:40]
    runtime_dir = pathlib.Path(str(result.get("runtime_dir", "")))
    effect_report = {}
    effect_path = pathlib.Path(str(result.get("effect_report_path", "")))
    if effect_path.exists():
        try:
            effect_report = json.loads(effect_path.read_text(encoding="utf-8"))
        except Exception:
            effect_report = {"unreadable": str(effect_path)}
    return {
        "project_dir": result.get("project_dir"),
        "runtime_dir": result.get("runtime_dir") or str(runtime_dir),
        "execution_path": result.get("execution_path"),
        "effect_report_path": result.get("effect_report_path"),
        "status": str(result.get("status", "unknown")).upper(),
        "files": files,
        "readme_excerpt": read_short_file(project_dir / "README.md"),
        "test_plan_excerpt": read_short_file(project_dir / "TEST_PLAN.md"),
        "effect_report_summary": effect_report,
        "online_input_examples": result.get("online_input_examples", {}),
        "example_outputs": result.get("example_outputs", {}),
    }


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def build_generation_args(
    chat_id: int | str,
    requirement: str,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
) -> argparse.Namespace:
    slug = f"telegram-live-{safe_id(chat_id)}"
    result_path = log_dir / f"{slug}_generation_result.json"
    return argparse.Namespace(
        requirement=requirement,
        project_slug=f"telegram_{slug}",
        assume_defaults=False,
        allow_network=True,
        allow_provider=True,
        use_api=True,
        use_local_model=False,
        prompt_max_chars=12000,
        model=model,
        timeout=timeout,
        result_path=str(result_path),
        json=True,
        generation_mode="api",
    )


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def generation_subprocess_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "generate_project.py"),
        "--requirement",
        str(args.requirement),
        "--project-slug",
        str(args.project_slug),
        "--prompt-max-chars",
        str(args.prompt_max_chars),
        "--model",
        str(args.model),
        "--timeout",
        str(args.timeout),
        "--result-path",
        str(args.result_path),
        "--json",
    ]
    command.append("--allow-network")
    command.append("--allow-provider")
    command.append("--use-api")
    if bool(getattr(args, "use_local_model", False)):
        command.append("--use-local-model")
    return command


def phase_log_path_for_project(project_slug: str) -> pathlib.Path:
    return ROOT / "examples" / "runtime_runs" / project_slug / "artifacts" / "generation_phase_log.jsonl"


def last_known_phase(phase_log_path: pathlib.Path) -> str:
    if not phase_log_path.exists():
        return ""
    phase = ""
    for line in phase_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("phase"):
            phase = str(doc["phase"])
    return phase


def recent_phase_events(phase_log_path: pathlib.Path, limit: int = 8) -> list[dict[str, Any]]:
    if not phase_log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in phase_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events[-max(1, limit):]


def read_timeout_diagnostics(project_slug: str) -> dict[str, Any]:
    run_dir = ROOT / "examples" / "runtime_runs" / project_slug
    diagnostics_path = run_dir / "agent_usage" / "usage_planning_diagnostics.json"
    if not diagnostics_path.exists():
        return {}
    try:
        doc = json.loads(diagnostics_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"path": str(diagnostics_path), "status": "unreadable", "error": str(exc)}
    if isinstance(doc, dict):
        doc.setdefault("path", str(diagnostics_path))
        return doc
    return {"path": str(diagnostics_path), "status": "invalid"}


def artifact_inventory(project_slug: str, result_path: pathlib.Path, phase_log_path: pathlib.Path) -> tuple[list[str], list[str]]:
    run_dir = ROOT / "examples" / "runtime_runs" / project_slug
    project_dir = ROOT / "generated" / project_slug
    paths = {
        "generation_result.json": result_path,
        "generation_phase_log.jsonl": phase_log_path,
        "product_studio_run.json": run_dir / "artifacts" / "product_studio_run.json",
        "usage_plan.json": run_dir / "agent_usage" / "usage_plan.json",
        "runtime_check.json": run_dir / "agent_usage" / "runtime_check.json",
        "visual_evidence_plan.json": run_dir / "agent_usage" / "visual_evidence_plan.json",
        "usage_planning_diagnostics.json": run_dir / "agent_usage" / "usage_planning_diagnostics.json",
        "README.md": project_dir / "README.md",
    }
    detected: list[str] = []
    missing: list[str] = []
    for name, path in paths.items():
        (detected if path.exists() else missing).append(name)
    return detected, missing


def write_timeout_failure_result(args: argparse.Namespace, timeout_seconds: int, result_path: pathlib.Path) -> dict[str, Any]:
    phase_log_path = phase_log_path_for_project(str(args.project_slug))
    detected, missing = artifact_inventory(str(args.project_slug), result_path, phase_log_path)
    result = {
        "kind": "CustomerProjectGenerationResult",
        "created_at": now(),
        "status": "BLOCKED",
        "reason": "generation subprocess exceeded total timeout",
        "timeout_seconds": timeout_seconds,
        "last_known_phase": last_known_phase(phase_log_path),
        "recent_phase_events": recent_phase_events(phase_log_path),
        "timeout_diagnostics": read_timeout_diagnostics(str(args.project_slug)),
        "artifacts_detected": detected,
        "missing_artifacts": missing,
        "phase_log_path": str(phase_log_path),
        "can_retry": True,
        "retry_should_reuse": [
            "product_studio_run.json",
            "customer_intent.raw_user_message",
            "output_contract",
            "frozen_project_type",
        ],
    }
    write_json(result_path, result)
    write_json(result_path.with_name(result_path.stem.replace("_generation_result", "_failure_result") + ".json"), result)
    return result


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def run_generation_subprocess(args: argparse.Namespace, log_dir: pathlib.Path) -> dict[str, Any]:
    command = generation_subprocess_command(args)
    result_path = pathlib.Path(str(args.result_path))
    timeout_seconds = max(GENERATION_TOTAL_TIMEOUT_SECONDS, int(args.timeout) + 180)
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        failure_result = write_timeout_failure_result(args, timeout_seconds, result_path)
        append_jsonl(
            log_dir / "generation_subprocess.jsonl",
            {
                "created_at": now(),
                "event": "generation_subprocess_timeout",
                "project_slug": str(args.project_slug),
                "timeout_seconds": timeout_seconds,
                "failure_result_path": str(result_path),
                "stdout_tail": str(exc.stdout or "")[-2000:],
                "stderr_tail": str(exc.stderr or "")[-2000:],
            },
        )
        return failure_result
    append_jsonl(
        log_dir / "generation_subprocess.jsonl",
        {
            "created_at": now(),
            "event": "generation_subprocess_finished",
            "project_slug": str(args.project_slug),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        },
    )
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
    if proc.returncode != 0:
        raise RuntimeError(f"generation subprocess failed before writing result: {proc.stderr[-1200:] or proc.stdout[-1200:]}")
    raise RuntimeError("generation subprocess completed without writing result")


def safe_generation_failure_facts(requirement: str, exc: Exception) -> dict[str, Any]:
    error = str(exc)
    category = "generation_pipeline_error"
    user_visible_cause = "后台生成流程中断，项目文件、测试和预览还没有完成。"
    if "prompt_max_chars" in error or "Namespace" in error:
        category = "generation_bridge_configuration_error"
        user_visible_cause = "后台生成入口配置缺少必需参数，流程在进入项目文件生成前中断。"
    elif "context prompt quality failed" in error.lower() or "prompt exceeds max_chars" in error.lower():
        category = "context_prompt_budget_error"
        user_visible_cause = "长期项目记忆和本轮需求压缩后仍超过当前生成上下文预算，流程在进入项目文件生成前中断。"
    elif "timeout" in error.lower():
        category = "generation_timeout"
        user_visible_cause = "后台生成超过本轮总等待时间，项目文件、测试或预览还没有完整返回。"
    elif "api" in error.lower() or "provider" in error.lower():
        category = "provider_generation_error"
        user_visible_cause = "后台生成模型/API 调用中断，项目文件、测试和预览还没有完整返回。"
    return {
        "requirement": requirement,
        "error_category": category,
        "user_visible_cause": user_visible_cause,
        "impact": "No project delivery, tests, screenshots, images, or videos were completed in this run.",
        "next_step": "Keep the captured project memory, fix the backend issue, and retry generation.",
        "technical_error_logged": True,
        "policy": "provider-only; no local template fallback",
    }


def generation_progress_text(elapsed_seconds: int) -> str:
    minutes = max(1, int(round(elapsed_seconds / 60)))
    return (
        f"后台仍在生成中，已运行约 {minutes} 分钟。"
        "我目前只能确认生成流程还没有写出最终交付结果；不会把尚未验证的阶段说成已完成。"
        "完成后我会再发送项目结果、测试状态，以及实际存在的截图/图片/视频预览。"
    )


# LEGACY PROVIDER PIPELINE.
# Telegram mainline must not call this.
# Telegram delivery is now driven by agent_conversation_loop + local_packager + delivery_manifest.
def run_generation_job(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    announce_start: bool = False,
    control_id: str = "",
    generation_mode: str = "api",
) -> None:
    session = load_session(session_dir, chat_id)
    if session.get("generation", {}).get("status") == "running":
        return
    requirement = combined_requirement(session)
    if not requirement:
        if not send_provider_message(
            client,
            chat_id,
            session_dir,
            event="missing_requirement_before_generation",
            session=session,
            facts={"reason": "user asked to generate before a usable project requirement was captured"},
            model=model,
            timeout=timeout,
        ):
            send_customer_reply(
                client,
                chat_id,
                session_dir,
                session,
                event="missing_requirement_before_generation",
                facts={"message": "刚才连接中断了一下。我还没有拿到足够的项目需求，你可以继续描述想做的东西。"},
        )
        return
    if control_id:
        update_backend_control_status(session, control_id, "running")
    session["generation"] = {
        "status": "running",
        "started_at": now(),
        "control_id": control_id,
        "generation_mode": str(generation_mode or "api"),
    }
    append_memory_event(session, "generation_started", data={"requirement": requirement[:6000], "generation_mode": str(generation_mode or "api"), "control_id": control_id})
    save_session(session_dir, session)
    if announce_start:
        send_provider_message(
            client,
            chat_id,
            session_dir,
            event="generation_started",
            session=session,
            facts={
                "requirement": requirement,
                "policy": "provider-only project generation; no local template fallback",
                "important": "Generation has just started. Do not claim tests passed or project completed.",
            },
            model=model,
            timeout=timeout,
        )
        save_session(session_dir, session)
    stop_progress = threading.Event()

    def progress_worker() -> None:
        for step in range(2):
            elapsed = 120 * (step + 1)
            if stop_progress.wait(120):
                return
            current = load_session(session_dir, chat_id)
            if current.get("generation", {}).get("status") != "running":
                return
            text = generation_progress_text(elapsed)
            send_customer_reply(
                client,
                chat_id,
                session_dir,
                current,
                event="generation_progress",
                facts={"elapsed_seconds": elapsed},
                source="generation_progress",
                direct_text=text,
            )

    progress_thread = threading.Thread(target=progress_worker, daemon=True)
    progress_thread.start()

    args = build_generation_args(chat_id, requirement, log_dir, model, timeout, generation_mode)
    try:
        assert_api_generation_ready(generation_mode)
        result = run_generation_subprocess(args, log_dir)
    except Exception as exc:
        stop_progress.set()
        session = load_session(session_dir, chat_id)
        if control_id:
            update_backend_control_status(session, control_id, "failed", reason=str(exc))
        session["generation"] = {"status": "failed", "finished_at": now(), "error": str(exc), "control_id": control_id, "generation_mode": str(generation_mode or "api")}
        safe_facts = safe_generation_failure_facts(requirement, exc)
        append_memory_event(session, "generation_failed", data={"error": str(exc), "safe_facts": safe_facts})
        save_session(session_dir, session)
        log_bridge_error(log_dir, "generation_failed", chat_id, exc, {"requirement": requirement})
        send_provider_or_technical_error(
            client,
            chat_id,
            session_dir,
            event="generation_failed",
            session=session,
            facts=safe_facts,
            model=model,
            timeout=timeout,
            technical_error=str(exc),
        )
        save_session(session_dir, session)
        return

    stop_progress.set()
    session = load_session(session_dir, chat_id)
    status = str(result.get("status", "unknown")).upper()
    session["generation"] = {
        "status": result.get("status", "unknown"),
        "finished_at": now(),
        "result_path": str(args.result_path),
        "control_id": control_id,
        "generation_mode": str(generation_mode or "api"),
    }
    if control_id:
        update_backend_control_status(
            session,
            control_id,
            "completed" if status == "PASS" else ("blocked" if status == "BLOCKED" else "completed"),
            result_path=str(args.result_path),
        )
    if str(result.get("status", "")).lower() == "pass" and isinstance(session.get("whiteboard"), dict):
        session["whiteboard"]["ready_to_generate"] = False
    append_memory_event(
        session,
        "generation_finished",
        data={
            "status": result.get("status", "unknown"),
            "result_path": str(args.result_path),
            "project_dir": result.get("project_dir", ""),
            "runtime_dir": result.get("runtime_dir", ""),
        },
    )
    save_session(session_dir, session)

    if status == "PASS":
        video = find_delivery_video(result)
        image_candidates = delivery_image_candidates(result)
        rendered_image = render_project_preview_image(result, log_dir)
        if rendered_image and is_valid_image_file(rendered_image):
            image_candidates.append(rendered_image)
        if not image_candidates:
            fallback_image = make_delivery_summary_image(result, log_dir)
            if fallback_image:
                image_candidates.append(fallback_image)
        image_candidates = unique_media_paths([p for p in image_candidates if is_valid_image_file(p)], limit=3)
        image = image_candidates[0] if image_candidates else None
        try:
            emit_delivery_evidence(session_dir, session, result, image, log_dir)
            evidence = delivery_evidence_state(read_truth_ledger(session_dir, chat_id))
            send_delivery_artifacts(client, chat_id, session_dir, session, evidence)
        except Exception as exc:
            log_bridge_error(log_dir, "emit_delivery_evidence_failed", chat_id, exc, {"result_path": str(args.result_path)})
        facts = project_delivery_facts(result)
        facts["preview"] = {
            "video_found": bool(video),
            "video_path": str(video) if video else "",
            "image_found": bool(image),
            "image_path": str(image) if image else "",
            "image_count": len(image_candidates),
            "note": "Video preview is available." if video else ("Preview image is available." if image else "No preview artifact was found in this run."),
        }
        send_provider_message(
            client,
            chat_id,
            session_dir,
            event="generation_passed",
            session=session,
            facts=facts,
            model=model,
            timeout=timeout,
        )
        save_session(session_dir, session)
        if video:
            caption = ""
            try:
                caption = provider_user_message(
                    event="test_video_caption",
                    session=session,
                    facts={"video_path": str(video), "purpose": "example-based output preview video"},
                    model=model,
                    timeout=min(timeout, 60),
                )
            except Exception as exc:
                print(f"video caption provider failed: {exc}", flush=True)
            client.send_chat_action(chat_id, "upload_video")
            video_sent = client.send_video(chat_id, video, caption or "")
            if not video_sent:
                log_bridge_error(log_dir, "send_video_failed", chat_id, RuntimeError("video send failed"), {"video": str(video)})
        if image_candidates:
            caption = ""
            try:
                caption = provider_user_message(
                    event="test_image_caption",
                    session=session,
                    facts={"image_paths": [str(path) for path in image_candidates], "purpose": "delivery preview images"},
                    model=model,
                    timeout=min(timeout, 60),
                )
            except Exception as exc:
                print(f"caption provider failed: {exc}", flush=True)
            sent: list[str] = []
            for candidate in image_candidates:
                client.send_chat_action(chat_id, "upload_photo")
                if client.send_photo(chat_id, candidate, caption or ""):
                    sent.append(str(candidate))
                    caption = ""
            if not sent:
                log_bridge_error(log_dir, "send_photo_failed", chat_id, RuntimeError("all image candidates failed"), {"candidates": [str(p) for p in image_candidates]})
            else:
                append_memory_event(session, "preview_media_sent", data={"video": str(video) if video else "", "images": sent})
                save_session(session_dir, session)
    elif status == "BLOCKED":
        can_retry = mark_generation_retry(session, reason=str(result.get("reason", "")))
        append_truth_ledger(
            session_dir,
            session,
            "blocked",
            "本地生成流程返回 BLOCKED",
            status="BLOCKED",
            evidence_ref=str(result.get("phase_log_path", "")),
            data={"artifact": "blocked", "reason": str(result.get("reason", ""))},
        )
        if control_id and can_retry:
            update_backend_control_status(session, control_id, "queued", reason="auto_retry_after_blocked", result_path=str(args.result_path))
            session["generation"]["status"] = "queued"
            save_session(session_dir, session)
            threading.Thread(
                target=run_generation_job,
                args=(client, chat_id, session_dir, log_dir, model, timeout),
                kwargs={"announce_start": False, "control_id": control_id, "generation_mode": generation_mode},
                daemon=True,
            ).start()
            return
        if not can_retry:
            append_truth_ledger(
                session_dir,
                session,
                "local_retry_exhausted",
                "本地重试次数已耗尽，可以允许升级处理",
                status="pass",
                evidence_ref=str(result.get("phase_log_path", "")),
                data={"artifact": "local_retry_exhausted"},
            )
            if control_id:
                update_backend_control_status(session, control_id, "blocked", reason="local_retry_exhausted", result_path=str(args.result_path))
            save_session(session_dir, session)
        text = product_studio_reply.compose_timeout_or_blocked_reply(result)
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="generation_blocked",
            facts={"status": status, "result": result},
            source="product_studio_reply_composer",
            direct_text=text,
        )
    else:
        send_provider_message(
            client,
            chat_id,
            session_dir,
            event="generation_completed_non_pass",
            session=session,
            facts={
                "status": status,
                "project_dir": result.get("project_dir"),
                "execution_path": result.get("execution_path"),
            },
            model=model,
            timeout=timeout,
        )
        save_session(session_dir, session)

def run_agent_generation_job(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool = False,
    max_turns: int = 12,
) -> None:
    session = load_session(session_dir, chat_id)
    requirement = combined_requirement(session)
    if not requirement:
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="missing_requirement_before_generation",
            facts={"message": "我还没有拿到足够的项目需求。你先描述想做的东西、输入和希望看到的结果。"},
        )
        return
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    generation.update({"status": "running", "driver": "agent_conversation_loop", "started_at": generation.get("started_at") or now()})
    session["generation"] = generation
    append_memory_event(session, "agent_loop_started", data={"requirement": requirement[:6000]})
    append_truth_ledger(
        session_dir,
        session,
        "agent_loop_started",
        "Agent conversation loop started directly from Telegram confirmation",
        evidence_ref=str(agent_session_path(session_dir, chat_id)),
        data={"artifact": "agent_session", "backend_controls_required": False},
    )
    save_session(session_dir, session)
    if announce_start:
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="generation_started",
            facts={"message": "我开始按这版需求生成项目。完成后会发送本地打包出来的项目 zip 和说明。"},
        )
    project_dir = log_dir / "agent_projects" / safe_id(chat_id)
    try:
        result = agent_conversation_loop.run_agent_loop(
            session_path=agent_session_path(session_dir, chat_id),
            project_dir=project_dir,
            model=model,
            timeout=timeout,
            max_turns=max_turns,
        )
    except Exception as exc:
        session = load_session(session_dir, chat_id)
        session["generation"] = {"status": "failed", "driver": "agent_conversation_loop", "finished_at": now(), "error": str(exc)}
        append_agent_session_event(session_dir, chat_id, {"kind": "agent_loop_error", "role": "tool", "error": str(exc)})
        append_memory_event(session, "agent_loop_failed", data={"error": str(exc)})
        save_session(session_dir, session)
        log_bridge_error(log_dir, "agent_loop_failed", chat_id, exc, {"project_dir": str(project_dir)})
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="generation_failed",
            facts={"message": "生成过程这次中断了；我已经把失败结果写回会话记录，后续可以从同一会话继续修复。"},
        )
        return
    finish_agent_loop_delivery(client, chat_id, session_dir, project_dir, result)


def finish_agent_loop_delivery(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    project_dir: pathlib.Path,
    result: dict[str, Any],
) -> None:
    manifest = result.get("manifest", {}) if isinstance(result.get("manifest"), dict) else {}
    if not manifest and result.get("manifest_path"):
        manifest = read_delivery_manifest(str(result.get("manifest_path", "")))
    session = load_session(session_dir, chat_id)
    session["generation"] = {
        "status": str(result.get("status", "unknown")),
        "driver": "agent_conversation_loop",
        "finished_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, chat_id)),
        "project_dir": str(project_dir),
        "manifest_path": str(manifest.get("manifest_path", result.get("manifest_path", ""))),
        "package_path": str(manifest.get("package_path", result.get("package_path", ""))),
    }
    append_memory_event(session, "agent_loop_finished", data={"result": result, "manifest": manifest})
    save_session(session_dir, session)
    if manifest and str(manifest.get("package_path", "")).strip():
        send_delivery_from_manifest(client, chat_id, session_dir, session, manifest)
    else:
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="generation_completed_non_pass",
            facts={"message": "这轮生成还没有拿到本地 packager 产出的项目包，我已把过程写入会话记录供下一轮继续。"},
        )


def start_agent_generation(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool,
    reason: str = "frontdesk_generation_confirmation",
) -> None:
    session = load_session(session_dir, chat_id)
    requirement = combined_requirement(session)
    if not requirement:
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="missing_requirement_before_generation",
            facts={"message": "我还没有拿到足够的项目需求。你先描述想做的东西、输入和希望看到的结果。"},
        )
        return
    update_active_run_status(session, "running", driver="agent_conversation_loop")
    session["generation"] = {
        "status": "running",
        "driver": "agent_conversation_loop",
        "started_at": now(),
        "agent_session_path": str(agent_session_path(session_dir, chat_id)),
    }
    save_session(session_dir, session)
    client.send_chat_action(chat_id, "typing")
    threading.Thread(
        target=run_agent_generation_job,
        args=(client, chat_id, session_dir, log_dir, model, timeout),
        kwargs={"announce_start": announce_start},
        daemon=True,
    ).start()


def queue_generation_job_legacy_disabled(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    announce_start: bool,
    generation_mode: str = "api",
) -> None:
    # Legacy compatibility only. Telegram mainline must not call this.
    start_agent_generation(
        client,
        chat_id,
        session_dir,
        log_dir,
        model,
        timeout,
        announce_start=announce_start,
        reason="legacy_queue_generation_job_redirect",
    )


def auto_start_pending_intakes(
    client: TelegramClient,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    *,
    allowed_chat: str = "",
    generation_mode: str = "api",
) -> int:
    session_paths = [session_path(session_dir, allowed_chat)] if allowed_chat else sorted(session_dir.glob("*.json"))
    started = 0
    for path in session_paths:
        if not path.exists() or path.name.endswith(".truth_ledger.jsonl"):
            continue
        chat_id = path.stem
        session = load_session(session_dir, chat_id)
        run = active_run(session) or {}
        generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
        status = str(generation.get("status", "idle")).lower()
        if status not in {"idle", "unstarted"}:
            continue
        if str(run.get("status", "")).lower() != "intake_open":
            continue
        if not combined_requirement(session):
            continue
        start_agent_generation(
            client,
            chat_id,
            session_dir,
            log_dir,
            model,
            timeout,
            announce_start=False,
            reason="startup_pending_intake",
        )
        started += 1
    return started


def continue_customer_turn(
    client: TelegramClient,
    chat_id: int | str,
    session: dict[str, Any],
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    context: dict[str, Any] | None = None,
) -> None:
    latest = latest_user_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    if latest:
        whiteboard = merge_whiteboard(
            whiteboard,
            {
                "project_summary": str(whiteboard.get("project_summary", "") or latest),
                "known_facts": [f"用户补充: {latest}"],
                "decision_log": ["本轮由 Human Frontdesk 记录补充，agent loop 会读取同一个 agent_session 继续推进。"],
            },
        )
        session["whiteboard"] = enforce_backend_updates_from_user_text(session, whiteboard)
        append_whiteboard_version(session, session["whiteboard"])
        append_memory_event(session, "whiteboard_revision", data={"source": "local_frontdesk", "latest_user_text": latest[:1200]})
        generation_status = str(session.get("generation", {}).get("status", "idle")).lower() if isinstance(session.get("generation"), dict) else "idle"
        action = "revise_generation_scope" if generation_status in {"queued", "running"} else "update_project_context"
        append_backend_control(
            session_dir,
            session,
            action,
            payload={
                "latest_user_text": latest[:4000],
                "whiteboard": session["whiteboard"],
                "requirement": combined_requirement(session)[:12000],
            },
            status="logged",
            reason="user_project_update",
        )
    memo = append_backend_memo(
        session_dir,
        session,
        "project_update",
        "我已把用户补充写进项目白板和 agent session；backend_controls 只作为日志，不作为生成入口。",
    )
    send_customer_reply(
        client,
        chat_id,
        session_dir,
        session,
        event="project_update",
        facts={"message": "我已记下这条补充，会按最新方向继续推进。没有可运行结果、预览或测试结论前，不会说已经完成。"},
    )


def handle_text(
    client: TelegramClient,
    chat_id: int | str,
    text: str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    generation_mode: str = "api",
) -> None:
    session = load_session(session_dir, chat_id)
    text = text.strip()
    if text:
        append_agent_session_event(session_dir, chat_id, {"kind": "user", "role": "user", "text": text})
    classification = classify_customer_message(text, session)
    append_truth_ledger(
        session_dir,
        session,
        "message_classification",
        "用户消息入口已先分类",
        evidence_ref=str(classification.get("intent", "")),
        data={"artifact": "message_classification", "classification": classification},
    )
    if text == "/new":
        clear_result = clear_chat_history(chat_id, session_dir, log_dir, include_outputs=False, delete=False)
        session = default_session(chat_id)
        append_memory_event(session, "session_reset", "/new", {"clear_result": clear_result})
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n你可以直接发新的项目想法。"},
        )
        return
    if text in {"/reset", "/restart"}:
        clear_result = clear_chat_history(chat_id, session_dir, log_dir, include_outputs=True, delete=False)
        session = default_session(chat_id)
        append_memory_event(session, "session_reset", text, {"clear_result": clear_result})
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n项目会话已重启，你可以从一句新需求开始。"},
        )
        return
    if text == "/delete_history":
        clear_result = clear_chat_history(chat_id, session_dir, log_dir, include_outputs=True, delete=True)
        session = default_session(chat_id)
        append_memory_event(session, "session_deleted", text, {"clear_result": clear_result})
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="admin_command",
            facts={"message": reset_summary_text(clear_result) + "\n已打开空白会话。"},
        )
        return
    if text == "/help":
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="admin_command",
            facts={
                "message": (
                    "可用命令：\n"
                    "/status 查看后台生成状态\n"
                    "/new 归档当前对话并开新会话\n"
                    "/reset 归档当前对话和本轮生成历史后重启\n"
                    "/delete_history 永久删除当前对话和本轮生成历史\n"
                    "平时直接描述项目需求即可；生成完成后我会直接发结果、图片或视频预览。"
                )
            },
        )
        return

    session.setdefault("messages", []).append({"role": "user", "text": text, "created_at": now(), "classification": classification})
    append_memory_event(session, "user_message", text, {"classification": classification})
    save_session(session_dir, session)

    intent = str(classification.get("intent", ""))
    if intent == "greeting":
        send_customer_reply(client, chat_id, session_dir, session, event="greeting")
        return
    if intent == "status_query":
        evidence = delivery_evidence_state(read_truth_ledger(session_dir, chat_id))
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="status_requested",
            facts={"generation": session.get("generation", {}), "evidence_state": evidence},
            backend_memo=latest_backend_memo(session),
        )
        return

    pending = current_pending_decision(session)
    if pending and intent not in {"admin_command", "greeting", "status_query", "generation_confirmation"}:
        if not pending.get("asked_at"):
            pending["asked_at"] = now()
            session["pending_decision"] = pending
            update_active_run_status(session, "waiting_decision")
            append_backend_control(
                session_dir,
                session,
                "wait_for_user_decision",
                payload={"question": pending["question"], "whiteboard": session.get("whiteboard", {})},
                status="logged",
                reason="blocking_question",
            )
            append_backend_memo(session_dir, session, "pending_decision", f"需要用户先确认关键问题：{pending['question']}")
            send_customer_reply(
                client,
                chat_id,
                session_dir,
                session,
                event="pending_decision",
                facts={"question": pending["question"]},
            )
            return
        pending["status"] = "resolved"
        pending["answer"] = text
        pending["resolved_at"] = now()
        session["pending_decision"] = pending
        whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
        questions = whiteboard.get("blocking_questions", []) if isinstance(whiteboard.get("blocking_questions"), list) else []
        whiteboard["blocking_questions"] = questions[1:]
        whiteboard["known_facts"] = unique_strings(list(whiteboard.get("known_facts", [])) + [f"用户确认关键问题: {text}"])
        session["whiteboard"] = whiteboard
        update_active_run_status(session, "intake_open", driver="frontdesk_intake")
        append_backend_control(
            session_dir,
            session,
            "user_decision_resolved",
            payload={"answer": text, "whiteboard": whiteboard},
            status="logged",
            reason="blocking_question_answered",
        )

    if intent == "new_project_request":
        ticket = create_intake_ticket(session_dir, session, text)
        run = create_active_run(session, ticket, text)
        append_backend_control(
            session_dir,
            session,
            "open_intake",
            payload={"raw_user_message": text, "whiteboard": session.get("whiteboard", {})},
            status="logged",
            reason="new_project_request",
        )
        append_truth_ledger(
            session_dir,
            session,
            "active_run_bound",
            "Telegram chat_id 已绑定 active run",
            evidence_ref=str(run.get("id", "")),
            data={"artifact": "active_run", "run_id": run.get("id", ""), "ticket_id": ticket.get("id", "")},
        )
        append_truth_ledger(
            session_dir,
            session,
            "parallel_generation_requested",
            "新需求已进入 agent_session，会等待用户确认后启动 agent loop",
            evidence_ref=str(run.get("id", "")),
            data={"artifact": "agent_session_intake", "auto_start": False},
        )
        memo = append_backend_memo(
            session_dir,
            session,
            "intake",
            "我这边已经把新需求写入 agent session；等待用户确认后直接启动 AgentConversationLoop，backend_controls 只保留为日志。",
        )
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="intake_ticket_created",
            facts={"project_summary": text, "backend_parallel_started": False},
        )
        return

    if intent == "generation_confirmation":
        start_agent_generation(
            client,
            chat_id,
            session_dir,
            log_dir,
            model,
            timeout,
            announce_start=True,
        )
        return

    if intent == "escalation_request":
        append_truth_ledger(
            session_dir,
            session,
            "provider_escalation_note",
            "用户升级请求已作为会话上下文记录，不再作为正式生成 gate",
            status="observed",
            evidence_ref="escalation_request",
            data={"artifact": "escalation_note"},
        )
        append_backend_control(
            session_dir,
            session,
            "escalation_note",
            payload={"classification": classification, "whiteboard": session.get("whiteboard", {})},
            status="logged",
            reason="user_requested_escalation_context",
        )
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="project_update",
            facts={"message": "收到，我会把这条升级诉求写进同一个生成会话，正式生成仍由 agent loop 连续推进。"},
        )
        return

    continue_customer_turn(client, chat_id, session, session_dir, log_dir, model, timeout, {"text": text})


def handle_attachment_message(
    client: TelegramClient,
    chat_id: int | str,
    message: dict[str, Any],
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    upload_dir: pathlib.Path,
    model: str,
    timeout: int,
) -> None:
    session = load_session(session_dir, chat_id)
    client.send_chat_action(chat_id, "upload_document")
    try:
        attachments, skipped = download_message_attachments(client, chat_id, message, upload_dir)
    except Exception as exc:
        log_bridge_error(log_dir, "attachment_download_failed", chat_id, exc, {"message_id": message.get("message_id")})
        send_customer_reply(
            client,
            chat_id,
            session_dir,
            session,
            event="attachment_download_failed",
            facts={"message": "我这边接到上传消息了，但刚才下载文件时连接中断。你可以重新发一次，或者先用文字补充这个资料的用途。"},
        )
        return
    if not attachments:
        if skipped:
            append_memory_event(session, "user_attachment_skipped", data={"skipped": skipped})
            send_customer_reply(
                client,
                chat_id,
                session_dir,
                session,
                event="attachment_skipped",
                facts={"message": "我收到了上传消息，但文件太大或 Telegram 没有返回可下载路径。你可以换成小一点的文件，或先用文字描述关键内容。", "skipped": skipped},
            )
            return
        if send_provider_message(
            client,
            chat_id,
            session_dir,
            event="unsupported_attachment_received",
            session=session,
            facts={"message_type": "non_text", "supported": ["photo", "document", "video", "animation", "audio", "voice"]},
            model=model,
            timeout=timeout,
        ):
            save_session(session_dir, session)
        else:
            send_customer_reply(
                client,
                chat_id,
                session_dir,
                session,
                event="unsupported_attachment_received",
                facts={"message": "我收到了非文本消息。现在可直接接收图片、文档、视频、音频这几类资料；你也可以补一句它们要怎么用于项目。"},
            )
        return
    if skipped:
        append_memory_event(session, "user_attachment_partially_skipped", data={"skipped": skipped})
    record_attachments_as_project_input(session, attachments)
    caption = str(message.get("caption", "")).strip()
    user_text = attachment_user_text(attachments, caption)
    session.setdefault("messages", []).append(
        {
            "role": "user",
            "text": user_text,
            "created_at": now(),
            "attachments": [item.get("local_path", "") for item in attachments],
        }
    )
    append_memory_event(
        session,
        "user_message",
        user_text,
        {"source": "attachment_message", "attachment_count": len(attachments)},
    )
    save_session(session_dir, session)
    continue_customer_turn(
        client,
        chat_id,
        session,
        session_dir,
        log_dir,
        model,
        timeout,
        {"attachments": recent_attachments({"attachments": attachments}, limit=len(attachments))},
    )


def run(args: argparse.Namespace) -> None:
    token = resolve_token(args.token)
    client = TelegramClient(token, args.http_timeout)
    session_dir = pathlib.Path(args.session_dir).resolve()
    log_dir = pathlib.Path(args.log_dir).resolve()
    upload_dir = pathlib.Path(args.upload_dir).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    allowed_chat = str(args.chat_id).strip()
    offset = int(args.offset)
    print(f"TELEGRAM_ONLY_BRIDGE: running chat_id={allowed_chat or '*'} session_dir={session_dir}", flush=True)
    auto_started = auto_start_pending_intakes(
        client,
        session_dir,
        log_dir,
        args.model,
        args.generation_timeout,
        allowed_chat=allowed_chat,
        generation_mode=args.generation_mode,
    )
    if auto_started:
        print(f"TELEGRAM_ONLY_BRIDGE: auto_started_pending_intakes={auto_started}", flush=True)
    while True:
        try:
            updates = client.get_updates(offset, args.poll_timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
            print(f"poll failed: {client.redact_for_log(exc)}", flush=True)
            time.sleep(args.retry_delay)
            continue
        for update in updates:
            update_id = int(update.get("update_id", 0))
            offset = max(offset, update_id + 1)
            message = update.get("message") or update.get("edited_message") or {}
            if not isinstance(message, dict):
                continue
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is None:
                continue
            if allowed_chat and str(chat_id) != allowed_chat:
                continue
            text = str(message.get("text", "")).strip()
            if not text:
                handle_attachment_message(
                    client,
                    chat_id,
                    message,
                    session_dir,
                    log_dir,
                    upload_dir,
                    args.model,
                    args.generation_timeout,
                )
                continue
            handle_text(client, chat_id, text, session_dir, log_dir, args.model, args.generation_timeout, args.generation_mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram-only CGNK customer-service bridge.")
    parser.add_argument("--token", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--session-dir", default=str(DEFAULT_SESSION_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--upload-dir", default=str(DEFAULT_UPLOAD_DIR))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1"))
    parser.add_argument("--generation-timeout", type=int, default=420)
    parser.add_argument("--generation-mode", choices=["simulator", "api"], default=os.environ.get("CGNK_TELEGRAM_GENERATION_MODE", "api"))
    parser.add_argument("--http-timeout", type=int, default=35)
    parser.add_argument("--poll-timeout", type=int, default=20)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
