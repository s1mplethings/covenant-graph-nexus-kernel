#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "examples" / "test_results" / "dialogue_gui_sessions"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(text or "").lower()).strip("-")
    value = re.sub(r"-+", "-", value)
    return value[:80] or "manual-dialogue-test"


def safe_session_id(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")
    return value[:100] or f"session-{uuid.uuid4().hex[:10]}"


def read_json(path: pathlib.Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def default_session(session_id: str) -> dict[str, Any]:
    return {
        "kind": "ManualDialogueTestSession",
        "session_id": session_id,
        "created_at": now(),
        "updated_at": now(),
        "mode": {
            "assistant_participation": "disabled",
            "api_calls": "disabled",
            "purpose": "User-led requirement dialogue and blueprint audit logging.",
        },
        "snapshot": {
            "title": "",
            "raw_requirement": "",
            "runtime_input": "",
            "intermediate_artifacts": "",
            "runtime_output": "",
            "automation_goal": "",
            "assumptions": "",
            "open_questions": "",
            "multi_criteria": "",
            "route_notes": "",
            "observed_problems": "",
            "final_decision": "",
        },
        "events": [],
    }


def html() -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CGNK 手动问答测试台</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      color: #1b2430;
      background: #f6f7f9;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 14px 18px;
      border-bottom: 1px solid #d8dde6;
      background: #ffffff;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    .status { color: #526071; font-size: 13px; }
    button, input, select, textarea {
      font: inherit;
      border: 1px solid #c9d1dc;
      border-radius: 6px;
      background: #ffffff;
      color: #1b2430;
    }
    button {
      padding: 8px 10px;
      cursor: pointer;
      background: #0f766e;
      border-color: #0f766e;
      color: #ffffff;
    }
    button.secondary {
      background: #ffffff;
      color: #1b2430;
      border-color: #c9d1dc;
    }
    main {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr) 380px;
      gap: 14px;
      padding: 14px;
    }
    section {
      background: #ffffff;
      border: 1px solid #d8dde6;
      border-radius: 8px;
      min-width: 0;
    }
    section h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 15px;
      border-bottom: 1px solid #e5e9f0;
    }
    .body { padding: 12px 14px; display: grid; gap: 10px; }
    label { display: grid; gap: 5px; font-size: 13px; color: #526071; }
    input, select, textarea { width: 100%; padding: 8px; }
    textarea { resize: vertical; min-height: 78px; line-height: 1.42; }
    .large { min-height: 140px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .event-list {
      max-height: calc(100vh - 180px);
      overflow: auto;
      display: grid;
      gap: 8px;
    }
    .event {
      border: 1px solid #e0e5ec;
      border-radius: 7px;
      padding: 9px;
      background: #fbfcfd;
    }
    .event-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      color: #617083;
      margin-bottom: 6px;
    }
    .event-content { white-space: pre-wrap; line-height: 1.42; }
    .preview {
      min-height: calc(100vh - 250px);
      max-height: calc(100vh - 250px);
      overflow: auto;
      white-space: pre-wrap;
      background: #101820;
      color: #e6edf3;
      border-radius: 7px;
      padding: 10px;
      font-size: 12px;
    }
    .hint {
      font-size: 12px;
      color: #657386;
      line-height: 1.45;
    }
    @media (max-width: 1100px) {
      main { grid-template-columns: 1fr; }
      .preview, .event-list { max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>CGNK 手动问答测试台</h1>
      <div class="status" id="status">未连接</div>
    </div>
    <div class="toolbar">
      <button class="secondary" id="newSession">新建会话</button>
      <button class="secondary" id="saveNow">立即保存</button>
      <button id="downloadJson">下载 JSON</button>
    </div>
  </header>
  <main>
    <section>
      <h2>会话和原始需求</h2>
      <div class="body">
        <label>会话标题
          <input id="title" data-field="title" placeholder="例如：视频高光项目蓝图问答测试">
        </label>
        <label>原始需求
          <textarea id="raw_requirement" data-field="raw_requirement" class="large" placeholder="由测试者输入。系统不会自动补全。"></textarea>
        </label>
        <div class="hint">本工具不会调用 API，不会生成答案，不会替你判断。所有字段和事件只用于记录测试过程。</div>
        <div class="row">
          <label>事件角色
            <select id="eventRole">
              <option value="tester">测试者</option>
              <option value="customer">模拟用户</option>
              <option value="system_observation">系统观察</option>
              <option value="reviewer">评审</option>
            </select>
          </label>
          <label>事件类型
            <select id="eventType">
              <option value="question">问题</option>
              <option value="answer">回答</option>
              <option value="assumption">假设</option>
              <option value="io_contract">I/O 记录</option>
              <option value="criterion">判断标准</option>
              <option value="route_note">路线记录</option>
              <option value="problem">问题定位</option>
              <option value="decision">结论</option>
              <option value="note">备注</option>
            </select>
          </label>
        </div>
        <label>事件内容
          <textarea id="eventContent" placeholder="手动输入本轮问答或观察。"></textarea>
        </label>
        <button id="addEvent">记录事件</button>
      </div>
    </section>

    <section>
      <h2>中间信息蓝图</h2>
      <div class="body">
        <label>运行时输入
          <textarea data-field="runtime_input" placeholder="例如：单个 GameVideoFile，而不是需求文本或 JSON records。"></textarea>
        </label>
        <label>中间产物
          <textarea data-field="intermediate_artifacts" class="large" placeholder="逐项记录：VideoMetadata、FrameSamples、AudioTimeline、CandidateWindows..."></textarea>
        </label>
        <label>运行时输出
          <textarea data-field="runtime_output" placeholder="例如：HighlightTimeline、ClipManifest、可下载视频片段。"></textarea>
        </label>
        <label>减少人力劳动的目标
          <textarea data-field="automation_goal" placeholder="记录系统应该自动完成哪些工作，哪些不能转嫁给使用者。"></textarea>
        </label>
        <label>假设和未确认点
          <textarea data-field="assumptions"></textarea>
        </label>
        <label>待追问问题
          <textarea data-field="open_questions"></textarea>
        </label>
        <label>多重判断标准
          <textarea data-field="multi_criteria" class="large" placeholder="记录画面、音频、事件密度、OCR、时间窗合并、导出有效性等标准。"></textarea>
        </label>
        <label>路线和模块记录
          <textarea data-field="route_notes"></textarea>
        </label>
        <label>观察到的问题
          <textarea data-field="observed_problems"></textarea>
        </label>
        <label>最终结论
          <textarea data-field="final_decision"></textarea>
        </label>
      </div>
    </section>

    <section>
      <h2>实时日志</h2>
      <div class="body">
        <div class="event-list" id="eventList"></div>
        <h2 style="padding:0;border:0;">JSON 预览</h2>
        <pre class="preview" id="preview"></pre>
      </div>
    </section>
  </main>
  <script>
    const state = {
      session_id: new URLSearchParams(location.search).get("session") || "",
      snapshot: {},
      events: [],
      saveTimer: null
    };

    const statusEl = document.getElementById("status");
    const eventList = document.getElementById("eventList");
    const preview = document.getElementById("preview");

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function collectSnapshot() {
      document.querySelectorAll("[data-field]").forEach((el) => {
        state.snapshot[el.dataset.field] = el.value;
      });
      return state.snapshot;
    }

    function applySnapshot(snapshot) {
      document.querySelectorAll("[data-field]").forEach((el) => {
        el.value = snapshot?.[el.dataset.field] || "";
      });
    }

    function sessionDoc() {
      collectSnapshot();
      return {
        kind: "ManualDialogueTestSession",
        session_id: state.session_id,
        updated_at: new Date().toISOString(),
        mode: {
          assistant_participation: "disabled",
          api_calls: "disabled",
          purpose: "User-led requirement dialogue and blueprint audit logging."
        },
        snapshot: state.snapshot,
        events: state.events
      };
    }

    function render() {
      eventList.innerHTML = "";
      [...state.events].reverse().forEach((event) => {
        const card = document.createElement("div");
        card.className = "event";
        const meta = document.createElement("div");
        meta.className = "event-meta";
        meta.textContent = `${event.created_at} | ${event.role} / ${event.type}`;
        const content = document.createElement("div");
        content.className = "event-content";
        content.textContent = event.content;
        card.append(meta, content);
        eventList.append(card);
      });
      preview.textContent = JSON.stringify(sessionDoc(), null, 2);
    }

    async function request(path, options = {}) {
      const response = await fetch(path, {
        headers: { "content-type": "application/json" },
        ...options
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    async function saveNow(reason = "snapshot_save") {
      const doc = sessionDoc();
      const saved = await request("/api/session", {
        method: "POST",
        body: JSON.stringify({ reason, session: doc })
      });
      state.session_id = saved.session_id;
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      setStatus(`已保存：${saved.path}`);
      render();
    }

    function scheduleSave(reason) {
      clearTimeout(state.saveTimer);
      state.saveTimer = setTimeout(() => {
        saveNow(reason).catch((error) => setStatus(`保存失败：${error.message}`));
      }, 500);
      render();
    }

    async function loadOrCreate() {
      const query = state.session_id ? `?session=${encodeURIComponent(state.session_id)}` : "";
      const doc = await request(`/api/session${query}`);
      state.session_id = doc.session_id;
      state.snapshot = doc.snapshot || {};
      state.events = doc.events || [];
      applySnapshot(state.snapshot);
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      setStatus(`记录文件：${doc.path}`);
      render();
    }

    document.querySelectorAll("[data-field]").forEach((el) => {
      el.addEventListener("input", () => scheduleSave("field_change"));
    });

    document.getElementById("addEvent").addEventListener("click", async () => {
      const content = document.getElementById("eventContent").value.trim();
      if (!content) return;
      const event = {
        id: crypto.randomUUID(),
        created_at: new Date().toISOString(),
        role: document.getElementById("eventRole").value,
        type: document.getElementById("eventType").value,
        content
      };
      state.events.push(event);
      document.getElementById("eventContent").value = "";
      await saveNow("event_added");
    });

    document.getElementById("saveNow").addEventListener("click", () => {
      saveNow("manual_save").catch((error) => setStatus(`保存失败：${error.message}`));
    });

    document.getElementById("newSession").addEventListener("click", async () => {
      const doc = await request("/api/session?new=1");
      state.session_id = doc.session_id;
      state.snapshot = doc.snapshot || {};
      state.events = doc.events || [];
      applySnapshot(state.snapshot);
      history.replaceState(null, "", `/?session=${encodeURIComponent(state.session_id)}`);
      setStatus(`新会话：${doc.path}`);
      render();
    });

    document.getElementById("downloadJson").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(sessionDoc(), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${state.session_id || "manual-dialogue-session"}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    });

    loadOrCreate().catch((error) => setStatus(`启动失败：${error.message}`));
  </script>
</body>
</html>
"""


class DialogueHandler(BaseHTTPRequestHandler):
    server_version = "CGNKManualDialogueGUI/1.0"

    @property
    def data_dir(self) -> pathlib.Path:
        return self.server.data_dir  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, doc: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, text: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def session_path(self, session_id: str) -> pathlib.Path:
        return self.data_dir / f"{safe_session_id(session_id)}.json"

    def load_session(self, session_id: str) -> dict[str, Any]:
        path = self.session_path(session_id)
        doc = read_json(path, default_session(session_id))
        doc["path"] = str(path)
        return doc

    def save_session(self, doc: dict[str, Any], reason: str) -> dict[str, Any]:
        snapshot = doc.get("snapshot") if isinstance(doc.get("snapshot"), dict) else {}
        session_id = safe_session_id(str(doc.get("session_id") or slug(snapshot.get("title") or "") or f"session-{uuid.uuid4().hex[:10]}"))
        path = self.session_path(session_id)
        existing = read_json(path, default_session(session_id))
        merged = {
            **existing,
            **doc,
            "kind": "ManualDialogueTestSession",
            "session_id": session_id,
            "updated_at": now(),
        }
        events = merged.get("events")
        if not isinstance(events, list):
            events = []
        audit_event = {
            "id": f"audit-{uuid.uuid4().hex[:10]}",
            "created_at": now(),
            "role": "recorder",
            "type": "autosave",
            "content": reason,
        }
        events.append(audit_event)
        merged["events"] = events
        write_json(path, merged)
        merged["path"] = str(path)
        return merged

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in ("", "/"):
            self.send_text(html())
            return
        if parsed.path == "/api/session":
            if query.get("new"):
                session_id = f"manual-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
                doc = default_session(session_id)
                saved = self.save_session(doc, "session_created")
                self.send_json(saved)
                return
            session_id = query.get("session", [""])[0] or f"manual-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            doc = self.load_session(session_id)
            if not self.session_path(session_id).exists():
                doc = self.save_session(doc, "session_created")
            self.send_json(doc)
            return
        if parsed.path == "/api/sessions":
            rows = []
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.data_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                doc = read_json(path, {})
                rows.append(
                    {
                        "session_id": doc.get("session_id", path.stem),
                        "updated_at": doc.get("updated_at", ""),
                        "title": doc.get("snapshot", {}).get("title", ""),
                        "path": str(path),
                    }
                )
            self.send_json({"sessions": rows})
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
            saved = self.save_session(session, str(body.get("reason") or "save"))
            self.send_json(saved)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8072)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()

    data_dir = pathlib.Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), DialogueHandler)
    server.data_dir = data_dir  # type: ignore[attr-defined]
    print(f"MANUAL_DIALOGUE_GUI: http://{args.host}:{args.port}/")
    print(f"data_dir={data_dir}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
