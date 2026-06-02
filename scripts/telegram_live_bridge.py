#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import check_connectivity
import generate_project


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SESSION_DIR = ROOT / "examples" / "test_results" / "telegram_live_sessions"
DEFAULT_LOG_DIR = ROOT / "examples" / "test_results" / "telegram_live_logs"
POLICY_PATH = ROOT / "config" / "customer_agent_policy.md"

DEFAULT_CUSTOMER_AGENT_POLICY = """# Customer Agent Policy

The assistant behaves like a product design and engineering partner, not a form-based customer support script.

- Understand the user's goal first, then propose a first-version product and technical plan.
- Infer reasonable defaults for optional fields instead of asking the user to fill every field.
- Ask only questions that block generation.
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
        self.base = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout
        try:
            import requests

            self.session = requests.Session()
        except Exception:
            self.session = None

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
            raise RuntimeError(f"Telegram {method} transport failed: {last_exc}")
        if not isinstance(doc, dict) or not doc.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {doc}")
        return doc

    def send_message(self, chat_id: int | str, text: str) -> None:
        self.call(
            "sendMessage",
            {
                "chat_id": str(chat_id),
                "text": text[:3900],
                "disable_web_page_preview": "true",
            },
        )

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

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        if not path.exists() or not path.is_file():
            return False
        boundary = "----CGNKTelegramBoundary"
        fields = {"chat_id": str(chat_id), "caption": caption[:900], "supports_streaming": "true"}
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
                "Content-Type: video/mp4\r\n\r\n"
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
                            files={"video": (path.name, fh, "video/mp4")},
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
        "whiteboard": {
            "project_summary": "",
            "known_facts": [],
            "open_questions": [],
            "default_assumptions": [],
            "first_version_plan": [],
            "blocking_questions": [],
            "ready_to_generate": False,
        },
        "generation": {"status": "idle"},
    }


def session_path(session_dir: pathlib.Path, chat_id: int | str) -> pathlib.Path:
    return session_dir / f"{safe_id(chat_id)}.json"


def load_session(session_dir: pathlib.Path, chat_id: int | str) -> dict[str, Any]:
    return read_json(session_path(session_dir, chat_id), default_session(chat_id))


def save_session(session_dir: pathlib.Path, session: dict[str, Any]) -> None:
    session["updated_at"] = now()
    write_json(session_path(session_dir, session.get("chat_id", "")), session)


def combined_requirement(session: dict[str, Any]) -> str:
    whiteboard = session.get("whiteboard", {})
    if isinstance(whiteboard, dict):
        parts: list[str] = []
        summary = str(whiteboard.get("project_summary", "")).strip()
        if summary:
            parts.append(summary)
        for key, label in (
            ("known_facts", "已确认事实"),
            ("default_assumptions", "默认假设"),
            ("first_version_plan", "第一版方案"),
        ):
            values = whiteboard.get(key, [])
            lines = [f"- {item}" for item in values if isinstance(item, str) and item.strip()]
            if lines:
                parts.append(label + ":\n" + "\n".join(lines))
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
    system = """你是 CGNK 的 Telegram 项目设计助手，更像产品合伙人，不是表单客服。
你的目标是把用户的一句话想法主动发展成可生成的第一版项目方案。

核心策略：
- 不要逐项审问字段，不要“复述一句再问一个缺口”的客服脚本。
- 先做专业判断：拆解产品层、技术层、默认方案和第一版边界。
- 对可默认的信息直接给默认假设并继续，不要阻塞用户。
- 只有缺失信息会导致完全无法生成时，才问一个阻塞问题。
- 输出要体现你懂这个项目。例如游戏视频高光项目，应主动给出视频输入、事件检测、高光评分、剪辑导出、MP4/H.264、通用信号检测等方案。
- 不要要求用户回复固定口令，不要写“请回复开始生成”。
- 如果信息足以生成第一版，回复里自然说明“我按这个方向开始做第一版”，并把 action 设为 "start_generation"。
- 当 action 是 "start_generation" 时，reply 不能只有一句“开始做”；要简短列出将生成的第一版能力、默认假设和测试/预览目标。
- 如果用户只是第一次提出项目想法，先给出你建议的第一版方案和默认假设，通常不要立刻启动生成；等用户继续补充、确认方向或没有提出硬性限制后，再把 action 设为 "start_generation"。
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
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
        *recent_dialogue(session),
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
    if bool(next_whiteboard.get("ready_to_generate")) and not next_whiteboard.get("blocking_questions"):
        action = "start_generation"
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
    system = """你是 CGNK 的真实 Telegram 项目设计与交付助手。
根据事件和事实生成一条自然、简短、像人力产品/工程搭档的中文消息。

规则：
- 不要使用固定口令、模板腔、机器人流程话术。
- 不要要求用户回复固定词，例如“开始生成”。
- 不要暴露内部模块名。
- 如果是交付结果，不要只报路径；要概括本次项目做了什么、测试是否通过、用户能看到什么效果、缺了什么预览、下一步建议。
- 交付结果里可以保留关键路径和状态，方便用户检查，但路径不是主体。
- 如果没有截图或预览，解释为“本轮测试没有产出 preview artifact”，并建议下一步补预览图/短视频任务。
- 如果是失败，面向用户说明影响和下一步，不要贴底层堆栈；不要承诺本地模板兜底。
- 只输出要发给用户的一条消息，不要 JSON，不要 Markdown 表格。
"""
    system += "\n\n当前热加载行为策略如下，必须优先遵守：\n" + policy
    payload = {
        "event": event,
        "facts": facts,
        "whiteboard": session.get("whiteboard", {}),
        "recent_dialogue": recent_dialogue(session, limit=8),
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
    session.setdefault("messages", []).append({"role": "assistant", "text": text, "created_at": now(), "source": "provider_user_message"})
    client.send_message(chat_id, text)
    return True


def send_provider_or_technical_error(
    client: TelegramClient,
    chat_id: int | str,
    *,
    event: str,
    session: dict[str, Any],
    facts: dict[str, Any],
    model: str,
    timeout: int,
    technical_error: str,
) -> None:
    if send_provider_message(client, chat_id, event=event, session=session, facts=facts, model=model, timeout=timeout):
        return
    client.send_message(chat_id, "刚才连接中断了一下，我已经把问题记录下来了。你可以继续补充需求，我会接着处理。")


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


def run_generation_job(
    client: TelegramClient,
    chat_id: int | str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
    announce_start: bool = False,
) -> None:
    session = load_session(session_dir, chat_id)
    if session.get("generation", {}).get("status") == "running":
        return
    requirement = combined_requirement(session)
    if not requirement:
        if not send_provider_message(
            client,
            chat_id,
            event="missing_requirement_before_generation",
            session=session,
            facts={"reason": "user asked to generate before a usable project requirement was captured"},
            model=model,
            timeout=timeout,
        ):
            client.send_message(chat_id, "刚才连接中断了一下。我还没有拿到足够的项目需求，你可以继续描述想做的东西。")
        return
    session["generation"] = {"status": "running", "started_at": now()}
    save_session(session_dir, session)
    if announce_start:
        send_provider_message(
            client,
            chat_id,
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
        for step in range(3):
            if stop_progress.wait(75):
                return
            current = load_session(session_dir, chat_id)
            if current.get("generation", {}).get("status") != "running":
                return
            if send_provider_message(
                client,
                chat_id,
                event="generation_progress",
                session=current,
                facts={
                    "elapsed_seconds_lower_bound": 75 * (step + 1),
                    "status": "still_running",
                    "current_stage": "online example input, provider generation, validation, preview artifact creation",
                    "message_policy": "progress heartbeat; do not claim completion",
                },
                model=model,
                timeout=timeout,
            ):
                save_session(session_dir, current)

    progress_thread = threading.Thread(target=progress_worker, daemon=True)
    progress_thread.start()

    slug = f"telegram-live-{safe_id(chat_id)}"
    result_path = log_dir / f"{slug}_generation_result.json"
    args = argparse.Namespace(
        requirement=requirement,
        project_slug=f"telegram_{slug}",
        assume_defaults=False,
        allow_network=True,
        allow_provider=True,
        use_api=True,
        model=model,
        timeout=timeout,
        result_path=str(result_path),
        json=True,
    )
    try:
        result = generate_project.run_generation(args)
    except Exception as exc:
        stop_progress.set()
        session = load_session(session_dir, chat_id)
        session["generation"] = {"status": "failed", "finished_at": now(), "error": str(exc)}
        save_session(session_dir, session)
        log_bridge_error(log_dir, "generation_failed", chat_id, exc, {"requirement": requirement})
        send_provider_or_technical_error(
            client,
            chat_id,
            event="generation_failed",
            session=session,
            facts={
                "requirement": requirement,
                "error": str(exc),
                "policy": "provider-only; no local template fallback",
            },
            model=model,
            timeout=timeout,
            technical_error=str(exc),
        )
        save_session(session_dir, session)
        return

    stop_progress.set()
    session = load_session(session_dir, chat_id)
    session["generation"] = {"status": result.get("status", "unknown"), "finished_at": now(), "result_path": str(result_path)}
    save_session(session_dir, session)

    status = str(result.get("status", "unknown")).upper()
    if status == "PASS":
        video = find_delivery_video(result)
        image_candidates = delivery_image_candidates(result)
        rendered_image = render_project_preview_image(result, log_dir)
        if rendered_image and is_valid_image_file(rendered_image):
            image_candidates.append(rendered_image)
        image = image_candidates[0] if image_candidates else None
        facts = project_delivery_facts(result)
        facts["preview"] = {
            "video_found": bool(video),
            "video_path": str(video) if video else "",
            "image_found": bool(image),
            "image_path": str(image) if image else "",
            "note": "Video preview is available." if video else ("Preview image is available." if image else "No preview artifact was found in this run."),
        }
        send_provider_message(
            client,
            chat_id,
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
            video_sent = client.send_video(chat_id, video, caption or "")
            if not video_sent:
                log_bridge_error(log_dir, "send_video_failed", chat_id, RuntimeError("video send failed"), {"video": str(video)})
            if image_candidates:
                image_caption = ""
                try:
                    image_caption = provider_user_message(
                        event="test_image_caption",
                        session=session,
                        facts={"image_path": str(image_candidates[0]), "purpose": "still image preview for the generated project"},
                        model=model,
                        timeout=min(timeout, 60),
                    )
                except Exception as exc:
                    print(f"image caption provider failed: {exc}", flush=True)
                sent = False
                for candidate in image_candidates:
                    if client.send_photo(chat_id, candidate, image_caption or ""):
                        sent = True
                        break
                if not sent:
                    log_bridge_error(log_dir, "send_photo_failed", chat_id, RuntimeError("all image candidates failed"), {"candidates": [str(p) for p in image_candidates]})
        elif image:
            caption = ""
            try:
                caption = provider_user_message(
                    event="test_image_caption",
                    session=session,
                    facts={"image_path": str(image), "purpose": "delivery test screenshot"},
                    model=model,
                    timeout=min(timeout, 60),
                )
            except Exception as exc:
                print(f"caption provider failed: {exc}", flush=True)
            sent = False
            for candidate in image_candidates:
                if client.send_photo(chat_id, candidate, caption or ""):
                    sent = True
                    break
            if not sent:
                log_bridge_error(log_dir, "send_photo_failed", chat_id, RuntimeError("all image candidates failed"), {"candidates": [str(p) for p in image_candidates]})
    else:
        send_provider_message(
            client,
            chat_id,
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


def handle_text(
    client: TelegramClient,
    chat_id: int | str,
    text: str,
    session_dir: pathlib.Path,
    log_dir: pathlib.Path,
    model: str,
    timeout: int,
) -> None:
    session = load_session(session_dir, chat_id)
    text = text.strip()
    if text == "/new":
        session = default_session(chat_id)
        save_session(session_dir, session)
        if send_provider_message(
            client,
            chat_id,
            event="new_session",
            session=session,
            facts={"command": "/new", "purpose": "start a fresh Telegram customer-service conversation"},
            model=model,
            timeout=timeout,
        ):
            save_session(session_dir, session)
        else:
            client.send_message(chat_id, "刚才连接中断了一下。新会话已经打开，你可以直接继续说项目想法。")
        return
    if text == "/status":
        generation = session.get("generation", {})
        if send_provider_message(
            client,
            chat_id,
            event="status_requested",
            session=session,
            facts={"generation": generation},
            model=model,
            timeout=timeout,
        ):
            save_session(session_dir, session)
        else:
            client.send_message(chat_id, "刚才连接中断了一下，状态说明没能生成。我已经记录了这个问题。")
        return

    session.setdefault("messages", []).append({"role": "user", "text": text, "created_at": now()})
    save_session(session_dir, session)

    if is_generate_command(text) or is_human_start_confirmation(text, session):
        thread = threading.Thread(
            target=run_generation_job,
            args=(client, chat_id, session_dir, log_dir, model, timeout, False),
            daemon=True,
        )
        thread.start()
        return

    try:
        reply, whiteboard, action = customer_service_reply(session, model, min(timeout, 60))
    except Exception as exc:
        log_bridge_error(log_dir, "customer_service_failed", chat_id, exc, {"text": text})
        print(f"customer service provider failed: {exc}", flush=True)
        client.send_message(chat_id, "刚才连接中断了一下。你这句我已经记下来了，可以继续补充，我会接着整理方案。")
        return
    if isinstance(whiteboard, dict):
        session["whiteboard"] = whiteboard
    session.setdefault("messages", []).append({"role": "assistant", "text": reply, "created_at": now()})
    save_session(session_dir, session)
    client.send_message(chat_id, reply)
    if action == "start_generation":
        thread = threading.Thread(
            target=run_generation_job,
            args=(client, chat_id, session_dir, log_dir, model, timeout, False),
            daemon=True,
        )
        thread.start()


def run(args: argparse.Namespace) -> None:
    token = resolve_token(args.token)
    client = TelegramClient(token, args.http_timeout)
    session_dir = pathlib.Path(args.session_dir).resolve()
    log_dir = pathlib.Path(args.log_dir).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    allowed_chat = str(args.chat_id).strip()
    offset = int(args.offset)
    print(f"TELEGRAM_ONLY_BRIDGE: running chat_id={allowed_chat or '*'} session_dir={session_dir}", flush=True)
    while True:
        try:
            updates = client.get_updates(offset, args.poll_timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            print(f"poll failed: {exc}", flush=True)
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
                session = load_session(session_dir, chat_id)
                if send_provider_message(
                    client,
                    chat_id,
                    event="non_text_message_received",
                    session=session,
                    facts={"message_type": "non_text", "policy": "text-only project requirement intake"},
                    model=args.model,
                    timeout=args.generation_timeout,
                ):
                    save_session(session_dir, session)
                else:
                    client.send_message(chat_id, "刚才连接中断了一下。我这边主要根据文字整理项目需求，你可以用文字继续补充。")
                continue
            handle_text(client, chat_id, text, session_dir, log_dir, args.model, args.generation_timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram-only CGNK customer-service bridge.")
    parser.add_argument("--token", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--session-dir", default=str(DEFAULT_SESSION_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1"))
    parser.add_argument("--generation-timeout", type=int, default=420)
    parser.add_argument("--http-timeout", type=int, default=35)
    parser.add_argument("--poll-timeout", type=int, default=20)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
