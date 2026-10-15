#!/usr/bin/env python3
"""Provider-free operational revision closure through the canonical revision lane."""
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import canonical_evidence_hash, codex_conversation, customer_runtime_runner, local_conversation_manager, local_packager, local_repo_manager, production_candidate_provenance, project_revision_lane, provider_causal_trace, real_test_execution
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
    if args[0] != "add" or len(args) < 2 or len(args) > ({3 if priority else 2}): return 2
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
    _write(project / "TEST_PLAN.md", "Verify add/list persistence, title limits, priority lifecycle, and cold start.\n")
    _write(project / "DELIVERY_NOTES.md", "Provider-free deterministic boundary exercise; canonical package and inspection still apply.\n")


def seal_provider_free_candidate(
    project: pathlib.Path,
    run_root: pathlib.Path,
    identity: dict[str, str],
) -> dict[str, Any]:
    """Create canonical provenance for the deterministic Provider boundary."""
    run_root.mkdir(parents=True, exist_ok=True)
    staging = run_root / "provider_staging"
    generated_files: list[str] = []
    for source in canonical_evidence_hash.iter_candidate_source_files(project):
        try:
            source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = source.relative_to(project)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source.unlink()
        generated_files.append(relative.as_posix())
    provider_result_path = run_root / "provider_generation_result.json"
    provider_result_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "provider_semantic_review": {"status": "pass"},
                "generated_files": sorted(generated_files),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    receipts: dict[str, pathlib.Path] = {}
    entry_started = provider_causal_trace.now()
    receipts["production_entry"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="production_entry",
        candidate_root=project,
        started_at=entry_started,
        finished_at=provider_causal_trace.now(),
        **identity,
    )
    generation_started = provider_causal_trace.now()
    request = provider_causal_trace.begin_provider_request(
        candidate_dir=project,
        production_run_dir=run_root,
        identity=identity,
        goal="provider-free operational revision closure",
        model="deterministic-provider-boundary",
        request_started_at=generation_started,
    )
    capture = provider_causal_trace.consume_provider_response(
        candidate_dir=project,
        provider_staging_dir=staging,
        production_run_dir=run_root,
        provider_result_path=provider_result_path,
        identity=identity,
        provider_request_capture=request,
        response_received_at=provider_causal_trace.now(),
    )
    provider_document = json.loads(provider_result_path.read_text(encoding="utf-8"))
    provider_document.update(
        {
            "project_dir": str(project.resolve()),
            "provider_staging_dir": str(staging.resolve()),
            "provider_causal_artifacts": {
                key: str(value) if isinstance(value, pathlib.Path) else value
                for key, value in capture.items()
            },
        }
    )
    provider_result_path.write_text(
        json.dumps(provider_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    provider_ref = {
        "role": "provider_generation_result",
        "ref": str(provider_result_path.resolve()),
        "hash": canonical_evidence_hash.sha256_file(provider_result_path),
    }
    causal_refs = [
        {
            "role": role,
            "ref": str(pathlib.Path(capture[key]).resolve()),
            "hash": canonical_evidence_hash.sha256_file(capture[key]),
        }
        for role, key in (
            ("provider_request", "request_ref"),
            ("provider_response", "response_ref"),
            ("implementation_decision", "decision_ref"),
            ("implementation_patch", "patch_ref"),
            ("patch_application", "application_ref"),
        )
    ]
    receipts["provider_generation"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_generation",
        candidate_root=project,
        started_at=generation_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[provider_ref, *causal_refs],
        **identity,
    )
    validation_started = provider_causal_trace.now()
    receipts["provider_validation"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_validation",
        candidate_root=project,
        started_at=validation_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[provider_ref, *causal_refs],
        **identity,
    )
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": canonical_evidence_hash.candidate_source_manifest(project)},
        (),
    )
    post_build_started = provider_causal_trace.now()
    receipts["post_build"] = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="post_build",
        candidate_root=project,
        started_at=post_build_started,
        finished_at=provider_causal_trace.now(),
        candidate_hash=candidate_hash,
        candidate_source_manifest_hash=manifest_hash,
        **identity,
    )
    provenance = production_candidate_provenance.produce(
        project,
        run_root,
        stage_receipts=receipts,
        provider_result_ref=provider_result_path,
        **identity,
    )
    provider_causal_trace.finalize(
        candidate_dir=project,
        production_run_dir=run_root,
        identity=identity,
        causal_capture=capture,
        production_provenance_ref=provenance["provenance_ref"],
    )
    return provenance


def verify(project: pathlib.Path, *, run_root: pathlib.Path) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=project, capture_output=True, text=True, timeout=30)
    _write(project / "TEST_REPORT.md", f"commands_run:\n- python -m unittest discover -s tests -q\nresults:\n- exit_code: {completed.returncode}\n- stdout: {completed.stdout.strip()}\n- stderr: {completed.stderr.strip()}\n")
    identity = {
        "run_id": f"pass3-{run_root.name}",
        "candidate_id": f"candidate-{run_root.name}",
        "commit_sha": f"provider-free-{run_root.name}",
    }
    provenance = seal_provider_free_candidate(project, run_root, identity)
    evidence_identity = {
        **identity,
        "candidate_hash": str(provenance["candidate_hash"]),
        "production_provenance_ref": str(provenance["provenance_ref"]),
        "production_provenance_hash": str(provenance["provenance_hash"]),
    }
    test_evidence = real_test_execution.run_tests(project, **evidence_identity)
    runtime_evidence = customer_runtime_runner.run(project, **evidence_identity)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "provenance": provenance,
        "test_evidence": test_evidence,
        "runtime_evidence": runtime_evidence,
    }


def package(project_dir: pathlib.Path, **_: Any) -> dict[str, Any]:
    return local_packager.package_project(project_dir, output_dir=project_dir, startup_command="python main.py list")


def independent_business_acceptance(
    project: pathlib.Path,
    *,
    round_index: int,
    priority_enabled: bool,
    max_title: int,
) -> dict[str, Any]:
    """Exercise the delivered CLI without importing its implementation or tests."""
    listing = subprocess.run(
        [sys.executable, "main.py", "list"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    errors: list[str] = []
    try:
        rows = json.loads(listing.stdout)
    except (TypeError, ValueError):
        rows = []
        errors.append("list_output_not_json")
    expected_titles = [f"round-{index}" for index in range(1, round_index + 1)]
    if listing.returncode != 0 or [row.get("title") for row in rows] != expected_titles:
        errors.append("persisted_titles_mismatch")
    for index, row in enumerate(rows, start=1):
        if index < round_index or priority_enabled:
            if row.get("priority") != "high":
                errors.append(f"priority_history_mismatch:{index}")
        elif "priority" in row:
            errors.append(f"withdrawn_priority_persisted_on_new_row:{index}")
    too_long = subprocess.run(
        [sys.executable, "main.py", "add", "x" * (max_title + 1)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if too_long.returncode != 3:
        errors.append("title_limit_not_enforced")
    priority_probe = subprocess.run(
        [sys.executable, "main.py", "add", "probe", "high"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    expected_priority_returncode = 0 if priority_enabled else 2
    if priority_probe.returncode != expected_priority_returncode:
        errors.append("priority_interface_state_mismatch")
    if priority_enabled:
        data_path = project / "data.json"
        current = json.loads(data_path.read_text(encoding="utf-8"))
        if not current or current[-1] != {"title": "probe", "priority": "high"}:
            errors.append("priority_semantics_mismatch")
        else:
            current.pop()
            data_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    return {
        "kind": "CGKNIndependentBusinessAcceptance",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "rows": rows,
        "expected_titles": expected_titles,
        "priority_enabled": priority_enabled,
        "max_title": max_title,
    }


def gate(project_dir: pathlib.Path, manifest: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return codex_conversation.evaluate_public_delivery_gate(
        project_dir,
        manifest,
        conversation=kwargs.get("conversation"),
        phase="final",
    )


def _run_scoped(output_dir: pathlib.Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    initial = output_dir / "initial"
    materialize(initial, priority=False, max_title=80)
    initial_verify = verify(initial, run_root=output_dir / "evidence" / "initial")
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
            acceptance = independent_business_acceptance(
                pathlib.Path(project_dir),
                round_index=index,
                priority_enabled=spec["priority"],
                max_title=spec["max_title"],
            )
            if acceptance["status"] != "PASS":
                raise RuntimeError("independent business acceptance failed")
            check = verify(
                pathlib.Path(project_dir),
                run_root=output_dir / "evidence" / f"round-{index}",
            )
            if check["returncode"]: raise RuntimeError("revision regression failed")
            return {"status": "PASS", "test": check, "independent_business_acceptance": acceptance}
        result = manager.execute_project_revision(conversation, prepared["revision_manifest"], {"provider_execute": provider_execute, "post_build_finalize": finalize, "package_project": package, "evaluate_public_delivery_gate": gate, "model": "deterministic-provider-boundary"})
        current = local_repo_manager.current_worktree(local_conversation_manager.get_active_project(conversation)["project_id"])
        listing = subprocess.run([sys.executable, "main.py", "list"], cwd=current, capture_output=True, text=True, timeout=10)
        loaded = project_revision_lane._load_json_object(result["revision_manifest"])
        results.append({"round": index, "request": spec["request"], "execution": result, "data_add_returncode": int((loaded.get("provider_result") or {}).get("data_add_returncode", 1)), "data_rows": json.loads(listing.stdout or "[]"), "regression": (loaded.get("post_build_finalize") or {}).get("test", {}), "independent_business_acceptance": (loaded.get("post_build_finalize") or {}).get("independent_business_acceptance", {})})
    active = local_conversation_manager.get_active_project(conversation)
    package_path = pathlib.Path(active["latest_project_package"])
    cold = output_dir / "cold_start"
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(cold)
    cold_acceptance = independent_business_acceptance(
        cold,
        round_index=3,
        priority_enabled=False,
        max_title=24,
    )
    cold_verify = verify(cold, run_root=output_dir / "evidence" / "cold-start")
    cold_list = subprocess.run([sys.executable, "main.py", "list"], cwd=cold, capture_output=True, text=True, timeout=10)
    report = {"kind": "CGKNPass2OperationalClosure", "created_at": datetime.now(timezone.utc).isoformat(), "formal_evidence_status": "NOT_EVALUATED", "provider_mode": "deterministic_boundary", "initial": {"test": initial_verify, "package": initial_package}, "rounds": results, "cold_start": {"test": cold_verify, "independent_business_acceptance": cold_acceptance, "data_rows": json.loads(cold_list.stdout or "[]"), "directory": str(cold)}, "status": "PASS" if initial_verify["returncode"] == 0 and all(row["execution"]["status"] == "ready" and row["data_add_returncode"] == 0 and row["regression"]["returncode"] == 0 and row["independent_business_acceptance"].get("status") == "PASS" and row["execution"].get("public_delivery_gate", {}).get("delivery_allowed") is True for row in results) and cold_verify["returncode"] == 0 and cold_acceptance["status"] == "PASS" else "FAIL"}
    (output_dir / "operational_closure.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def run(output_dir: pathlib.Path) -> dict[str, Any]:
    keys = ("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", "CGNK_MANAGED_PROJECT_ROOT")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["CGNK_LOCAL_STUDIO_CONVERSATION_ROOT"] = str(output_dir / "conversations")
    os.environ["CGNK_MANAGED_PROJECT_ROOT"] = str(output_dir / "managed")
    try:
        return _run_scoped(output_dir)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=pathlib.Path, required=True); args = parser.parse_args(argv)
    report = run(args.output_dir.resolve()); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__": raise SystemExit(main())
