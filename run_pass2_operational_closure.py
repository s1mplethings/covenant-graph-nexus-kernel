#!/usr/bin/env python3
"""Provider-free operational revision closure through the canonical revision lane."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import canonical_delivery_manifest, canonical_evidence_hash, customer_runtime_runner, local_conversation_manager, local_packager, local_repo_manager, project_revision_lane, real_test_execution
from scripts.main_agent_manager import MainAgentManager


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _app_source(*, priority: bool, max_title: int) -> str:
    priority_read = "priority = args[2] if len(args) > 2 else 'normal'" if priority else "priority = 'normal'"
    priority_store = ", 'priority': priority" if priority else ""
    return f'''import json, pathlib, sys

MAX_TITLE = {max_title}
PRIORITY_ENABLED = {priority!r}

def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

def save(path, rows):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)

def main(argv=None):
    args = list(argv or sys.argv[1:]); path = pathlib.Path("data.json")
    if args and args[0] == "--help": print("usage: main.py [add TITLE|list]"); return 0
    if not args or args[0] == "list":
        print(json.dumps(load(path), ensure_ascii=False)); return 0
    if args[0] != "add" or len(args) < 2: return 2
    title = args[1].strip()
    if not title or len(title) > MAX_TITLE: return 3
    {priority_read}
    rows = load(path); rows.append({{'title': title{priority_store}}}); save(path, rows); return 0

if __name__ == "__main__": raise SystemExit(main())
'''


def _tests_source(*, priority: bool, max_title: int) -> str:
    priority_assert = "self.assertEqual(rows[0]['priority'], 'high')" if priority else "self.assertNotIn('priority', rows[0])"
    return f'''import json, pathlib, tempfile, unittest
import main as app

class AppTests(unittest.TestCase):
    def test_add_list_and_constraint(self):
        with tempfile.TemporaryDirectory() as raw:
            prior = pathlib.Path.cwd(); os_path = pathlib.Path(raw)
            import os; os.chdir(os_path)
            try:
                args = ['add', 'kept task'] + ({['high']!r} if app.PRIORITY_ENABLED else [])
                self.assertEqual(app.main(args), 0)
                rows = json.loads(pathlib.Path('data.json').read_text(encoding='utf-8'))
                self.assertEqual(rows[0]['title'], 'kept task')
                {priority_assert}
                self.assertEqual(app.main(['add', 'x' * ({max_title} + 1)]), 3)
            finally: os.chdir(prior)

if __name__ == '__main__': unittest.main()
'''


def materialize(project: pathlib.Path, *, priority: bool, max_title: int) -> None:
    _write(project / "main.py", _app_source(priority=priority, max_title=max_title))
    _write(project / "tests" / "test_app.py", _tests_source(priority=priority, max_title=max_title))
    _write(project / "README.md", "# Task Ledger\n\nRun `python main.py add TITLE` and `python main.py list`.\n")
    _write(project / "DELIVERY_NOTES.md", "Provider-free deterministic boundary exercise; canonical package and inspection still apply.\n")


def verify(project: pathlib.Path) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=project, capture_output=True, text=True, timeout=30)
    _write(project / "TEST_REPORT.md", f"commands_run:\n- python -m unittest discover -s tests -q\nresults:\n- exit_code: {completed.returncode}\n- stdout: {completed.stdout.strip()}\n- stderr: {completed.stderr.strip()}\n")
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    identity = {"run_id": f"pass2-{project.name}", "candidate_id": f"candidate-{project.name}", "candidate_hash": candidate_hash, "commit_sha": f"provider-free-{project.name}"}
    test_evidence = real_test_execution.run_tests(project, **identity)
    runtime_evidence = customer_runtime_runner.run(project, **identity)
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "test_evidence": test_evidence, "runtime_evidence": runtime_evidence}


def package(project_dir: pathlib.Path, **_: Any) -> dict[str, Any]:
    return local_packager.package_project(project_dir, output_dir=project_dir, startup_command="python main.py list")


def gate(project_dir: pathlib.Path, manifest: dict[str, Any], **_: Any) -> dict[str, Any]:
    inspected = canonical_delivery_manifest.inspect_canonical_delivery_manifest(project_dir, manifest)
    return {"delivery_allowed": inspected.get("status") == "PASS", "is_final": True, "status": inspected.get("status", "FAIL"), "verdict": inspected.get("status", "FAIL"), "inspection": inspected}


def run(output_dir: pathlib.Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CGNK_LOCAL_STUDIO_CONVERSATION_ROOT"] = str(output_dir / "conversations")
    os.environ["CGNK_MANAGED_PROJECT_ROOT"] = str(output_dir / "managed")
    initial = output_dir / "initial"
    materialize(initial, priority=False, max_title=80)
    initial_verify = verify(initial)
    initial_package = package(initial)
    conversation = local_conversation_manager.default_conversation("pass2-operational", source="provider_free_closure")
    local_conversation_manager.update_whiteboard(conversation, {"project_summary": "Persistent local task ledger"}, "pass2")
    project_revision_lane.bind_initial_project_delivery(conversation, initial, initial_package["package_path"], initial_package["manifest_path"])
    rounds = [{"request": "新增 priority 功能", "priority": True, "max_title": 80}, {"request": "改变约束：标题最多 24 字符", "priority": True, "max_title": 24}, {"request": "撤回 priority 功能并保留标题约束", "priority": False, "max_title": 24}]
    results = []
    manager = MainAgentManager()
    for index, spec in enumerate(rounds, start=1):
        prepared = manager.start_project_revision(conversation, spec["request"])
        def provider_execute(out_dir: str, **_: Any) -> dict[str, Any]:
            project = pathlib.Path(out_dir); materialize(project, priority=spec["priority"], max_title=spec["max_title"])
            added = subprocess.run([sys.executable, "main.py", "add", f"round-{index}"] + (["high"] if spec["priority"] else []), cwd=project, capture_output=True, text=True, timeout=10)
            if added.returncode: raise RuntimeError("revision data mutation failed")
            return {"status": "PASS", "provider_mode": "deterministic_boundary", "generated_files": ["main.py", "tests/test_app.py"], "data_add_returncode": added.returncode}
        def finalize(project_dir: pathlib.Path, **_: Any) -> dict[str, Any]:
            check = verify(pathlib.Path(project_dir));
            if check["returncode"]: raise RuntimeError("revision regression failed")
            return {"status": "PASS", "test": check}
        result = manager.execute_project_revision(conversation, prepared["revision_manifest"], {"provider_execute": provider_execute, "post_build_finalize": finalize, "package_project": package, "evaluate_public_delivery_gate": gate, "model": "deterministic-provider-boundary"})
        current = local_repo_manager.current_worktree(local_conversation_manager.get_active_project(conversation)["project_id"])
        listing = subprocess.run([sys.executable, "main.py", "list"], cwd=current, capture_output=True, text=True, timeout=10)
        loaded = project_revision_lane._load_json_object(result["revision_manifest"])
        results.append({"round": index, "request": spec["request"], "execution": result, "data_add_returncode": int((loaded.get("provider_result") or {}).get("data_add_returncode", 1)), "data_rows": json.loads(listing.stdout or "[]"), "regression": (loaded.get("post_build_finalize") or {}).get("test", {})})
    active = local_conversation_manager.get_active_project(conversation)
    package_path = pathlib.Path(active["latest_project_package"])
    cold = output_dir / "cold_start"
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(cold)
    cold_verify = verify(cold)
    cold_list = subprocess.run([sys.executable, "main.py", "list"], cwd=cold, capture_output=True, text=True, timeout=10)
    report = {"kind": "CGKNPass2OperationalClosure", "created_at": datetime.now(timezone.utc).isoformat(), "formal_evidence_status": "NOT_EVALUATED", "provider_mode": "deterministic_boundary", "initial": {"test": initial_verify, "package": initial_package}, "rounds": results, "cold_start": {"test": cold_verify, "data_rows": json.loads(cold_list.stdout or "[]"), "directory": str(cold)}, "status": "PASS" if initial_verify["returncode"] == 0 and all(row["execution"]["status"] == "ready" and row["data_add_returncode"] == 0 and row["regression"]["returncode"] == 0 for row in results) and cold_verify["returncode"] == 0 else "FAIL"}
    (output_dir / "operational_closure.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=pathlib.Path, required=True); args = parser.parse_args(argv)
    report = run(args.output_dir.resolve()); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__": raise SystemExit(main())
