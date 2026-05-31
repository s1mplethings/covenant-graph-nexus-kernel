#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "examples" / "test_results" / "telegram_dialogue_sessions"
RUN_DATA_DIR = ROOT / "examples" / "test_results" / "telegram_dialogue_runs"
SESSION_LOCKS: dict[str, threading.Lock] = {}
SESSION_LOCKS_GUARD = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:100] or f"telegram-{uuid.uuid4().hex[:10]}"


def read_json(path: pathlib.Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    last_error: Exception | None = None
    for attempt in range(5):
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            time.sleep(0.12 * (attempt + 1))
    if last_error:
        raise last_error


def default_session(session_id: str) -> dict[str, Any]:
    return {
        "kind": "TelegramStyleDialogueSession",
        "session_id": session_id,
        "created_at": now(),
        "updated_at": now(),
        "mode": {
            "assistant_participation": "disabled",
            "api_calls": "enabled for dialogue replies",
            "description": "Simple API-backed dialogue test recorder.",
        },
        "messages": [],
        "artifacts": {},
    }


def html() -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>模拟 Telegram 问答测试</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #dbe7f3;
      color: #17212b;
      height: 100vh;
      display: grid;
      place-items: center;
    }
    .phone {
      width: min(920px, 100vw);
      height: min(920px, 100vh);
      background: #eef5fb;
      border: 1px solid #b8c8d8;
      display: grid;
      grid-template-rows: auto 1fr auto;
      box-shadow: 0 16px 42px rgba(20, 37, 56, .18);
    }
    header {
      height: 58px;
      background: #2aabee;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 14px;
    }
    .chat-title { font-weight: 650; line-height: 1.1; }
    .chat-subtitle { font-size: 12px; opacity: .86; margin-top: 3px; }
    .header-actions { display: flex; gap: 8px; }
    button, select, textarea, input {
      font: inherit;
      border: 0;
      border-radius: 8px;
    }
    button {
      cursor: pointer;
      background: #168acd;
      color: #fff;
      padding: 8px 10px;
    }
    button.light {
      background: rgba(255,255,255,.18);
    }
    .messages {
      overflow: auto;
      padding: 18px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      background:
        linear-gradient(rgba(238,245,251,.9), rgba(238,245,251,.9)),
        radial-gradient(circle at 20% 20%, rgba(42,171,238,.14), transparent 28%),
        radial-gradient(circle at 80% 10%, rgba(73, 148, 110, .12), transparent 32%);
    }
    .bubble {
      max-width: min(620px, 86%);
      padding: 9px 11px 7px;
      border-radius: 12px;
      line-height: 1.42;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: 0 1px 1px rgba(0,0,0,.08);
    }
    .bubble .meta {
      display: flex;
      gap: 8px;
      align-items: center;
      margin-bottom: 4px;
      font-size: 12px;
      color: #5f6f7f;
    }
    .bubble .time {
      margin-top: 5px;
      text-align: right;
      color: #6d7b88;
      font-size: 11px;
    }
    .tester { align-self: flex-end; background: #d9fdd3; border-bottom-right-radius: 4px; }
    .customer { align-self: flex-start; background: #fff; border-bottom-left-radius: 4px; }
    .service { align-self: flex-start; background: #fff; border-bottom-left-radius: 4px; }
    .observer { align-self: center; background: #fff8d8; max-width: min(720px, 92%); }
    .composer {
      background: #ffffff;
      border-top: 1px solid #cbd8e4;
      padding: 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: end;
    }
    select, input, textarea {
      width: 100%;
      background: #f4f7fa;
      border: 1px solid #d1dbe5;
      padding: 9px;
      color: #17212b;
    }
    textarea {
      resize: none;
      min-height: 44px;
      max-height: 130px;
      line-height: 1.35;
    }
    .empty {
      margin: auto;
      color: #5d6d7c;
      background: rgba(255,255,255,.7);
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13px;
    }
    @media (max-width: 720px) {
      body { display: block; }
      .phone { width: 100vw; height: 100vh; border: 0; box-shadow: none; }
      .composer { grid-template-columns: 1fr auto; }
    }
  </style>
</head>
<body>
  <div class="phone">
    <header>
      <div>
        <div class="chat-title">模拟 Telegram 问答测试</div>
        <div class="chat-subtitle" id="status">记录器启动中</div>
      </div>
      <div class="header-actions">
        <button class="light" id="newSession">新会话</button>
        <button class="light" id="exportJson">导出</button>
      </div>
    </header>
    <main class="messages" id="messages">
      <div class="empty">打开后自动连接 API。输入消息即可开始测试，过程会自动记录。</div>
    </main>
    <footer class="composer">
      <textarea id="message" placeholder="输入要记录的对话内容，Enter 发送，Shift+Enter 换行"></textarea>
      <button id="send">发送</button>
    </footer>
  </div>
  <script>
    const state = {
      session_id: new URLSearchParams(location.search).get("session") || "",
      messages: [],
      artifacts: {}
    };
    const messagesEl = document.getElementById("messages");
    const statusEl = document.getElementById("status");
    const messageEl = document.getElementById("message");

    function localTime(iso) {
      try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
      catch { return ""; }
    }

    function doc() {
      return {
        kind: "TelegramStyleDialogueSession",
        session_id: state.session_id,
        updated_at: new Date().toISOString(),
        mode: {
          assistant_participation: "disabled",
          api_calls: "enabled for dialogue replies",
          description: "Simple API-backed dialogue test recorder."
        },
        messages: state.messages,
        artifacts: state.artifacts || {}
      };
    }

    function render() {
      messagesEl.innerHTML = "";
      if (!state.messages.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "打开后自动连接 API。输入消息即可开始测试，过程会自动记录。";
        messagesEl.append(empty);
        return;
      }
      state.messages.forEach((msg) => {
        const bubble = document.createElement("article");
        bubble.className = `bubble ${msg.role}`;
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = `${msg.role} / ${msg.type}`;
        const content = document.createElement("div");
        content.textContent = msg.content;
        const time = document.createElement("div");
        time.className = "time";
        time.textContent = localTime(msg.created_at);
        bubble.append(meta, content, time);
        messagesEl.append(bubble);
      });
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function request(path, options = {}) {
      const response = await fetch(path, {
        headers: { "content-type": "application/json" },
        ...options
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    async function save(reason) {
      const saved = await request("/api/session", {
        method: "POST",
        body: JSON.stringify({ reason, session: doc() })
      });
      state.session_id = saved.session_id;
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      statusEl.textContent = `记录中：${saved.path}`;
    }

    async function load() {
      const query = state.session_id ? `?session=${encodeURIComponent(state.session_id)}` : "";
      const loaded = await request(`/api/session${query}`);
      state.session_id = loaded.session_id;
      state.messages = loaded.messages || [];
      state.artifacts = loaded.artifacts || {};
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      statusEl.textContent = `记录中：${loaded.path}`;
      render();
      request("/api/connect", {
        method: "POST",
        body: JSON.stringify({ session_id: state.session_id })
      }).then((updated) => {
        state.messages = updated.messages || [];
        state.artifacts = updated.artifacts || {};
        statusEl.textContent = `记录中：${updated.path}`;
        render();
      }).catch((error) => statusEl.textContent = `API 连接失败：${error.message}`);
    }

    async function send() {
      const content = messageEl.value.trim();
      if (!content) return;
      messageEl.disabled = true;
      messageEl.value = "";
      statusEl.textContent = "API 回复中...";
      const updated = await request("/api/message", {
        method: "POST",
        body: JSON.stringify({ session_id: state.session_id, content })
      });
      state.session_id = updated.session_id;
      state.messages = updated.messages || [];
      state.artifacts = updated.artifacts || {};
      messageEl.disabled = false;
      messageEl.focus();
      statusEl.textContent = `记录中：${updated.path}`;
      render();
      const activeJob = state.artifacts?.active_generation_job;
      if (activeJob?.job_id && activeJob?.status === "running") {
        statusEl.textContent = "检测到生成意图，正在生成项目并测试...";
        pollJob(activeJob.job_id).catch((error) => statusEl.textContent = `生成轮询失败：${error.message}`);
      }
    }

    document.getElementById("send").addEventListener("click", () => {
      send().catch((error) => statusEl.textContent = `保存失败：${error.message}`);
    });

    messageEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send().catch((error) => statusEl.textContent = `保存失败：${error.message}`);
      }
    });

    document.getElementById("newSession").addEventListener("click", async () => {
      const loaded = await request("/api/session?new=1");
      state.session_id = loaded.session_id;
      state.messages = loaded.messages || [];
      state.artifacts = loaded.artifacts || {};
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      statusEl.textContent = `记录中：${loaded.path}`;
      render();
      request("/api/connect", {
        method: "POST",
        body: JSON.stringify({ session_id: state.session_id })
      }).then((updated) => {
        state.messages = updated.messages || [];
        state.artifacts = updated.artifacts || {};
        statusEl.textContent = `记录中：${updated.path}`;
        render();
      }).catch((error) => statusEl.textContent = `API 连接失败：${error.message}`);
    });

    async function reloadSession() {
      const loaded = await request(`/api/session?session=${encodeURIComponent(state.session_id)}`);
      state.messages = loaded.messages || [];
      state.artifacts = loaded.artifacts || {};
      statusEl.textContent = `记录中：${loaded.path}`;
      render();
      return loaded;
    }

    async function pollJob(jobId) {
      const job = await request(`/api/job?job_id=${encodeURIComponent(jobId)}`);
      await reloadSession();
      if (job.status === "running") {
        setTimeout(() => pollJob(jobId).catch((error) => statusEl.textContent = `任务轮询失败：${error.message}`), 1800);
      } else {
        statusEl.textContent = `生成任务${job.status === "pass" ? "完成" : "失败"}`;
      }
    }

    document.getElementById("exportJson").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(doc(), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${state.session_id || "telegram-dialogue-session"}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    });

    load().catch((error) => statusEl.textContent = `启动失败：${error.message}`);
  </script>
</body>
</html>
"""


def message(role: str, msg_type: str, content: str, artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "created_at": now(),
        "role": role,
        "type": msg_type,
        "content": content,
    }
    if artifacts:
        row["artifacts"] = artifacts
    return row


def session_file(data_dir: pathlib.Path, session_id: str) -> pathlib.Path:
    return data_dir / f"{safe_id(session_id)}.json"


def session_lock(session_id: str) -> threading.Lock:
    key = safe_id(session_id)
    with SESSION_LOCKS_GUARD:
        lock = SESSION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            SESSION_LOCKS[key] = lock
        return lock


def append_session_message(data_dir: pathlib.Path, session_id: str, row: dict[str, Any]) -> dict[str, Any]:
    with session_lock(session_id):
        path = session_file(data_dir, session_id)
        doc = read_json(path, default_session(session_id))
        rows = doc.get("messages")
        if not isinstance(rows, list):
            rows = []
        rows.append(row)
        doc["messages"] = rows
        doc["updated_at"] = now()
        write_json(path, doc)
        doc["path"] = str(path)
        return doc


def update_session_artifacts(data_dir: pathlib.Path, session_id: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    with session_lock(session_id):
        path = session_file(data_dir, session_id)
        doc = read_json(path, default_session(session_id))
        current = doc.get("artifacts")
        if not isinstance(current, dict):
            current = {}
        current.update(artifacts)
        doc["artifacts"] = current
        doc["updated_at"] = now()
        write_json(path, doc)
        doc["path"] = str(path)
        return doc


def transcript_goal(session: dict[str, Any]) -> str:
    rows = session.get("messages") if isinstance(session.get("messages"), list) else []
    transcript = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", "unknown"))
        msg_type = str(row.get("type", "message"))
        content = str(row.get("content", "")).strip()
        if content:
            transcript.append(f"[{role}/{msg_type}] {content}")
    body = "\n".join(transcript).strip() or "空对话。请先在 Telegram GUI 中输入需求和问答记录。"
    return (
        "以下是用户主导的模拟 Telegram 项目需求对话记录。\n"
        "请只根据这份对话提取最终项目需求；不要自动套用 CRUD、任务看板、JSON 记录管理等默认模板；"
        "如果对话中要求真实项目/API测试，则保留该要求。运行时输入、输出和中间产物必须来自对话语义。\n\n"
        + body
    )


def wants_generation_from_dialogue(user_text: str, assistant_text: str = "") -> bool:
    text = f"{user_text}\n{assistant_text}".lower()
    explicit_patterns = (
        r"直接生成",
        r"开始生成",
        r"现在生成",
        r"马上生成",
        r"生成项目吧",
        r"帮我生成",
        r"可以生成项目",
        r"信息够了.*生成",
        r"信息足够.*生成",
        r"start\s+generation",
        r"generate\s+(the\s+)?project",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in explicit_patterns)


def run_command(command: list[str], timeout: int) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "stdout": proc.stdout[-6000:],
        "stderr": proc.stderr[-6000:],
        "status": "pass" if proc.returncode == 0 else "fail",
    }


def call_dialogue_api(messages: list[dict[str, Any]], timeout: int = 120) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_connectivity import _extract_text, _is_gptsapi_base_url, _resolve_api_credentials  # type: ignore

    creds = _resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    root = str(creds.get("base_url", "")).strip()
    if not token:
        return {"ok": False, "error": "missing API key"}

    model = str(creds.get("model") or "gpt-4o-mini")
    system = (
        "你是 CGNK 项目需求测试中的客服问答代理。"
        "你的职责是用尽量少的问题澄清用户真正想要构建和测试的项目。"
        "你的对话不能像固定表单，也不能按固定顺序机械追问输入、输出、标准；先理解用户已经说出的信息，只补真正缺失且会影响生成的内容。"
        "不要替用户默认 CRUD、任务看板、JSON 记录管理等模板。"
        "如果用户已经说了项目对象，例如“游戏视频找高光”，就把运行时输入推断为游戏视频文件，不要再问“输入是什么类型的视频文件”。"
        "如果用户说输入是视频，就必须把运行时输入保持为视频文件；"
        "如果用户说输出为 mp4、高光片段、一个一个视频，就把输出推断为多个 MP4 高光片段，不要重复确认。"
        "对于游戏视频高光项目，默认高光标准可以是画面变化、动作强度、音频峰值、语音/字幕关键词、连续事件密度的综合判断；只有用户没有给判断标准时，才用一句话问“高光按默认综合判断可以吗，还是有指定事件？”。"
        "每轮最多问一个主问题，必要时把相关小项合并成同一个问题。"
        "优先用自然总结式回复，例如“我先按 X 理解，剩下只差 Y”，不要连续使用“请问您希望...”句式。"
        "不要询问预算、截止时间、库名、版本、文档、安装方式、平台、界面风格等非阻塞细节，除非用户主动提到或这些信息会改变核心方案。"
        "当已经知道输入、核心处理、输出和验收方式时，要明确说“信息足够，可以生成项目”，并简短总结需求，不要继续追问。"
        "验收方式可以用合理默认值：能上传/选择一个视频、生成候选高光、导出 MP4、显示高光依据；不要为了验收方式单独追问用户。"
        "如果用户说“不用了”“没有要求”“你决定”，就采用合理默认值并收束。"
        "不要生成代码，不要声称已经生成项目，只进行问答澄清；真正生成由对话里的明确生成意图触发。"
    )
    api_messages = [{"role": "system", "content": system}]
    for row in messages[-24:]:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", ""))
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        if role == "customer":
            api_messages.append({"role": "user", "content": content})
        elif role == "service":
            api_messages.append({"role": "assistant", "content": content})
        elif role == "tester":
            api_messages.append({"role": "user", "content": f"测试者记录：{content}"})

    if _is_gptsapi_base_url(root):
        endpoint = root.rstrip("/") + "/chat/completions"
        payload = {"model": model, "messages": api_messages, "temperature": 0.35, "max_tokens": 700}
    else:
        endpoint = root.rstrip("/") + "/responses"
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in api_messages)
        payload = {"model": model, "input": transcript, "temperature": 0.2, "max_output_tokens": 700}
    doc: dict[str, Any] | None = None
    error = ""
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        started = time.time()
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "CGNK-Telegram-Dialogue-GUI/1",
                    "Connection": "close",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise RuntimeError("response is not object")
            doc = parsed
            attempts.append({"attempt": attempt, "status": "pass", "duration_seconds": round(time.time() - started, 2)})
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            error = f"HTTP {exc.code}: {detail[:400]}"
            attempts.append({"attempt": attempt, "status": "fail", "error": error, "duration_seconds": round(time.time() - started, 2)})
            break
        except Exception as exc:
            error = f"request failed: {exc}"
            attempts.append({"attempt": attempt, "status": "fail", "error": error, "duration_seconds": round(time.time() - started, 2)})
            if attempt < 3:
                time.sleep(1.2 * attempt)
    if doc is None:
        return {"ok": False, "error": error, "endpoint": endpoint, "model": model, "attempts": attempts}
    return {
        "ok": True,
        "text": _extract_text(doc).strip(),
        "request_id": str(doc.get("id", "")).strip(),
        "endpoint": endpoint,
        "model": model,
        "attempts": attempts,
    }


def check_api_connected() -> dict[str, Any]:
    result = run_command([sys.executable, "scripts/check_connectivity.py", "--live"], timeout=120)
    api_connected = "api=connected" in str(result.get("stdout", ""))
    return {
        "ok": api_connected,
        "api_status": "connected" if api_connected else "failed",
        "overall_status": result.get("status"),
        "command": result,
        "result_path": str(ROOT / "examples" / "test_results" / "connectivity_check_result.json"),
    }


def write_pipeline_plan(session_id: str, goal: str) -> dict[str, pathlib.Path]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import compose_local_pipeline  # type: ignore
    import requirement_blueprint  # type: ignore

    safe = safe_id(session_id)
    RUN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    composition_path = RUN_DATA_DIR / f"{safe}_composition.json"
    blueprint_path = RUN_DATA_DIR / f"{safe}_requirement_blueprint.json"
    composition = compose_local_pipeline.compose(goal, allow_network=True, allow_provider=True)
    blueprint = requirement_blueprint.build_requirement_blueprint(goal, [], assume_defaults=False)
    composition["requirement_blueprint"] = blueprint
    composition["requirement_blueprint_ref"] = str(blueprint_path)
    write_json(composition_path, composition)
    write_json(blueprint_path, blueprint)
    return {"composition": composition_path, "blueprint": blueprint_path}


def start_job(server: ThreadingHTTPServer, kind: str, session_id: str, target) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    jobs = server.jobs  # type: ignore[attr-defined]
    jobs[job_id] = {"job_id": job_id, "kind": kind, "status": "running", "started_at": now(), "session_id": session_id}

    def runner() -> None:
        try:
            result = target(job_id, session_id)
            jobs[job_id].update({"status": "pass", "finished_at": now(), "result": result})
            update_session_artifacts(
                server.data_dir,  # type: ignore[attr-defined]
                session_id,
                {"active_generation_job": {"job_id": job_id, "kind": kind, "status": "pass", "finished_at": jobs[job_id]["finished_at"]}},
            )
        except Exception as exc:
            jobs[job_id].update({"status": "fail", "finished_at": now(), "error": str(exc)})
            update_session_artifacts(
                server.data_dir,  # type: ignore[attr-defined]
                session_id,
                {"active_generation_job": {"job_id": job_id, "kind": kind, "status": "fail", "finished_at": jobs[job_id]["finished_at"], "error": str(exc)}},
            )
            append_session_message(
                server.data_dir,  # type: ignore[attr-defined]
                session_id,
                message("observer", "problem", f"{kind} 失败：{exc}"),
            )

    threading.Thread(target=runner, daemon=True).start()
    return jobs[job_id]


class Handler(BaseHTTPRequestHandler):
    server_version = "CGNKTelegramDialogueGUI/1.0"

    @property
    def data_dir(self) -> pathlib.Path:
        return self.server.data_dir  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_text(self, text: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, doc: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def session_path(self, session_id: str) -> pathlib.Path:
        return self.data_dir / f"{safe_id(session_id)}.json"

    def save_session(self, session: dict[str, Any], reason: str) -> dict[str, Any]:
        session_id = safe_id(str(session.get("session_id") or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"))
        path = self.session_path(session_id)
        existing = read_json(path, default_session(session_id))
        messages = session.get("messages")
        if not isinstance(messages, list):
            messages = existing.get("messages", [])
        artifacts = session.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = existing.get("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
        saved = {
            **existing,
            "kind": "TelegramStyleDialogueSession",
            "session_id": session_id,
            "updated_at": now(),
            "mode": {
                "assistant_participation": "disabled",
                "api_calls": "enabled for dialogue replies",
                "description": "Simple API-backed dialogue test recorder.",
            },
            "messages": messages,
            "artifacts": artifacts,
            "last_save_reason": reason,
        }
        write_json(path, saved)
        saved["path"] = str(path)
        return saved

    def load_session(self, session_id: str) -> dict[str, Any]:
        path = self.session_path(session_id)
        doc = read_json(path, default_session(session_id))
        doc["path"] = str(path)
        return doc

    def run_api_check_job(self, job_id: str, session_id: str) -> dict[str, Any]:
        append_session_message(
            self.data_dir,
            session_id,
            message("observer", "criterion", "开始真实 API 连通测试：python scripts/check_connectivity.py --live"),
        )
        result = run_command([sys.executable, "scripts/check_connectivity.py", "--live"], timeout=120)
        artifacts = {
            "api_connectivity_result": str(ROOT / "examples" / "test_results" / "connectivity_check_result.json"),
            "api_connectivity_command": result,
        }
        update_session_artifacts(self.data_dir, session_id, artifacts)
        append_session_message(
            self.data_dir,
            session_id,
            message(
                "observer",
                "decision" if result["status"] == "pass" else "problem",
                "API 连通测试完成："
                + result["status"]
                + "\n\n"
                + (result.get("stdout") or result.get("stderr") or ""),
                artifacts,
            ),
        )
        if result["status"] != "pass":
            raise RuntimeError("API connectivity check failed")
        return artifacts

    def run_project_test_job(self, job_id: str, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        goal = transcript_goal(session)
        safe = safe_id(session_id)
        out_dir = ROOT / "generated" / f"telegram_{safe}"
        run_dir = ROOT / "examples" / "runtime_runs" / f"telegram_{safe}"
        test_run_dir = ROOT / "examples" / "runtime_runs" / f"telegram_{safe}_tests"
        execution_path = RUN_DATA_DIR / f"{safe}_execution.json"
        test_composition_path = RUN_DATA_DIR / f"{safe}_test_composition.json"
        test_execution_path = RUN_DATA_DIR / f"{safe}_test_execution.json"

        append_session_message(
            self.data_dir,
            session_id,
            message(
                "observer",
                "criterion",
                "开始真实项目/API管线测试。当前对话会作为需求来源；不会使用 GUI 外的人工回答。",
                {"goal_preview": goal[:1200]},
            ),
        )
        paths = write_pipeline_plan(session_id, goal)
        artifacts: dict[str, Any] = {
            "goal_source": "telegram_transcript",
            "composition_path": str(paths["composition"]),
            "requirement_blueprint_path": str(paths["blueprint"]),
            "project_dir": str(out_dir),
            "runtime_dir": str(run_dir),
            "test_composition_path": str(test_composition_path),
            "test_execution_path": str(test_execution_path),
        }
        update_session_artifacts(self.data_dir, session_id, artifacts)
        append_session_message(
            self.data_dir,
            session_id,
            message("observer", "io", "已生成本轮 composition 和 requirement blueprint。", artifacts),
        )

        generation_command = [
            sys.executable,
            "scripts/run_local_pipeline.py",
            "--plan",
            str(paths["composition"]),
            "--out-dir",
            str(out_dir),
            "--run-dir",
            str(run_dir),
            "--result-path",
            str(execution_path),
            "--timeout",
            "420",
            "--json",
        ]
        generation = run_command(generation_command, timeout=700)
        artifacts["generation_command"] = generation
        artifacts["execution_path"] = str(execution_path)
        update_session_artifacts(self.data_dir, session_id, artifacts)
        append_session_message(
            self.data_dir,
            session_id,
            message(
                "observer",
                "decision" if generation["status"] == "pass" else "problem",
                "真实项目生成完成："
                + generation["status"]
                + "\n\n"
                + (generation.get("stdout") or generation.get("stderr") or ""),
                {"project_dir": str(out_dir), "execution_path": str(execution_path)},
            ),
        )
        if generation["status"] != "pass":
            raise RuntimeError("project generation failed")

        compose_test_command = [
            sys.executable,
            "scripts/compose_test_pipeline.py",
            "--goal",
            "测试 Telegram GUI 对话生成的真实项目，包含 live API 连通和本地浏览器测试",
            "--project-dir",
            str(out_dir),
            "--profile",
            "full",
            "--live-browser",
            "--run-dir",
            str(run_dir),
            "--out",
            str(test_composition_path),
            "--json",
        ]
        test_composition = run_command(compose_test_command, timeout=180)
        artifacts["test_composition_command"] = test_composition
        update_session_artifacts(self.data_dir, session_id, artifacts)
        append_session_message(
            self.data_dir,
            session_id,
            message(
                "observer",
                "criterion",
                "测试管线编排完成："
                + test_composition["status"]
                + "\n\n"
                + (test_composition.get("stdout") or test_composition.get("stderr") or ""),
                {"test_composition_path": str(test_composition_path)},
            ),
        )
        if test_composition["status"] != "pass":
            raise RuntimeError("test composition failed")

        run_test_command = [
            sys.executable,
            "scripts/run_test_pipeline.py",
            "--plan",
            str(test_composition_path),
            "--run-dir",
            str(test_run_dir),
            "--result-path",
            str(test_execution_path),
            "--json",
        ]
        test_execution = run_command(run_test_command, timeout=360)
        artifacts["test_execution_command"] = test_execution
        update_session_artifacts(self.data_dir, session_id, artifacts)
        append_session_message(
            self.data_dir,
            session_id,
            message(
                "observer",
                "decision" if test_execution["status"] == "pass" else "problem",
                "真实测试执行完成："
                + test_execution["status"]
                + "\n\n"
                + (test_execution.get("stdout") or test_execution.get("stderr") or ""),
                {"test_execution_path": str(test_execution_path), "project_dir": str(out_dir)},
            ),
        )
        if test_execution["status"] != "pass":
            raise RuntimeError("test execution failed")
        return artifacts

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in ("", "/"):
            self.send_text(html())
            return
        if parsed.path == "/favicon.ico":
            self.send_text("", "image/x-icon")
            return
        if parsed.path == "/api/session":
            if query.get("new"):
                session_id = f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
                self.send_json(self.save_session(default_session(session_id), "session_created"))
                return
            session_id = query.get("session", [""])[0] or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            path = self.session_path(session_id)
            if path.exists():
                self.send_json(self.load_session(session_id))
            else:
                self.send_json(self.save_session(default_session(session_id), "session_created"))
            return
        if parsed.path == "/api/job":
            job_id = query.get("job_id", [""])[0]
            job = self.server.jobs.get(job_id)  # type: ignore[attr-defined]
            if not isinstance(job, dict):
                self.send_error(HTTPStatus.NOT_FOUND, "unknown job")
                return
            self.send_json(job)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/session":
            body = self.read_body()
            session = body.get("session")
            if not isinstance(session, dict):
                self.send_error(HTTPStatus.BAD_REQUEST, "missing session")
                return
            self.send_json(self.save_session(session, str(body.get("reason") or "save")))
            return
        if parsed.path == "/api/connect":
            body = self.read_body()
            session_id = safe_id(str(body.get("session_id") or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"))
            current = self.load_session(session_id)
            artifacts = current.get("artifacts") if isinstance(current.get("artifacts"), dict) else {}
            if isinstance(artifacts, dict) and artifacts.get("api_connection", {}).get("ok"):
                self.send_json(current)
                return
            result = check_api_connected()
            update_session_artifacts(self.data_dir, session_id, {"api_connection": result})
            append_session_message(
                self.data_dir,
                session_id,
                message(
                    "observer",
                    "decision" if result.get("ok") else "problem",
                    "API 已连接。" if result.get("ok") else "API 连接失败。\n\n" + json.dumps(result, ensure_ascii=False, indent=2),
                    {"api_connection": result},
                ),
            )
            self.send_json(self.load_session(session_id))
            return
        if parsed.path == "/api/message":
            body = self.read_body()
            session_id = safe_id(str(body.get("session_id") or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"))
            content = str(body.get("content") or "").strip()
            if not content:
                self.send_error(HTTPStatus.BAD_REQUEST, "missing content")
                return
            append_session_message(self.data_dir, session_id, message("customer", "message", content))
            current = self.load_session(session_id)
            api_result = call_dialogue_api(current.get("messages", []))
            update_session_artifacts(
                self.data_dir,
                session_id,
                {"last_api_reply": {k: v for k, v in api_result.items() if k != "text"}},
            )
            assistant_text = ""
            if api_result.get("ok"):
                assistant_text = str(api_result.get("text") or "")
                append_session_message(
                    self.data_dir,
                    session_id,
                    message(
                        "service",
                        "message",
                        assistant_text,
                        {"request_id": api_result.get("request_id"), "model": api_result.get("model")},
                    ),
                )
            else:
                append_session_message(
                    self.data_dir,
                    session_id,
                    message("observer", "problem", "API 回复失败：\n" + json.dumps(api_result, ensure_ascii=False, indent=2)),
                )
            current = self.load_session(session_id)
            active = current.get("artifacts", {}).get("active_generation_job") if isinstance(current.get("artifacts"), dict) else None
            active_running = isinstance(active, dict) and active.get("status") == "running"
            if wants_generation_from_dialogue(content, assistant_text) and not active_running:
                append_session_message(
                    self.data_dir,
                    session_id,
                    message("observer", "criterion", "检测到对话里的生成意图，开始用当前对话生成项目并执行测试。"),
                )
                job = start_job(self.server, "project_generation_and_test", session_id, self.run_project_test_job)
                update_session_artifacts(
                    self.data_dir,
                    session_id,
                    {"active_generation_job": {"job_id": job["job_id"], "kind": job["kind"], "status": job["status"], "started_at": job["started_at"]}},
                )
            self.send_json(self.load_session(session_id))
            return
        if parsed.path == "/api/run_api_check":
            body = self.read_body()
            session_id = safe_id(str(body.get("session_id") or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"))
            job = start_job(self.server, "api_check", session_id, self.run_api_check_job)
            self.send_json(job)
            return
        if parsed.path == "/api/run_project_test":
            body = self.read_body()
            session_id = safe_id(str(body.get("session_id") or f"telegram-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"))
            job = start_job(self.server, "project_generation_and_test", session_id, self.run_project_test_job)
            self.send_json(job)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8073)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()

    data_dir = pathlib.Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.data_dir = data_dir  # type: ignore[attr-defined]
    server.jobs = {}  # type: ignore[attr-defined]
    print(f"TELEGRAM_DIALOGUE_GUI: http://{args.host}:{args.port}/")
    print(f"data_dir={data_dir}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
