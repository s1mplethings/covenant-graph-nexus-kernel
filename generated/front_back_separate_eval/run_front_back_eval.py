from __future__ import annotations

import json
import pathlib
import shutil
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import scripts.generated_project_architecture_contract as architecture_contract
import scripts.local_packager as local_packager
import scripts.real_test_execution as real_test_execution
import scripts.runnable_project_contract as runnable_contract
import scripts.runtime_visual_evidence as visual_evidence
import scripts.telegram_live_bridge as bridge


OUT = ROOT / "generated" / "front_back_separate_eval"
FORBIDDEN_PUBLIC = (
    "provider",
    "pipeline",
    "manifest",
    "runner",
    "JSONL",
    "BLOCKED",
    "dynamic_pipeline_runner",
    "pipeline_manifest",
    "delivery_manifest",
    "agent_session",
    "local_packager",
    "truth_ledger",
)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(chat_id), pathlib.Path(path), caption))
        return True


def _write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _leaks(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in FORBIDDEN_PUBLIC if term.lower() in lowered]


def _quality_scores(text: str, user: str, session: dict[str, Any], starts_before: int, starts_after: int) -> dict[str, int]:
    visible = text.strip()
    status = str((session.get("generation") or {}).get("status") or "")
    active = session.get("active_run") if isinstance(session.get("active_run"), dict) else {}
    a = 5 if visible else 0
    if "第一版" in user and "第一版" in visible:
        a = 5
    if "本地模型" in user and ("本地模型" in visible or "接口生成" in visible or "生成后端" in visible):
        a = 5
    if "截图" in user and ("截图" in visible or "预览" in visible):
        a = 5
    if "总结" in user and ("项目" in visible or "需求" in visible or "下一步" in visible):
        a = 5

    b = 4
    if any(marker in visible for marker in ("？", "吗", "哪些", "运行方式", "使用场景")) and starts_after == starts_before:
        b = 5
    if any(marker in user for marker in ("开始", "还在", "为什么", "总结", "怎么做")) and visible:
        b = 5

    c = 5 if any(marker in visible for marker in ("我会", "我先", "我这边", "下一步", "不能算完成", "不会")) else 3
    d = 5
    if any(marker in visible for marker in ("已经完成", "已交付", "交付已经整理好")) and status not in {"ready", "ready_with_warnings", "delivered", "final_delivered"} and str(active.get("status")) != "delivered":
        d = 1
    if "还在做吗" in user and starts_after > starts_before:
        d = 0
    e = 5
    if any(marker in visible for marker in ("判断：", "原因：", "下一步：", "当前状态：", "用户纠正:", "用户补充:", "change_request:")):
        e = 2
    return {"A": a, "B": b, "C": c, "D": d, "E": e, "total": a + b + c + d + e}


def _seed_known_project(session_dir: pathlib.Path, chat_id: str, summary: str) -> None:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = summary
    session["active_run"] = {"id": f"run-{chat_id}-seed", "status": "intake_open", "goal": summary, "created_at": bridge.now()}
    bridge.save_session(session_dir, session)


def _fake_dialogue_analysis(session_dir: pathlib.Path, chat_id: str, session: dict[str, Any], *, model: str, timeout: int, reason: str) -> dict[str, Any]:
    latest = bridge.latest_user_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    known = list(whiteboard.get("known_facts", []) if isinstance(whiteboard.get("known_facts"), list) else [])
    open_questions = list(whiteboard.get("open_questions", []) if isinstance(whiteboard.get("open_questions"), list) else [])
    acceptance = list(whiteboard.get("acceptance_criteria", []) if isinstance(whiteboard.get("acceptance_criteria"), list) else [])
    summary = str(whiteboard.get("project_summary") or "").strip()

    if "工具" in latest and not summary:
        summary = "小团队使用的本地工具，范围待继续收敛"
        open_questions = ["主要使用场景是什么？", "第一版要本地网页、桌面 GUI，还是命令行工具？", "必须交付哪些证据？"]
    elif "小团队" in latest:
        summary = "给小团队使用的本地项目/任务资料管理工具"
        known.append("用户补充: 面向小团队")
    elif "本地运行" in latest:
        summary = "给小团队使用的本地运行项目/任务资料管理工具"
        known.append("用户补充: 最好本地运行")
    elif "任务" in latest and "项目资料" in latest:
        summary = "本地运行的小团队任务管理和项目资料管理工具"
        known.append("用户补充: 管理任务和项目资料")
        acceptance.extend(["任务管理", "项目资料库", "本地运行", "README、测试报告、截图"])
    elif "AI 文档助手" in latest or "导入文档" in latest:
        summary = "本地 AI 文档助手，支持导入、检索、总结和界面"
        known.append("用户补充: 项目内部需要本地模型路线")
        acceptance.extend(["本地模型配置入口", "检索和总结适配层", "缺模型时不能假装真实推理"])
        whiteboard["target_project_architecture"] = {"model_mode": "local_model", "features": ["document_import", "retrieval", "summarization", "ui"]}
        whiteboard["cgkn_execution"] = {"generation_backend": "api"}
    else:
        if latest:
            known.append(f"用户补充: {latest}")

    whiteboard["project_summary"] = summary or latest
    whiteboard["known_facts"] = bridge.unique_strings(known, limit=80)
    whiteboard["open_questions"] = bridge.unique_strings(open_questions, limit=20)
    whiteboard["acceptance_criteria"] = bridge.unique_strings(acceptance, limit=40)
    whiteboard.setdefault("delivery_requirements", ["可运行项目", "测试报告", "截图", "最终项目包"])
    session["whiteboard"] = whiteboard
    bridge.save_session(session_dir, session)
    return {
        "status": "ok",
        "source": "controlled_frontdesk_fixture",
        "project_summary": whiteboard["project_summary"],
        "soft_questions": open_questions[:3],
        "critical_questions": [],
        "missing_required_inputs": [],
        "confidence": 0.86,
        "backend_memo": "controlled frontdesk fixture for dialogue quality evaluation",
        "user_visible_reply": "我先把范围收敛清楚，再决定第一版怎么做。",
    }


def _fake_customer_service_reply(session: dict[str, Any], model: str, timeout: int) -> tuple[str, dict[str, Any], str]:
    latest = bridge.latest_user_text(session)
    whiteboard = session.get("whiteboard", {}) if isinstance(session.get("whiteboard"), dict) else {}
    summary = str(whiteboard.get("project_summary") or latest)
    if "我想做一个工具" in latest:
        reply = "可以，我先不急着开工。这个目标还偏宽，我需要先确认三个点：给谁用、第一版用什么形式运行、交付时你最看重任务流程还是资料管理。"
    elif "第一版" in latest or "准备怎么做" in latest:
        reply = f"第一版我建议先做成可本地运行的工作台：任务列表、项目资料库、搜索入口和设置页先打通；验收看启动命令、测试记录和截图。当前理解是：{summary}。"
    elif "API 还是本地模型生成" in latest or "用 API 还是本地模型生成" in latest:
        reply = "这里要分开看：生成出来的项目内部可以走本地模型；CGKN 自己生成代码这一步按当前可用后端执行。这两件事不会混成一个限制。"
    elif "项目里面用本地模型" in latest:
        reply = "对，你修正得对。你的意思是目标项目内部接本地模型，不是要求 CGKN 生成代码也必须走本地。我会按这个语义更新方案。"
    elif "总结" in latest:
        reply = f"现在项目方向是：{summary}。下一步要看可运行项目、真实截图和测试报告，没补齐前不会说完成。"
    else:
        reply = f"我会把这条并入当前项目范围。现在先按“{summary}”推进，不清楚的地方会作为假设和验收限制写清楚。"
    return reply, whiteboard, "continue_chat"


def _fake_provider_user_message(*, event: str, session: dict[str, Any], facts: dict[str, Any], model: str, timeout: int) -> str:
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    status = str(generation.get("status") or "idle")
    if event == "greeting":
        return "我在。你直接说项目目标，我会先帮你收敛第一版范围和交付标准。"
    if event == "status_requested":
        if status in {"running", "queued"}:
            return "还在推进。我不会因为这条状态追问重开项目；现在要看测试、截图和最终项目包是否补齐。"
        return "目前没有正在跑的新任务。已有内容我会按同一个项目上下文继续衔接。"
    return "这条我会按当前项目上下文处理。"


def _fake_start_factory(calls: list[dict[str, Any]], delivered_chats: set[str] | None = None):
    delivered_chats = delivered_chats or set()

    def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
        session = bridge.load_session(session_dir_arg, chat_id)
        calls.append({"chat_id": str(chat_id), "reason": reason, "summary": session.get("whiteboard", {}).get("project_summary", "")})
        if str(chat_id) in delivered_chats:
            session["generation"] = {
                "status": "ready_with_warnings",
                "driver": "controlled_fixture",
                "package_path": "final_project_bundle.zip",
                "screenshot_count": 2,
                "test_report": "TEST_REPORT.md",
            }
            bridge.update_active_run_status(session, "delivered", package_path="final_project_bundle.zip", screenshot_count=2)
        else:
            session["generation"] = {"status": "running", "driver": "controlled_fixture", "effective_generation_mode": "api"}
            bridge.update_active_run_status(session, "running", driver="controlled_fixture")
        bridge.save_session(session_dir_arg, session)

    return fake_start


def run_frontdesk_eval() -> dict[str, Any]:
    root = OUT / "frontdesk"
    if root.exists():
        shutil.rmtree(root)
    session_dir = root / "sessions"
    log_dir = root / "logs"
    client = FakeTelegramClient()
    start_calls: list[dict[str, Any]] = []
    original_apply = bridge.apply_backend_dialogue_tick
    original_reply = bridge.customer_service_reply
    original_provider = bridge.provider_user_message
    original_start = bridge.start_agent_generation
    original_local_available = bridge.local_project_generation_available
    bridge.apply_backend_dialogue_tick = _fake_dialogue_analysis
    bridge.customer_service_reply = _fake_customer_service_reply
    bridge.provider_user_message = _fake_provider_user_message
    bridge.start_agent_generation = _fake_start_factory(start_calls, delivered_chats={"frontdesk-c"})
    bridge.local_project_generation_available = lambda: False
    conversations = {
        "A": [
            "我想做一个工具",
            "做给小团队用的",
            "最好是本地运行",
            "能管理任务和项目资料",
            "第一版你觉得要做什么",
            "那开始吧",
            "还在做吗",
            "总结一下你理解的需求",
        ],
        "B": [
            "我想做一个本地 AI 文档助手，可以导入文档、检索、总结，还要有界面",
            "走本地模型 + 开始做吧",
            "你是用 API 还是本地模型生成？",
            "我是说项目里面用本地模型，不是让你们生成代码也走本地",
            "为什么还没有截图",
            "那先补截图和测试",
            "总结一下现在做到哪了",
        ],
        "C": [
            "我想做一个本地任务管理系统",
            "开始生成",
            "还在做吗",
            "为什么还没有截图",
            "截图角度不够，补一个首页和设置页",
            "总结一下下一版要改什么",
        ],
    }
    rows: list[dict[str, Any]] = []
    try:
        for name, messages in conversations.items():
            chat_id = f"frontdesk-{name.lower()}"
            if name == "B":
                _seed_known_project(session_dir, chat_id, "本地 AI 文档助手，支持导入、检索、总结和界面")
            for index, user_message in enumerate(messages, 1):
                before_starts = len(start_calls)
                before_session = bridge.load_session(session_dir, chat_id) if (session_dir / f"{chat_id}.json").exists() else bridge.default_session(chat_id)
                before_run = ((before_session.get("active_run") or {}) if isinstance(before_session.get("active_run"), dict) else {}).get("id", "")
                bridge.handle_text(client, chat_id, user_message, session_dir, log_dir, "gpt-test", 60, generation_mode="api")
                session = bridge.load_session(session_dir, chat_id)
                assistant_reply = client.messages[-1][1] if client.messages else ""
                last_user = next((item for item in reversed(session.get("messages", [])) if item.get("role") == "user"), {})
                last = session.get("last_team_lead_reply", {}) if isinstance(session.get("last_team_lead_reply"), dict) else {}
                active = session.get("active_run", {}) if isinstance(session.get("active_run"), dict) else {}
                scores = _quality_scores(assistant_reply, user_message, session, before_starts, len(start_calls))
                rows.append(
                    {
                        "dialogue": name,
                        "turn": index,
                        "user_message": user_message,
                        "assistant_visible_reply": assistant_reply,
                        "classification.intent": (last_user.get("classification") or {}).get("intent", ""),
                        "reply_intent": last.get("reply_intent", ""),
                        "visible_status": last.get("visible_status", ""),
                        "next_user_options": last.get("next_user_options", []),
                        "whiteboard.project_summary": session.get("whiteboard", {}).get("project_summary", ""),
                        "whiteboard.known_facts": session.get("whiteboard", {}).get("known_facts", []),
                        "whiteboard.open_questions": session.get("whiteboard", {}).get("open_questions", []),
                        "whiteboard.target_project_architecture": session.get("whiteboard", {}).get("target_project_architecture", {}),
                        "whiteboard.cgkn_execution": session.get("whiteboard", {}).get("cgkn_execution", {}),
                        "whiteboard.change_requests": session.get("whiteboard", {}).get("change_requests", []),
                        "generation.status": session.get("generation", {}).get("status", ""),
                        "active_run.status": active.get("status", ""),
                        "run_id": active.get("id", ""),
                        "start_generation_called": len(start_calls) > before_starts,
                        "api_generation_called": len(start_calls) > before_starts,
                        "repair_called": active.get("next_action") == "repair_evidence" or "补截图" in json.dumps(session.get("whiteboard", {}).get("change_requests", []), ensure_ascii=False),
                        "same_context": not before_run or before_run == active.get("id", ""),
                        "internal_term_leak": _leaks(assistant_reply),
                        "fake_completion": scores["D"] < 5,
                        "question_quality_score": scores["B"],
                        "answer_quality_score": scores["total"],
                        "score_breakdown": scores,
                    }
                )
    finally:
        bridge.apply_backend_dialogue_tick = original_apply
        bridge.customer_service_reply = original_reply
        bridge.provider_user_message = original_provider
        bridge.start_agent_generation = original_start
        bridge.local_project_generation_available = original_local_available

    grouped: dict[str, list[int]] = {}
    for row in rows:
        grouped.setdefault(row["dialogue"], []).append(int(row["answer_quality_score"]))
    dialogue_results = {
        key: {
            "average": round(sum(vals) / len(vals), 2) if vals else 0,
            "verdict": "PASS" if vals and sum(vals) / len(vals) >= 22 else "NEEDS_REWORK",
        }
        for key, vals in grouped.items()
    }
    result = {
        "mode": "controlled_frontdesk_fixture_through_handle_text",
        "rows": rows,
        "dialogue_results": dialogue_results,
        "start_calls": start_calls,
        "leaks": [row for row in rows if row["internal_term_leak"]],
        "fake_completions": [row for row in rows if row["fake_completion"]],
        "overall_average": round(sum(int(row["answer_quality_score"]) for row in rows) / len(rows), 2) if rows else 0,
    }
    _write_json(OUT / "frontdesk_dialogue_eval.json", result)
    _write_frontdesk_md(result)
    return result


def _write_frontdesk_md(result: dict[str, Any]) -> None:
    rows = result["rows"]
    lines = ["# Frontdesk Dialogue Eval", ""]
    lines.append("| 对话 | 轮次 | 用户输入 | intent | visible_status | 分数 | 内部词 |")
    lines.append("|---|---:|---|---|---|---:|---|")
    for row in rows:
        lines.append(
            f"| {row['dialogue']} | {row['turn']} | {row['user_message']} | {row['reply_intent']} | {row['visible_status']} | {row['answer_quality_score']} | {','.join(row['internal_term_leak']) or '-'} |"
        )
    lines.append("")
    lines.append("## Key Replies")
    for row in rows:
        if row["turn"] in {1, 5, 6, 7, 8} or row["dialogue"] in {"B", "C"}:
            lines.append(f"- {row['dialogue']}{row['turn']} 用户：{row['user_message']}")
            lines.append(f"  回复：{row['assistant_visible_reply']}")
    (OUT / "frontdesk_dialogue_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_large_project(project: pathlib.Path) -> None:
    if project.exists():
        shutil.rmtree(project)
    for rel in [
        "frontend/pages",
        "backend/services",
        "backend/models",
        "backend/adapters",
        "screenshots",
        "tests",
        "docs",
        "data",
    ]:
        (project / rel).mkdir(parents=True, exist_ok=True)
    (project / "index.html").write_text(
        "<!doctype html><html><body><nav>Dashboard Documents Search Tasks Reports Settings</nav><main id='app'>Local AI Knowledge Studio</main><script src='frontend/app.js'></script></body></html>\n",
        encoding="utf-8",
    )
    (project / "frontend" / "app.js").write_text(
        "const views=['Dashboard','Documents','Search','Tasks','Reports','Settings']; document.querySelector('#app').textContent=views.join(' | ');\n",
        encoding="utf-8",
    )
    for view in ("dashboard", "documents", "search", "tasks", "reports", "settings"):
        (project / "frontend" / "pages" / f"{view}.js").write_text(f"export const name = '{view}';\n", encoding="utf-8")
    (project / "main.py").write_text("from backend.services.app_service import smoke\n\nif __name__ == '__main__':\n    print(smoke())\n", encoding="utf-8")
    (project / "backend" / "services" / "app_service.py").write_text(
        "from .document_import import import_document\nfrom .search_service import search\nfrom .task_service import create_task\nfrom .report_service import generate_report\n\n\ndef smoke():\n    doc = import_document('demo.md', 'demo text')\n    task = create_task('Review demo', priority='high')\n    return generate_report([doc], [task])[:80]\n",
        encoding="utf-8",
    )
    (project / "backend" / "services" / "document_import.py").write_text(
        "def import_document(path, text='', tags=None):\n    return {'path': path, 'source': path, 'text': text, 'tags': tags or [], 'status': 'indexed'}\n",
        encoding="utf-8",
    )
    (project / "backend" / "services" / "search_service.py").write_text(
        "def search(documents, keyword=''):\n    return [doc for doc in documents if keyword.lower() in str(doc).lower()]\n",
        encoding="utf-8",
    )
    (project / "backend" / "services" / "task_service.py").write_text(
        "def create_task(title, status='todo', priority='medium', owner=''):\n    return {'title': title, 'status': status, 'priority': priority, 'owner': owner}\n",
        encoding="utf-8",
    )
    (project / "backend" / "services" / "report_service.py").write_text(
        "from datetime import datetime\n\n\ndef generate_report(documents, tasks):\n    return '# Local AI Knowledge Studio Report\\nGenerated: ' + datetime.utcnow().isoformat() + '\\nSources: ' + str(len(documents)) + '\\nTasks: ' + str(len(tasks)) + '\\nLimits: mock adapter only unless local model configured.'\n",
        encoding="utf-8",
    )
    (project / "backend" / "adapters" / "local_model_adapter.py").write_text(
        "class LocalModelAdapter:\n    def __init__(self, model_path='', endpoint='', mock=True):\n        self.model_path = model_path\n        self.endpoint = endpoint\n        self.mock = mock\n    def summarize(self, text):\n        if self.mock:\n            return '[MOCK ADAPTER] ' + text[:80]\n        raise RuntimeError('Local model is not configured; cannot claim real inference.')\n",
        encoding="utf-8",
    )
    (project / "backend" / "storage.py").write_text(
        "import json\nfrom pathlib import Path\n\nDB = Path('data/store.json')\n\ndef load():\n    return json.loads(DB.read_text(encoding='utf-8')) if DB.exists() else {'documents': [], 'tasks': []}\n\ndef save(data):\n    DB.parent.mkdir(exist_ok=True); DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (project / "backend" / "models" / "schemas.py").write_text("DOCUMENT_FIELDS=['source','tags','status','text']\nTASK_STATUS=['todo','doing','done']\n", encoding="utf-8")
    (project / "config_schema.json").write_text(json.dumps({"MODEL_PATH": "", "LOCAL_MODEL_ENDPOINT": "", "mock_adapter": True}, indent=2), encoding="utf-8")
    (project / "api_schema.json").write_text(json.dumps({"document_import": "POST /documents", "search": "GET /search", "reports": "POST /reports"}, indent=2), encoding="utf-8")
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project / "README.md").write_text(
        "# Local AI Knowledge Studio\n\nRun: `python main.py`\n\nTest: `python -m pytest tests`\n\nViews: Dashboard, Documents, Search, Tasks, Reports, Settings.\n\nModel config: set MODEL_PATH or LOCAL_MODEL_ENDPOINT. If missing, the app uses a mock adapter clearly marked as mock and does not claim real inference.\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_smoke.py").write_text(
        "from backend.services.document_import import import_document\nfrom backend.services.search_service import search\nfrom backend.adapters.local_model_adapter import LocalModelAdapter\n\n\ndef test_smoke_services():\n    doc = import_document('a.md', 'alpha beta', ['research'])\n    assert search([doc], 'alpha')\n    assert LocalModelAdapter(mock=True).summarize('hello').startswith('[MOCK ADAPTER]')\n",
        encoding="utf-8",
    )
    (project / "data" / "store.json").write_text(json.dumps({"documents": [{"source": "demo.md", "tags": ["demo"], "status": "indexed"}], "tasks": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    (project / "docs" / "DATA_MODEL.md").write_text("Documents: source, tags, status, text. Tasks: title, status, priority, owner. Missing model limit: cannot claim real inference without configured local model file or endpoint.\n", encoding="utf-8")
    for name in ("dashboard_screenshot.png", "documents_screenshot.png", "settings_screenshot.png"):
        visual_evidence.write_runtime_preview_png(project / "screenshots" / name, title=name)
    (project / "customer_runtime.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "clean_environment": True,
                "health_check": "PASS",
                "customer_operation": "PASS",
                "note": "controlled fixture only; synthetic screenshots remain blocked",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _count_files(project: pathlib.Path) -> dict[str, int]:
    files = [item for item in project.rglob("*") if item.is_file()]
    rels = [item.relative_to(project).as_posix().lower() for item in files]
    return {
        "generated_file_count": len(files),
        "source_file_count": sum(1 for rel in rels if rel.endswith((".py", ".js", ".html"))),
        "frontend_file_count": sum(1 for rel in rels if rel.startswith("frontend/") or rel == "index.html"),
        "backend_file_count": sum(1 for rel in rels if rel.startswith("backend/") or rel == "main.py"),
        "test_file_count": sum(1 for rel in rels if rel.startswith("tests/") or "test" in pathlib.PurePosixPath(rel).name),
    }


def run_backend_controlled_eval() -> dict[str, Any]:
    root = OUT / "backend_controlled"
    project = root / "LocalAIKnowledgeStudio"
    _write_large_project(project)
    test_result = real_test_execution.run_tests(project, timeout=60)
    visual_result = visual_evidence.collect_visual_evidence(project)
    manifest = local_packager.package_project(project, startup_command="python main.py", screenshot_path=project / "screenshots" / "dashboard_screenshot.png")
    session_dir = root / "sessions"
    session = bridge.default_session("backend-controlled")
    session["whiteboard"]["project_summary"] = "Local AI Knowledge Studio"
    session["whiteboard"]["delivery_requirements"] = ["README", "启动命令", "测试命令", "TEST_REPORT.md", "screenshots", "final_project_bundle.zip"]
    bridge.save_session(session_dir, session)
    gate = bridge.evaluate_public_delivery_gate(project, manifest, session, phase="final")
    client = FakeTelegramClient()
    sent = bridge.send_delivery_from_manifest(client, "backend-controlled", session_dir, session, manifest)
    arch = architecture_contract.evaluate_project(project, {"mode": "local_model"})
    runnable = runnable_contract.evaluate_project(project)
    counts = _count_files(project)
    bundle = pathlib.Path(str(manifest.get("package_path", project / "final_project_bundle.zip")))
    complete_delivery = gate.get("delivery_allowed") and bundle.exists() and client.documents and client.photos and visual_result.get("verdict") == "PASS"
    classification = "large_project_delivered_controlled_fixture" if complete_delivery else "generated_but_missing_delivery_package"
    result = {
        "run_id": "backend-controlled",
        "run_dir": str(root),
        "provider_mode": "controlled_fixture",
        "project_dir": str(project),
        **counts,
        "README path": str(project / "README.md"),
        "startup_commands": runnable.get("startup_commands", []),
        "test_commands": test_result.get("commands_run", []),
        "architecture_contract_verdict": arch.get("verdict"),
        "runnable_contract_verdict": runnable.get("verdict"),
        "real_test_execution_verdict": test_result.get("verdict"),
        "visual_evidence_verdict": visual_result.get("verdict"),
        "public_delivery_gate_verdict": "PASS" if gate.get("delivery_allowed") else "FAIL",
        "final_project_bundle_path": str(bundle),
        "bundle_size": bundle.stat().st_size if bundle.exists() else 0,
        "telegram_sent_document": len(client.documents),
        "telegram_sent_photo": len(client.photos),
        "classification": classification,
        "missing_evidence": gate.get("missing", []),
        "architecture": arch,
        "runnable": runnable,
        "test_result": test_result,
        "visual_result": visual_result,
        "public_delivery_gate": gate,
        "sent": sent,
    }
    _write_json(OUT / "backend_large_project_eval.json", {"controlled_fixture": result, "real_provider": real_provider_not_run()})
    _write_backend_md(result)
    return result


def real_provider_not_run() -> dict[str, Any]:
    return {
        "provider_mode": "real_provider_api",
        "classification": "not_run_cost_controlled",
        "verdict": "NOT_PROVEN",
        "reason": "本轮为诊断优先；未消耗真实接口额度。后端真实生成能力未证明，只证明受控 provider fixture 下的交付合同。",
    }


def _write_backend_md(result: dict[str, Any]) -> None:
    lines = [
        "# Backend Large Project Eval",
        "",
        f"- classification: {result['classification']}",
        f"- project_dir: {result['project_dir']}",
        f"- files: {result['generated_file_count']}",
        f"- frontend files: {result['frontend_file_count']}",
        f"- backend files: {result['backend_file_count']}",
        f"- test files: {result['test_file_count']}",
        f"- architecture: {result['architecture_contract_verdict']}",
        f"- runnable: {result['runnable_contract_verdict']}",
        f"- real test: {result['real_test_execution_verdict']}",
        f"- visual: {result['visual_evidence_verdict']}",
        f"- delivery gate: {result['public_delivery_gate_verdict']}",
        f"- bundle: {result['final_project_bundle_path']} ({result['bundle_size']} bytes)",
        f"- telegram document/photo: {result['telegram_sent_document']}/{result['telegram_sent_photo']}",
        "",
        "Real provider/API generation was not run in this diagnostic pass; real backend generation ability is not proven by the controlled fixture.",
    ]
    (OUT / "backend_large_project_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    frontdesk = run_frontdesk_eval()
    backend = run_backend_controlled_eval()
    combined = {"frontdesk": frontdesk, "backend_controlled": backend, "real_provider": real_provider_not_run()}
    _write_json(OUT / "combined_eval.json", combined)
    return combined


if __name__ == "__main__":
    data = main()
    print(json.dumps({"frontdesk_average": data["frontdesk"]["overall_average"], "backend": data["backend_controlled"]["classification"]}, ensure_ascii=False, indent=2))
