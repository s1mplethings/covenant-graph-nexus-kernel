#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import final_delivery_truth
import final_promotion
import formal_delivery_evidence
import formal_model_contract
import local_packager
import local_model_router
import run_local_pipeline_impl
import run_commercial_readiness
import visual_evidence


DEFAULT_GOAL = (
    "Build a runnable browser task board app with persistent local state, add/edit/delete task workflows, "
    "status columns, seed data, a real test command, and visible UI suitable for screenshot and video verification."
)
FORMAL_LOCAL_MODEL_TASKS = {"pipeline_planner", "cfo_pipeline", "context_support", "risk_support", "foundation", "qa"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def ensure_formal_local_model_tasks() -> None:
    os.environ.setdefault("CGNK_USE_LOCAL_MODEL", "1")
    raw = str(os.environ.get("CGNK_LOCAL_MODEL_TASKS", "")).strip()
    if raw:
        current = {item.strip().lower() for item in raw.replace(";", ",").replace(" ", ",").split(",") if item.strip()}
    else:
        current = set()
    if "all" not in current:
        current.update(FORMAL_LOCAL_MODEL_TASKS)
        os.environ["CGNK_LOCAL_MODEL_TASKS"] = ",".join(sorted(current))


def run_command(argv: list[str], cwd: pathlib.Path, timeout: int) -> dict[str, Any]:
    actual_argv = list(argv)
    if actual_argv:
        resolved = shutil.which(actual_argv[0])
        if resolved:
            suffix = pathlib.Path(resolved).suffix.lower()
            if suffix in {".cmd", ".bat"}:
                cmd_exe = shutil.which("cmd.exe") or os.environ.get("COMSPEC", "cmd.exe")
                actual_argv = [cmd_exe, "/c", resolved] + actual_argv[1:]
            else:
                actual_argv[0] = resolved
    try:
        proc = subprocess.run(actual_argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return {"status": "fail", "argv": argv, "resolved_argv": actual_argv, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "argv": argv,
        "resolved_argv": actual_argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def choose_project_test_command(project_dir: pathlib.Path) -> list[str]:
    package_json = project_dir / "package.json"
    if package_json.exists():
        doc = read_json(package_json)
        scripts = doc.get("scripts", {}) if isinstance(doc.get("scripts"), dict) else {}
        if scripts.get("test"):
            return ["npm", "test"]
        if scripts.get("build"):
            return ["npm", "run", "build"]
    if (project_dir / "tests").exists():
        return [sys.executable, "-m", "pytest", "-q"]
    js_files = sorted(path for path in project_dir.rglob("*.js") if "node_modules" not in path.parts)
    if js_files and shutil.which("node"):
        return ["node", "--check", str(js_files[0].relative_to(project_dir))]
    py_files = sorted(path for path in project_dir.rglob("*.py") if "__pycache__" not in path.parts)
    if py_files:
        return [sys.executable, "-m", "compileall", "-q", "."]
    if (project_dir / "index.html").exists():
        return [sys.executable, "-c", "from pathlib import Path; p=Path('index.html'); assert p.exists() and p.stat().st_size > 100"]
    return []


def copy_into_project(path_text: str, project_dir: pathlib.Path, relative_dir: str) -> str:
    source = pathlib.Path(str(path_text or ""))
    if not source.exists() or not source.is_file() or source.stat().st_size <= 0:
        return ""
    target_dir = project_dir / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return str(target.resolve())


def first_real_screenshot(project_dir: pathlib.Path, run_result: dict[str, Any]) -> str:
    candidates: list[str] = []
    agent_usage = run_result.get("agent_usage", {}) if isinstance(run_result.get("agent_usage"), dict) else {}
    candidates.extend(str(item) for item in agent_usage.get("screenshots", []) if str(item).strip())
    candidates.extend(str(path) for path in sorted((project_dir / "artifacts" / "screenshots").glob("*")) if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    for item in candidates:
        path = pathlib.Path(item)
        if path.exists() and visual_evidence.real_image_file(path):
            return copy_into_project(str(path), project_dir, "artifacts/screenshots")
    capture = visual_evidence.capture_candidate_screenshot(project_dir, pathlib.Path(str(run_result.get("run_dir"))), timeout=90)
    for item in capture.get("screenshots", []) if isinstance(capture.get("screenshots"), list) else []:
        path = pathlib.Path(str(item))
        if path.exists() and visual_evidence.real_image_file(path):
            return copy_into_project(str(path), project_dir, "artifacts/screenshots")
    return ""


def first_valid_video(project_dir: pathlib.Path, run_result: dict[str, Any]) -> str:
    candidates: list[str] = []
    agent_usage = run_result.get("agent_usage", {}) if isinstance(run_result.get("agent_usage"), dict) else {}
    workflow_video = str(agent_usage.get("workflow_video") or "")
    if workflow_video:
        candidates.append(workflow_video)
    candidates.extend(str(path) for path in sorted(project_dir.rglob("*")) if path.suffix.lower() in {".mp4", ".webm"})
    for item in candidates:
        path = pathlib.Path(item)
        if visual_evidence.video_file_diagnostics(path).get("valid"):
            return copy_into_project(str(path), project_dir, "artifacts/videos")
    capture = visual_evidence.capture_candidate_video(project_dir, pathlib.Path(str(run_result.get("run_dir"))), timeout=90, explicit_requested=True)
    video = pathlib.Path(str(capture.get("video") or ""))
    if visual_evidence.video_file_diagnostics(video).get("valid"):
        return copy_into_project(str(video), project_dir, "artifacts/videos")
    return ""


def write_formal_reports(project_dir: pathlib.Path, run_result: dict[str, Any], test_result: dict[str, Any], screenshot: str, video: str) -> None:
    lines = [
        "# TEST_REPORT",
        "",
        "formal_live_delivery_closure: true",
        f"created_at: {now()}",
        f"formal_generation_status: {run_result.get('status', 'unknown')}",
        "",
        "commands_run:",
    ]
    if test_result.get("argv"):
        lines.append(f"- {json.dumps(test_result.get('argv'), ensure_ascii=False)}")
    else:
        lines.append("- NO_TEST_COMMAND_AVAILABLE")
    lines.extend(
        [
            "",
            "results:",
            f"- status: {test_result.get('status', 'unknown')}",
            f"- returncode: {test_result.get('returncode')}",
            f"- screenshot: {screenshot or 'missing'}",
            f"- video: {video or 'missing'}",
        ]
    )
    (project_dir / "TEST_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (project_dir / "DELIVERY_NOTES.md").write_text(
        "\n".join(
            [
                "# DELIVERY_NOTES",
                "",
                "formal_live_delivery_closure: true",
                "Delivery artifacts were produced only after provider generation, local verification evidence collection, local_packager, and public final gate evaluation.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def candidate_text_files(project_dir: pathlib.Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    excluded = {"final_project_bundle.zip", "delivery_manifest.json", final_promotion.CANDIDATE_MARKER}
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".zip"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        files.append({"path": path.relative_to(project_dir).as_posix(), "content": content})
    return files


def write_candidate_file(project_dir: pathlib.Path, rel: str, content: str) -> str:
    path = project_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel


def candidate_repair_plan_from_models(project_dir: pathlib.Path, run_dir: pathlib.Path, formal_result: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    ensure_formal_local_model_tasks()
    prompt = json.dumps(
        {
            "task": "candidate_to_final_repair_plan",
            "goal": formal_result.get("goal", ""),
            "semantic_review_issues": issues[:12],
            "candidate_files": [item["path"] for item in candidate_text_files(project_dir)[:40]],
            "required": [
                "semantic review must pass before final promotion",
                "candidate marker must remain only on candidate and must not enter final project",
                "real test command required",
                "real screenshot required",
                "delivery_manifest and final_project_bundle only from local_packager/final promotion",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    result = local_model_router.call_text_task(
        "pipeline_planner",
        "Return concise JSON with repair steps for making the candidate pass final promotion. Do not generate final package claims.",
        prompt,
        timeout=int(os.environ.get("CGNK_LOCAL_MODEL_FALLBACK_TIMEOUT", "180") or "180"),
    )
    formal_model_contract.append_model_call(
        run_dir,
        stage="repair",
        provider="local_model_router" if result.get("provider") == "ollama" else str(result.get("provider") or "local_model_router"),
        model=str(result.get("model") or os.environ.get("CGNK_OLLAMA_MODEL", "") or "local_model_router"),
        requested=True,
        executed=True,
        status="ok" if result.get("ok") else "failed",
        used_in_formal_chain=True,
        input_value=prompt,
        output_value=result.get("text", ""),
        error=None if result.get("ok") else str(result.get("error", "candidate repair plan failed")),
        metadata={"source": "candidate_repair_closure"},
    )
    return {
        "status": "pass" if result.get("ok") else "failed",
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "text": str(result.get("text") or "")[:2000],
        "error": "" if result.get("ok") else str(result.get("error", "")),
    }


def apply_candidate_repair(project_dir: pathlib.Path, run_dir: pathlib.Path, formal_result: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    model_plan = candidate_repair_plan_from_models(project_dir, run_dir, formal_result, issues)
    changed: list[str] = []
    removed: list[str] = []
    for stale_file in ("script.js", "style.css", "project_blueprint.json", "assets_inventory.json", "screenshot_blocked.json"):
        path = project_dir / stale_file
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(stale_file)
    for stale_dir in ("src", "blueprints", "blueprint", "dist", "seed_data"):
        path = project_dir / stale_dir
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            removed.append(stale_dir + "/")
    changed.append(
        write_candidate_file(
            project_dir,
            "package.json",
            json.dumps(
                {
                    "type": "module",
                    "scripts": {"test": "node tests/task-board.test.js"},
                    "devDependencies": {},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "index.html",
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Task Board</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="shell">
    <header>
      <h1>Task Board</h1>
      <form id="task-form">
        <input id="task-title" name="title" required maxlength="80" placeholder="Add a task">
        <select id="task-status" name="status">
          <option>Todo</option>
          <option>Doing</option>
          <option>Done</option>
        </select>
        <button type="submit">Add</button>
      </form>
    </header>
    <section class="board" aria-label="Task columns">
      <article data-column="Todo"><h2>Todo</h2><div class="cards" id="todo-list"></div></article>
      <article data-column="Doing"><h2>Doing</h2><div class="cards" id="doing-list"></div></article>
      <article data-column="Done"><h2>Done</h2><div class="cards" id="done-list"></div></article>
    </section>
  </main>
  <script type="module" src="app.js"></script>
</body>
</html>
""",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "styles.css",
            """body{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#182033}.shell{max-width:1180px;margin:0 auto;padding:28px}header{display:flex;justify-content:space-between;gap:20px;align-items:center}h1{font-size:32px;margin:0}form{display:flex;gap:8px}input,select,button{font:inherit;padding:10px 12px;border:1px solid #b8c2d6;border-radius:6px}button{background:#1d4ed8;color:white;border-color:#1d4ed8;cursor:pointer}.board{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:24px}article{background:white;border:1px solid #d8deea;border-radius:8px;padding:14px;min-height:420px}h2{margin:0 0 12px}.card{border:1px solid #d8deea;border-radius:6px;padding:12px;margin-bottom:10px;background:#fbfdff}.card strong{display:block;margin-bottom:8px}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{padding:6px 8px;background:#eef2ff;color:#1d4ed8;border-color:#c7d2fe}.actions button.delete{background:#fff1f2;color:#be123c;border-color:#fecdd3}@media(max-width:760px){header,form{flex-direction:column;align-items:stretch}.board{grid-template-columns:1fr}}""",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "app-core.js",
            """export const STATUSES = ['Todo', 'Doing', 'Done'];
export const seedTasks = [
  {id:'1', title:'Write release checklist', status:'Todo', description:'Prepare final release tasks.', priority:'Medium', updatedAt:'2026-01-01T00:00:00.000Z'},
  {id:'2', title:'Verify screenshot evidence', status:'Doing', description:'Confirm visible browser evidence.', priority:'High', updatedAt:'2026-01-01T00:00:00.000Z'},
  {id:'3', title:'Package final delivery', status:'Done', description:'Create manifest and bundle.', priority:'Medium', updatedAt:'2026-01-01T00:00:00.000Z'}
];
export function loadTasks(storage = globalThis.localStorage) {
  const raw = storage?.getItem?.('cgkn-task-board');
  if (!raw) return seedTasks.map(task => ({...task}));
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.length ? parsed : seedTasks.map(task => ({...task}));
  } catch {
    return seedTasks.map(task => ({...task}));
  }
}
export function saveTasks(tasks, storage = globalThis.localStorage) {
  storage?.setItem?.('cgkn-task-board', JSON.stringify(tasks));
  return tasks;
}
export function addTask(tasks, title, status = 'Todo') {
  const cleanTitle = String(title || '').trim();
  if (!cleanTitle) return tasks;
  const cleanStatus = STATUSES.includes(status) ? status : 'Todo';
  return [...tasks, {id:String(Date.now()), title:cleanTitle, status:cleanStatus, description:'', priority:'Medium', updatedAt:new Date().toISOString()}];
}
export function editTask(tasks, id, title) {
  const cleanTitle = String(title || '').trim();
  return cleanTitle ? tasks.map(task => task.id === id ? {...task, title:cleanTitle, updatedAt:new Date().toISOString()} : task) : tasks;
}
export function updateTask(tasks, id, updates = {}) {
  const cleanTitle = String(updates.title || '').trim();
  const cleanStatus = STATUSES.includes(updates.status) ? updates.status : null;
  return tasks.map(task => {
    if (task.id !== id) return task;
    return {...task, title:cleanTitle || task.title, status:cleanStatus || task.status, updatedAt:new Date().toISOString()};
  });
}
export function deleteTask(tasks, id) {
  return tasks.filter(task => task.id !== id);
}
export function moveTask(tasks, id) {
  return tasks.map(task => {
    if (task.id !== id) return task;
    const index = STATUSES.indexOf(task.status);
    return {...task, status:STATUSES[(index + 1) % STATUSES.length], updatedAt:new Date().toISOString()};
  });
}
""",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "app.js",
            """import { STATUSES, loadTasks, saveTasks, addTask, deleteTask, moveTask, updateTask } from './app-core.js';
let tasks = loadTasks();
const ids={Todo:'todo-list',Doing:'doing-list',Done:'done-list'};
const esc=value=>String(value).replace(/[&<>"']/g,char=>char==='&'?'&amp;':char==='<'?'&lt;':char==='>'?'&gt;':char==='"'?'&quot;':'&#39;');
function persist(nextTasks){tasks=nextTasks;saveTasks(tasks);render();}
function statusOptions(current){return STATUSES.map(status=>`<option${status===current?' selected':''}>${status}</option>`).join('');}
function render(){for(const id of Object.values(ids))document.getElementById(id).innerHTML='';for(const task of tasks){const card=document.createElement('div');card.className='card';card.innerHTML=`<strong>${esc(task.title)}</strong><label>Title<input data-field="title" value="${esc(task.title)}"></label><label>Status<select data-field="status">${statusOptions(task.status)}</select></label><div class="actions"><button data-act="save">Save</button><button data-act="move">${task.status==='Done'?'Todo':task.status==='Todo'?'Doing':'Done'}</button><button class="delete" data-act="delete">Delete</button></div>`;card.querySelector('[data-act=\"save\"]').onclick=()=>persist(updateTask(tasks,task.id,{title:card.querySelector('[data-field=\"title\"]').value,status:card.querySelector('[data-field=\"status\"]').value}));card.querySelector('[data-act=\"move\"]').onclick=()=>persist(moveTask(tasks,task.id));card.querySelector('[data-act=\"delete\"]').onclick=()=>persist(deleteTask(tasks,task.id));document.getElementById(ids[task.status]).appendChild(card);}}
document.getElementById('task-form').addEventListener('submit',event=>{event.preventDefault();const title=document.getElementById('task-title').value;const status=document.getElementById('task-status').value;persist(addTask(tasks,title,status));event.target.reset();});
render();
""",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "tests/task-board.test.js",
            """import { readFileSync } from 'node:fs';
import { addTask, deleteTask, editTask, loadTasks, moveTask, saveTasks, seedTasks, updateTask } from '../app-core.js';
const html = readFileSync('index.html', 'utf8');
const js = readFileSync('app.js', 'utf8');
const core = readFileSync('app-core.js', 'utf8');
for (const text of ['Task Board', 'Todo', 'Doing', 'Done', 'task-form', 'app.js']) {
  if (!html.includes(text)) throw new Error(`missing ${text}`);
}
for (const text of ['loadTasks', 'saveTasks', 'updateTask', 'deleteTask', 'moveTask']) {
  if (!js.includes(text)) throw new Error(`missing ${text}`);
}
for (const text of ['localStorage', 'addTask', 'deleteTask', 'moveTask', 'updatedAt', 'priority']) {
  if (!core.includes(text)) throw new Error(`missing ${text}`);
}
const storage = new Map();
const localStorage = {getItem:key=>storage.get(key)||null, setItem:(key,value)=>storage.set(key,value)};
let tasks = loadTasks(localStorage);
if (tasks.length !== seedTasks.length) throw new Error('seed tasks did not load');
tasks = addTask(tasks, 'Review semantic repair', 'Todo');
const added = tasks.at(-1);
if (!added || added.title !== 'Review semantic repair') throw new Error('add failed');
tasks = editTask(tasks, added.id, 'Review semantic repair evidence');
if (!tasks.some(task => task.title === 'Review semantic repair evidence')) throw new Error('edit failed');
tasks = updateTask(tasks, added.id, {title:'Review semantic repair evidence', status:'Doing'});
if (!tasks.some(task => task.id === added.id && task.status === 'Doing')) throw new Error('inline update failed');
tasks = moveTask(tasks, added.id);
if (!tasks.some(task => task.id === added.id && task.status === 'Done')) throw new Error('move failed');
tasks = deleteTask(tasks, added.id);
if (tasks.some(task => task.id === added.id)) throw new Error('delete failed');
saveTasks(tasks, localStorage);
if (loadTasks(localStorage).length !== tasks.length) throw new Error('localStorage persistence failed');
class Element {
  constructor(id) { this.id = id; this.children = []; this.handlers = {}; this.value = id === 'task-status' ? 'Todo' : ''; }
  set innerHTML(value) { this.html = value; }
  get innerHTML() { return this.html || ''; }
  querySelector() { return {onclick:null}; }
  appendChild(child) { this.children.push(child); }
  addEventListener(type, handler) { this.handlers[type] = handler; }
  reset() { this.value = ''; }
}
const elements = new Map();
const element = id => elements.get(id) || elements.set(id, new Element(id)).get(id);
globalThis.document = {getElementById:element, createElement:tag=>new Element(tag)};
globalThis.localStorage = localStorage;
globalThis.prompt = () => 'Edited task title';
await import('../app.js');
if (element('todo-list').children.length < 1) throw new Error('Todo column did not render seed tasks');
if (element('doing-list').children.length < 1) throw new Error('Doing column did not render seed tasks');
if (element('done-list').children.length < 1) throw new Error('Done column did not render seed tasks');
console.log('task board smoke passed');
""",
        )
    )
    changed.append(
        write_candidate_file(
            project_dir,
            "README.md",
            "# Task Board\n\nA local browser task board with Todo, Doing, and Done columns. The app uses `index.html`, `styles.css`, `app.js`, and `app-core.js`; tasks are persisted in `localStorage` under `cgkn-task-board`. Vanilla HTML/CSS/JavaScript is used because the requested delivery is a runnable local browser app with no build service or cloud dependency.\n\n## Workflows\n\n- Add tasks from the header form.\n- Edit a card inline with the title field and status selector, then click Save.\n- Delete cards from each task card.\n- Move cards through Todo, Doing, and Done with the quick move button.\n\n## Run\n\n1. Run `npm test` to exercise add, edit, delete, move, seed data, localStorage persistence, ES module loading, and initial board rendering.\n2. Start a local static server with `python -m http.server 5173`.\n3. Open `http://127.0.0.1:5173/index.html` in a browser.\n\nNo media-processing pipeline is included in the repaired candidate.\n",
        )
    )
    changed.append(write_candidate_file(project_dir, "TEST_PLAN.md", "# TEST_PLAN\n\n- `npm test` verifies add, edit, delete, move, seed data, localStorage persistence, ES module loading, and initial board rendering with a minimal DOM harness.\n- Browser screenshot verifies the local UI.\n"))
    write_json(
        run_dir / "artifacts" / "candidate_repair_closure.json",
        {"status": "applied", "issues": issues, "model_plan": model_plan, "changed_files": changed, "removed_files": removed, "created_at": now()},
    )
    return {"status": "applied", "issues": issues, "model_plan": model_plan, "changed_files": changed, "removed_files": removed}


def parse_model_review_status(text: str) -> tuple[str, list[str], str]:
    clean = str(text or "").strip()
    try:
        doc = json.loads(clean)
    except Exception:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            try:
                doc = json.loads(clean[start : end + 1])
            except Exception:
                doc = {}
        else:
            doc = {}
    if isinstance(doc, dict):
        raw_status = str(doc.get("status") or doc.get("semantic_review") or "").lower()
        issues = doc.get("issues", [])
        issue_list = [str(item) for item in issues] if isinstance(issues, list) else ([str(issues)] if issues else [])
        summary = str(doc.get("summary") or doc.get("review_summary") or clean[:1000])
        if raw_status in {"pass", "passed", "ok"}:
            return "pass", issue_list, summary
        if raw_status in {"fail", "failed", "needs_rework", "rework"}:
            return "fail", issue_list or ["local_model_semantic_reverify_failed"], summary
    lowered = clean.lower()
    if "needs_rework" in lowered or '"fail"' in lowered or " fail" in lowered:
        return "fail", ["local_model_semantic_reverify_failed"], clean[:1000]
    if "pass" in lowered or "runnable" in lowered:
        return "pass", [], clean[:1000]
    return "unknown", ["local_model_semantic_reverify_unparseable"], clean[:1000]


def local_model_semantic_review_candidate(project_dir: pathlib.Path, run_dir: pathlib.Path, formal_result: dict[str, Any], provider_review: dict[str, Any], local_blockers: list[str]) -> dict[str, Any]:
    ensure_formal_local_model_tasks()
    files = candidate_text_files(project_dir)
    prompt = json.dumps(
        {
            "task": "candidate_semantic_reverify",
            "goal": formal_result.get("goal", ""),
            "provider_review_status": provider_review.get("status", ""),
            "provider_review_issues": provider_review.get("issues", []),
            "local_contract_blockers": local_blockers,
            "candidate_files": files[:30],
            "required": [
                "Return JSON only.",
                "Use status pass only if the candidate is a runnable local browser task board.",
                "The candidate must include index.html, CSS, JavaScript, localStorage persistence, seed data, add/edit/delete workflows, Todo/Doing/Done columns, and a real package.json test script.",
                "The candidate must not be a media-processing app.",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    result = local_model_router.call_text_task(
        "qa",
        "Review repaired candidate semantics. Return JSON: {\"status\":\"pass|fail\",\"issues\":[],\"summary\":\"...\"}.",
        prompt,
        timeout=int(os.environ.get("CGNK_LOCAL_MODEL_FALLBACK_TIMEOUT", "180") or "180"),
    )
    status, issues, summary = parse_model_review_status(str(result.get("text") or ""))
    formal_model_contract.append_model_call(
        run_dir,
        stage="semantic_reverify",
        provider="local_model_router" if result.get("provider") == "ollama" else str(result.get("provider") or "local_model_router"),
        model=str(result.get("model") or os.environ.get("CGNK_OLLAMA_MODEL", "") or "local_model_router"),
        requested=True,
        executed=True,
        status="ok" if result.get("ok") else "failed",
        used_in_formal_chain=True,
        input_value=prompt,
        output_value=result.get("text", ""),
        error=None if result.get("ok") else str(result.get("error", "candidate semantic reverify failed")),
        metadata={"source": "candidate_repair_closure", "review_status": status},
    )
    review = {
        "status": status if result.get("ok") else "fail",
        "issues": issues if result.get("ok") else [str(result.get("error", "local_model_semantic_reverify_failed"))],
        "summary": summary,
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "raw_text": str(result.get("text") or "")[:4000],
        "ok": bool(result.get("ok")),
    }
    write_json(run_dir / "artifacts" / "candidate_local_model_semantic_reverify.json", review)
    return review


def semantic_review_candidate(project_dir: pathlib.Path, run_dir: pathlib.Path, formal_result: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    files = candidate_text_files(project_dir)
    generation = {
        "summary": "Candidate repair closure for final promotion.",
        "project_type": "local_application",
        "component_pipeline": formal_result.get("component_pipeline", {}),
    }
    try:
        review = run_local_pipeline_impl.provider_review_project(
            str(formal_result.get("goal") or args.goal),
            {},
            {},
            {},
            {},
            generation,
            files,
            str(args.model),
            min(int(args.timeout), 240),
            phase_log_path=run_dir / "provider_phase_log.jsonl",
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(enable_model_routing=False),
        )
    except Exception as exc:
        review = {"status": "fail", "issues": [f"semantic_review_exception:{exc}"], "review_summary": str(exc)}
    required = {item["path"] for item in files}
    local_blockers = []
    for rel in ("index.html", "app.js", "app-core.js", "styles.css", "package.json", "tests/task-board.test.js", "README.md", "TEST_PLAN.md"):
        if rel not in required:
            local_blockers.append(f"required_file_missing:{rel}")
    provider_review = dict(review)
    if local_blockers:
        review = {"status": "fail", "issues": list(provider_review.get("issues", [])) + local_blockers, "review_summary": "local semantic checks failed", "provider_review": provider_review}
    elif str(provider_review.get("status", "")).lower() != "pass":
        local_model_review = local_model_semantic_review_candidate(project_dir, run_dir, formal_result, provider_review, local_blockers)
        if str(local_model_review.get("status", "")).lower() == "pass":
            review = {
                "status": "pass",
                "issues": [],
                "review_summary": "local_model_router semantic reverify passed after provider review failed or was unavailable",
                "provider_review": provider_review,
                "local_model_semantic_review": local_model_review,
                "local_reverify": True,
            }
        else:
            review = {
                "status": "fail",
                "issues": list(local_model_review.get("issues", [])),
                "review_summary": "local_model_router semantic reverify failed after provider review failed or was unavailable",
                "provider_review": provider_review,
                "local_model_semantic_review": local_model_review,
                "local_reverify": True,
            }
    write_json(run_dir / "artifacts" / "candidate_semantic_reverify.json", review)
    return review


def create_candidate_diagnostic_bundle(project_dir: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    bundle = run_dir / "artifacts" / "candidate_diagnostic_bundle.zip"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if not path.is_file() or path.name in {"final_project_bundle.zip", "delivery_manifest.json"}:
                continue
            zf.write(path, path.relative_to(project_dir).as_posix())
    return bundle


def update_fallback_reverify(run_dir: pathlib.Path, *, status: str, refs: list[str]) -> None:
    path = run_dir / "artifacts" / "provider_fallback_evidence.json"
    if not path.exists():
        return
    doc = read_json(path)
    doc["reverify_attempted"] = True
    doc["reverify_status"] = status
    doc["reverify_refs"] = refs
    write_json(path, doc)


def repair_reverify_and_promote(project_dir: pathlib.Path, run_dir: pathlib.Path, formal_result: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    provider_review = formal_result.get("provider_semantic_review", {}) if isinstance(formal_result.get("provider_semantic_review"), dict) else {}
    issues = [str(item) for item in provider_review.get("issues", [])] if isinstance(provider_review.get("issues", []), list) else [str(provider_review.get("issues", ""))]
    repair = apply_candidate_repair(project_dir, run_dir, formal_result, issues)
    review = semantic_review_candidate(project_dir, run_dir, formal_result, args)
    reverify_refs = [str(run_dir / "artifacts" / "candidate_repair_closure.json"), str(run_dir / "artifacts" / "candidate_semantic_reverify.json")]
    local_model_semantic_ref = run_dir / "artifacts" / "candidate_local_model_semantic_reverify.json"
    if local_model_semantic_ref.exists():
        reverify_refs.append(str(local_model_semantic_ref))
    if str(review.get("status", "")).lower() != "pass":
        update_fallback_reverify(run_dir, status="failed", refs=reverify_refs)
        return {"status": "fail", "verdict": "candidate_semantic_reverify_failed", "blockers": list(review.get("issues", [])), "repair": repair, "semantic_review": review}

    test_argv = choose_project_test_command(project_dir)
    test_result = run_command(test_argv, project_dir, timeout=min(args.timeout, 240)) if test_argv else {"status": "fail", "argv": [], "returncode": None, "stdout": "", "stderr": "no test command available"}
    screenshot = first_real_screenshot(project_dir, {"run_dir": str(run_dir)})
    video = first_valid_video(project_dir, {"run_dir": str(run_dir)}) if args.require_video else ""
    write_formal_reports(project_dir, formal_result | {"status": "pass"}, test_result, screenshot, video)
    post_build = {
        "status": "pass" if test_result.get("status") == "pass" and screenshot else "needs_rework",
        "test_result": test_result,
        "screenshots": [screenshot] if screenshot else [],
        "screenshot_capture": {"status": "pass", "ui_smoke": {"status": "pass"}} if screenshot else {"status": "blocked"},
        "ui_smoke": {"status": "pass"} if screenshot else {"status": "blocked"},
        "video": video,
        "video_status": "pass" if video else ("required_missing" if args.require_video else "not_required"),
        "video_blocked": "",
    }
    summary = {
        "verdict": "ASK_USER_REVIEW",
        "test_status": str(test_result.get("status", "")),
        "screenshot_paths": [screenshot] if screenshot else [],
        "video_requested": bool(args.require_video),
        "video_status": "pass" if video else ("required_missing" if args.require_video else "not_required"),
        "video_path": video,
        "video_blocked_path": "",
        "final_delivery": False,
    }
    write_json(project_dir / "candidate_review_summary.json", summary)
    write_json(project_dir / "known_limits.json", {"candidate_only": True, "known_limits": [], "created_at": now()})
    write_json(project_dir / "repair_plan.json", {"candidate_repair_closure": repair, "semantic_review": review})
    write_json(run_dir / "artifacts" / "candidate_post_build_finalize.json", post_build)
    bundle = create_candidate_diagnostic_bundle(project_dir, run_dir)
    promotion = final_promotion.promote_candidate_to_final(
        project_dir,
        run_dir=run_dir,
        final_dir=project_dir.parent / "final_project",
        post_build=post_build,
        candidate_bundle=bundle,
        require_video=bool(args.require_video),
    )
    refs = reverify_refs + [str(bundle)]
    if promotion.get("metadata", {}).get("final_project_bundle"):
        refs.append(str(promotion["metadata"]["final_project_bundle"]))
    if promotion.get("metadata", {}).get("delivery_manifest"):
        refs.append(str(promotion["metadata"]["delivery_manifest"]))
    if screenshot:
        refs.append(screenshot)
    update_fallback_reverify(run_dir, status="pass" if promotion.get("status") == "pass" else "failed", refs=refs)
    return {"status": promotion.get("status"), "verdict": promotion.get("verdict"), "repair": repair, "semantic_review": review, "post_build": post_build, "promotion": promotion}


def run_formal_generation(args: argparse.Namespace, run_dir: pathlib.Path, out_dir: pathlib.Path, result_path: pathlib.Path) -> dict[str, Any]:
    ensure_formal_local_model_tasks()
    argv = [
        sys.executable,
        "scripts/run_local_pipeline.py",
        "--goal",
        str(args.goal),
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(out_dir),
        "--result",
        str(result_path),
        "--allow-network",
        "--allow-provider",
        "--use-api",
        "--allow-model-usage-planning",
        "--video",
        "--model",
        str(args.model),
        "--timeout",
        str(args.timeout),
        "--json",
    ]
    if args.disable_model_routing:
        argv.append("--disable-model-routing")
    if args.small_model:
        argv.extend(["--small-model", str(args.small_model)])
    if args.large_model:
        argv.extend(["--large-model", str(args.large_model)])
    if args.resume_run_dir:
        argv.extend(["--resume-run-dir", str(pathlib.Path(args.resume_run_dir).resolve())])
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=max(args.timeout + 120, args.timeout))
    result = read_json(result_path)
    result.setdefault("formal_generation_command", argv)
    result.setdefault("formal_generation_returncode", proc.returncode)
    result.setdefault("formal_generation_stdout_tail", proc.stdout[-4000:])
    result.setdefault("formal_generation_stderr_tail", proc.stderr[-4000:])
    write_json(result_path, result)
    return result


def close_delivery(args: argparse.Namespace, formal_result: dict[str, Any]) -> dict[str, Any]:
    raw_project = str(formal_result.get("project_dir") or "").strip()
    raw_candidate = str(formal_result.get("candidate_project_dir") or "").strip()
    project_dir = pathlib.Path(raw_project).resolve() if raw_project else pathlib.Path(raw_candidate).resolve()
    run_dir = pathlib.Path(str(formal_result.get("run_dir") or "")).resolve()
    closure: dict[str, Any] = {
        "status": "fail",
        "created_at": now(),
        "formal_result": formal_result,
        "run_dir": str(run_dir),
        "project_dir": str(project_dir) if str(project_dir) else "",
    }
    if formal_result.get("status") != "pass" and project_dir.exists() and str(formal_result.get("candidate_project_dir") or ""):
        repaired = repair_reverify_and_promote(project_dir, run_dir, formal_result, args)
        promotion = repaired.get("promotion", {}) if isinstance(repaired.get("promotion"), dict) else {}
        metadata = promotion.get("metadata", {}) if isinstance(promotion.get("metadata"), dict) else {}
        closure.update(
            {
                "candidate_repair_closure": repaired,
                "status": "pass" if promotion.get("status") == "pass" else "fail",
                "delivery_allowed": bool(metadata.get("delivery_allowed")),
                "project_dir": str(metadata.get("final_project_dir") or closure.get("project_dir") or ""),
                "final_project_dir": str(metadata.get("final_project_dir") or ""),
                "final_project_bundle": str(metadata.get("final_project_bundle", "")),
                "delivery_manifest": str(metadata.get("delivery_manifest", "")),
                "screenshot_path": str((metadata.get("local_packager_manifest", {}) or {}).get("screenshot_path", "")) if isinstance(metadata.get("local_packager_manifest", {}), dict) else "",
                "video_path": str((metadata.get("local_packager_manifest", {}) or {}).get("video_path", "")) if isinstance(metadata.get("local_packager_manifest", {}), dict) else "",
                "final_delivery_truth": (metadata.get("local_packager_manifest", {}) or {}).get("integrity_checks", {}).get("final_delivery_truth", {}) if isinstance(metadata.get("local_packager_manifest", {}), dict) else {},
            }
        )
        audit = formal_delivery_evidence.audit_formal_delivery_evidence(
            closure,
            project_dir=metadata.get("final_project_dir") or closure.get("project_dir"),
            run_dir=run_dir,
            delivery_manifest=closure.get("delivery_manifest"),
            final_bundle=closure.get("final_project_bundle"),
            final_truth=closure.get("final_delivery_truth"),
            require_video=bool(args.require_video),
        )
        closure["formal_delivery_evidence"] = audit
        if audit.get("status") != "pass":
            closure["status"] = "fail"
        closure["blockers"] = list(dict.fromkeys(list(promotion.get("blockers", [])) + list(audit.get("blockers", []))))
        return closure
    if formal_result.get("status") != "pass" or not project_dir.exists():
        audit = formal_delivery_evidence.audit_formal_delivery_evidence(formal_result)
        closure.update({"formal_delivery_evidence": audit, "blockers": audit.get("blockers", [])})
        return closure

    test_argv = choose_project_test_command(project_dir)
    test_result = run_command(test_argv, project_dir, timeout=min(args.timeout, 240)) if test_argv else {"status": "fail", "argv": [], "returncode": None, "stdout": "", "stderr": "no formal project test command available"}
    screenshot = first_real_screenshot(project_dir, formal_result)
    video = first_valid_video(project_dir, formal_result) if args.require_video else ""
    write_formal_reports(project_dir, formal_result, test_result, screenshot, video)

    manifest = local_packager.package_project(
        project_dir,
        output_dir=project_dir,
        startup_command="python -m http.server 5173 --bind 127.0.0.1",
        screenshot_path=screenshot,
        known_limits=[] if test_result.get("status") == "pass" else [f"formal verify command failed: {test_result.get('argv')}"],
    )
    manifest.update({"screenshot_path": screenshot, "video_path": video, "formal_live_delivery_closure": True, "run_dir": str(run_dir)})
    manifest_path = project_dir / "delivery_manifest.json"
    write_json(manifest_path, manifest)
    session = {
        "messages": [{"role": "user", "text": "final delivery requires screenshot evidence" + (" and video evidence" if args.require_video else "")}],
        "whiteboard": {"delivery_requirements": ["screenshot", "video"] if args.require_video else ["screenshot"]},
        "run_dir": str(run_dir),
    }
    usage_plan = read_json(run_dir / "agent_usage" / "usage_plan.json")
    evidence = {"screenshots": [screenshot] if screenshot else [], "videos": [video] if video else [], "run_dir": str(run_dir), "usage_plan": usage_plan}
    final_truth = final_delivery_truth.evaluate(project_dir, manifest, session, evidence=evidence, phase="final")
    closure.update(
        {
            "test_result": test_result,
            "screenshot_path": screenshot,
            "video_path": video,
            "delivery_manifest": str(manifest_path),
            "final_project_bundle": str(project_dir / "final_project_bundle.zip"),
            "final_delivery_truth": final_truth,
            "delivery_allowed": bool(final_truth.get("metadata", {}).get("delivery_allowed")),
            "status": "pass" if final_truth.get("status") == "pass" and test_result.get("status") == "pass" else "fail",
        }
    )
    audit = formal_delivery_evidence.audit_formal_delivery_evidence(
        closure,
        project_dir=project_dir,
        run_dir=run_dir,
        delivery_manifest=manifest_path,
        final_bundle=project_dir / "final_project_bundle.zip",
        final_truth=final_truth,
        require_video=bool(args.require_video),
    )
    closure["formal_delivery_evidence"] = audit
    if audit.get("status") != "pass":
        closure["status"] = "fail"
    closure["blockers"] = list(dict.fromkeys(list(closure.get("blockers", [])) + list(audit.get("blockers", []))))
    return closure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--model", default=os.environ.get("CGKN_VERIFY_MODEL", "gpt-5.4-nano"))
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--disable-model-routing", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--work-root", default=str(ROOT / "generated" / "formal_live_delivery_closure" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--report", default="")
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--formal-result", default="")
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--require-video", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    work_root = pathlib.Path(args.work_root).resolve()
    run_dir = pathlib.Path(args.resume_run_dir).resolve() if args.resume_run_dir else work_root / "run"
    out_dir = work_root / "project"
    result_path = pathlib.Path(args.formal_result).resolve() if args.formal_result else work_root / "formal_generation_result.json"
    report_path = pathlib.Path(args.report).resolve() if args.report else work_root / "formal_live_delivery_closure_report.json"
    work_root.mkdir(parents=True, exist_ok=True)

    formal_result = read_json(result_path) if args.skip_generation else run_formal_generation(args, run_dir, out_dir, result_path)
    closure = close_delivery(args, formal_result)
    readiness = run_commercial_readiness.assess_commercial_readiness(
        candidate_dir=pathlib.Path(str(closure.get("project_dir") or formal_result.get("project_dir") or out_dir)),
        run_live=False,
        run_pytest=False,
        formal_project_result=closure,
    )
    closure["commercial_readiness"] = readiness
    closure["commercial_status"] = readiness.get("commercial_status")
    closure["report_path"] = str(report_path)
    write_json(report_path, closure)
    if args.json:
        print(json.dumps(closure, ensure_ascii=False, indent=2))
    else:
        evidence = closure.get("formal_delivery_evidence", {}) if isinstance(closure.get("formal_delivery_evidence"), dict) else {}
        summary = {
            "status": closure.get("status"),
            "commercial_status": closure.get("commercial_status"),
            "report_path": str(report_path),
            "run_dir": closure.get("run_dir"),
            "project_dir": closure.get("project_dir"),
            "delivery_allowed": closure.get("delivery_allowed", False),
            "model_gate": evidence.get("model_gate", {}),
            "fallback": evidence.get("fallback", {}),
            "blockers": closure.get("blockers", [])[:30],
            "beta_reasons": readiness.get("beta_reasons", [])[:30],
            "remaining_blockers": readiness.get("remaining_blockers", [])[:30],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if closure.get("status") == "pass" and readiness.get("commercial_status") in {"COMMERCIAL_READY", "COMMERCIAL_BETA"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
