from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import zipfile
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, contains_forbidden_terms, rel_list, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, contains_forbidden_terms, rel_list, write_json


def _expected_paths(project_dir: pathlib.Path, expected_files: list[str]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for item in expected_files:
        path = project_dir / item
        if path.exists():
            present.append(item)
        else:
            missing.append(item)
    return present, missing


def _python_import_smoke(project_dir: pathlib.Path) -> bool:
    py_files = [project_dir / "app" / "main.py"]
    services_dir = project_dir / "app" / "services"
    if services_dir.exists():
        py_files.extend(sorted(services_dir.glob("*.py")))
    py_files = [path for path in py_files if path.exists()]
    if not py_files:
        return False
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", *[str(path.resolve()) for path in py_files]],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


def _real_png(path: pathlib.Path) -> bool:
    try:
        data = path.read_bytes()
        return data.startswith(b"\x89PNG\r\n\x1a\n") and len(set(data[100:: max(1, len(data) // 2000)])) > 8
    except Exception:
        return False


def _verify(
    gate: str,
    *,
    stage: str,
    project_dir: pathlib.Path,
    out_dir: pathlib.Path,
    expected_files: list[str],
    shared_context: dict[str, Any] | None,
) -> bool:
    if gate == "goal_terms_present":
        frozen = out_dir / "frozen_requirement.json"
        text = frozen.read_text(encoding="utf-8", errors="replace").lower() if frozen.exists() else ""
        return all(term in text for term in ("document", "knowledge", "search", "reports", "tasks"))
    if gate == "no_forbidden_context":
        forbidden = list((shared_context or {}).get("forbidden_context_terms") or [])
        targets = [out_dir / "frozen_requirement.json", project_dir / "README.md"]
        parts: list[str] = []
        for path in targets:
            if not path.exists():
                continue
            if path.name == "frozen_requirement.json":
                try:
                    doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    doc = {}
                parts.append(
                    json.dumps(
                        {
                            "project_name": doc.get("project_name", ""),
                            "user_goal": doc.get("user_goal", ""),
                            "requirements": doc.get("requirements", []),
                            "allowed_context_terms": doc.get("allowed_context_terms", []),
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        text = "\n".join(parts)
        return not contains_forbidden_terms(text, forbidden)
    if gate == "entrypoint_exists":
        return any((project_dir / name).exists() for name in ("app/main.py", "main.py", "app.py", "index.html"))
    if gate == "dependency_file_exists":
        return any((project_dir / name).exists() for name in ("requirements.txt", "pyproject.toml", "package.json"))
    if gate == "startup_command_present":
        readme = project_dir / "README.md"
        return readme.exists() and "python" in readme.read_text(encoding="utf-8", errors="replace").lower()
    if gate == "service_files_exist":
        return not _expected_paths(project_dir, expected_files)[1]
    if gate == "python_import_smoke":
        return _python_import_smoke(project_dir)
    if gate == "view_count_ge_5":
        return len(list((project_dir / "app" / "templates").glob("*.html"))) >= 5
    if gate == "frontend_entrypoint_exists":
        return (project_dir / "index.html").exists() or (project_dir / "app" / "templates" / "dashboard.html").exists()
    if gate == "pytest_exit_code_0":
        execution = project_dir / "test_execution.json"
        if execution.exists():
            try:
                return json.loads(execution.read_text(encoding="utf-8")).get("verdict") == "PASS"
            except Exception:
                return False
        return False
    if gate == "screenshots_ge_3":
        return len([path for path in (project_dir / "screenshots").glob("*.png") if _real_png(path)]) >= 3
    if gate == "not_blank_or_placeholder":
        return bool([path for path in (project_dir / "screenshots").glob("*.png") if _real_png(path)])
    if gate == "bundle_integrity_pass":
        bundle = project_dir / "final_project_bundle.zip"
        manifest = project_dir / "delivery_manifest.json"
        if not bundle.exists() or not manifest.exists():
            return False
        try:
            with zipfile.ZipFile(bundle) as zf:
                names = {pathlib.PurePosixPath(name).name for name in zf.namelist()}
            return {"README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"}.issubset(names)
        except Exception:
            return False
    if gate == "public_delivery_gate_pass":
        gate_path = out_dir / "contract_checks" / "public_delivery_gate.json"
        if not gate_path.exists():
            return False
        try:
            return bool(json.loads(gate_path.read_text(encoding="utf-8")).get("delivery_allowed"))
        except Exception:
            return False
    return False


def run_checkpoint(
    *,
    stage: str,
    agent_id: str,
    project_dir: str | pathlib.Path,
    out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR,
    expected_files: list[str] | None = None,
    outputs: list[str] | None = None,
    verification: list[str] | None = None,
    next_allowed_stages: list[str] | None = None,
    shared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    out = pathlib.Path(out_dir)
    expected = list(expected_files or [])
    present, missing = _expected_paths(project, expected)
    checks: list[dict[str, Any]] = []
    failed: list[str] = []
    for gate in verification or []:
        ok = _verify(gate, stage=stage, project_dir=project, out_dir=out, expected_files=expected, shared_context=shared_context)
        checks.append({"name": gate, "verdict": "PASS" if ok else "FAIL"})
        if not ok:
            failed.append(gate)
    verdict = "PASS" if not missing and not failed else "FAIL"
    checkpoint = {
        "stage": stage,
        "agent_id": agent_id,
        "expected_files": expected,
        "present_files": present,
        "missing_files": missing,
        "outputs": list(outputs or []),
        "verification": checks,
        "failed_verification": failed,
        "verdict": verdict,
        "can_continue": verdict == "PASS",
        "next_allowed_stages": list(next_allowed_stages or []) if verdict == "PASS" else [],
    }
    write_json(out / "checkpoints" / f"{stage}.json", checkpoint)
    return checkpoint
