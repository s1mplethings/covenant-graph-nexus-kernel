#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import complexity_project_contract_check
import discovery_selection_lane
import requirement_acceptance_check
import planning_docs_materializer
import implementation_structure_materializer
import delivery_evidence_builder
import requirement_decision_lane


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"

BENCHMARK = "complexity_scale_local_video_workbench"
PROMPT = """我要一个本地优先的视频素材处理工作台，用来导入视频，自动抽取音频，切分片段，生成转写，占位分析高价值片段，选择候选片段，渲染导出短片，并提供 GUI 和 CLI 两种使用方式。

要求：
1. 最多只能问我一轮澄清问题。
2. 必须先完成 product_brief、technical_plan、interaction_design、acceptance_matrix，再进入实现。
3. 必须有单一主流程 orchestrator，流程至少包括 ingest_video、extract_audio、chunk_audio、transcribe_audio、analyze_segments、select_segments、render_clips、export_results。
4. GUI 和 CLI 必须共享同一套 stages.py / orchestrator.py，不能各写一套逻辑。
5. 必须生成阶段 artifact，包括 stage_plan.json、media_manifest.json、audio_chunk_manifest.json、transcript_merged.json、segment_analysis.json、selected_segments.json、clip_manifest.json、export_results.json。
6. 每个 artifact 必须包含 stage、count、input_path、output_path、status、created_at，并且下游 artifact 能回指上游 artifact。
7. 必须支持无真实模型/无 ffmpeg 时的 honest degraded mode，不能假装真实处理成功。
8. 最终必须输出 README、TEST_REPORT、DELIVERY_NOTES、至少一张运行截图、final_project_bundle.zip、run_dir。
9. 最终回复必须说明 internal_acceptance、user_acceptance、known_gaps，以及哪些要求没有达成。
10. 不允许生成单文件 demo，不允许只做静态页面，不允许只有 README 没有可运行代码。
"""

REQUIRED_ARTIFACTS = [
    "stage_plan.json",
    "media_manifest.json",
    "audio_chunk_manifest.json",
    "transcript_merged.json",
    "segment_analysis.json",
    "selected_segments.json",
    "clip_manifest.json",
    "export_results.json",
]

REQUIRED_ARTIFACT_FIELDS = {"stage", "count", "input_path", "output_path", "status", "created_at"}
PIPELINE_STAGES = [
    "ingest_video",
    "extract_audio",
    "chunk_audio",
    "transcribe_audio",
    "analyze_segments",
    "select_segments",
    "render_clips",
    "export_results",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_read(path: pathlib.Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def run_command(argv: list[str], *, cwd: pathlib.Path, timeout: int) -> dict[str, Any]:
    start = time.time()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {
            "argv": argv,
            "cwd": str(cwd),
            "started_at": started_at,
            "duration_seconds": round(time.time() - start, 3),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "cwd": str(cwd),
            "started_at": started_at,
            "duration_seconds": round(time.time() - start, 3),
            "returncode": None,
            "timeout": timeout,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else f"timeout after {timeout}s",
        }


def parse_json_result(command: dict[str, Any], result_path: pathlib.Path) -> dict[str, Any]:
    if result_path.exists():
        try:
            return json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    stdout = str(command.get("stdout") or "")
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stdout[start : end + 1])
        except Exception:
            return {}
    return {}


def iter_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in roots:
        if root.exists():
            if root.is_file():
                files.append(root)
            else:
                files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files), key=lambda p: str(p).lower())


def rel(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def find_by_name(files: list[pathlib.Path], name: str) -> list[pathlib.Path]:
    target = name.lower()
    return [path for path in files if path.name.lower() == target]


def find_python(files: list[pathlib.Path], name: str) -> list[pathlib.Path]:
    return [path for path in files if path.name.lower() == name.lower()]


def json_doc(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def status(pass_condition: bool, evidence: list[str], fail_reason: str) -> dict[str, Any]:
    if pass_condition:
        return {"status": "PASS", "evidence": evidence}
    return {"status": "FAIL", "evidence": evidence, "missing": fail_reason}


def file_status(files: list[pathlib.Path], filename: str, missing: str) -> dict[str, Any]:
    matches = find_by_name(files, filename)
    return status(bool(matches), [rel(path) for path in matches], missing)


def has_terms(path: pathlib.Path, terms: list[str]) -> bool:
    text = safe_read(path).lower()
    return any(term.lower() in text for term in terms)


def detect_entries(files: list[pathlib.Path]) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    cli_terms = ["argparse", "click", "typer", "__main__", "subparsers"]
    gui_terms = ["tkinter", "streamlit", "gradio", "pyqt", "pyside", "customtkinter", "flask", "fastapi"]
    cli = [
        path
        for path in files
        if path.suffix == ".py"
        and ("cli" in path.name.lower() or path.name.lower() in {"main.py", "__main__.py"})
        and has_terms(path, cli_terms)
    ]
    gui = [
        path
        for path in files
        if path.suffix == ".py"
        and ("gui" in path.name.lower() or "app" in path.name.lower() or "ui" in path.name.lower())
        and has_terms(path, gui_terms)
    ]
    return cli, gui


def artifact_has_required_shape(path: pathlib.Path) -> bool:
    doc = json_doc(path)
    if isinstance(doc, dict):
        return REQUIRED_ARTIFACT_FIELDS.issubset(doc.keys())
    if isinstance(doc, list) and doc and all(isinstance(item, dict) for item in doc):
        return all(REQUIRED_ARTIFACT_FIELDS.issubset(item.keys()) for item in doc[:10])
    return False


def artifact_references_previous(path: pathlib.Path, previous_name: str) -> bool:
    text = safe_read(path).lower()
    previous = previous_name.lower()
    trace_terms = ["upstream", "source", "parent", "depends", "input_artifact", "previous", "from_artifact", previous]
    return previous in text and any(term in text for term in trace_terms)


def evaluate(project_dir: pathlib.Path, run_dir: pathlib.Path, result: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    files = iter_files(project_dir, run_dir)
    checks: dict[str, dict[str, Any]] = {}
    layered = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)
    req_dir = run_dir / "requirement_decision"
    req_files = [req_dir / name for name in requirement_acceptance_check.REQUIREMENT_FILES]
    checks["requirement_decision_artifacts"] = status(
        all(path.exists() and path.stat().st_size > 0 for path in req_files),
        [rel(path) for path in req_files if path.exists()],
        "requirement_decision artifacts missing",
    )
    discovery_dir = run_dir / "discovery"
    discovery_check = complexity_project_contract_check.validate(run_dir=run_dir)
    discovery_blockers = list(discovery_check.get("blockers", []))
    discovery_files = [discovery_dir / name for name in complexity_project_contract_check.DISCOVERY_FILES]
    checks["discovery_artifacts"] = status(
        all(path.exists() and path.stat().st_size > 0 for path in discovery_files),
        [rel(path) for path in discovery_files if path.exists()],
        "discovery artifacts missing",
    )
    checks["complexity_project_contract"] = status(
        not any("contract_" in blocker or "candidate_" in blocker or "selected_" in blocker or "discovery_" in blocker for blocker in discovery_blockers),
        [rel(discovery_dir / "complexity_project_contract.json")] if (discovery_dir / "complexity_project_contract.json").exists() else [],
        "complexity_project_contract.json missing or structurally invalid",
    )
    checks["product_brief"] = file_status(files, "product_brief.md", "product_brief.md missing")
    checks["technical_plan"] = file_status(files, "technical_plan.md", "technical_plan.md missing")
    checks["interaction_design"] = file_status(files, "interaction_design.md", "interaction_design.md missing")
    checks["acceptance_matrix"] = status(
        bool(find_by_name(files, "acceptance_matrix.md")),
        [rel(path) for path in find_by_name(files, "acceptance_matrix.md")],
        "acceptance_matrix.md missing",
    )
    planning_gate = layered.get("checks", {}).get("planning_contract_gate", {}) if isinstance(layered.get("checks"), dict) else {}
    planning_missing = planning_gate.get("missing", []) if isinstance(planning_gate.get("missing"), list) else []
    checks["planning_contract_gate"] = status(
        not planning_missing,
        [str(item) for item in planning_gate.get("evidence", [])] if isinstance(planning_gate.get("evidence"), list) else [],
        ", ".join(str(item) for item in planning_missing) or "planning contract incomplete",
    )

    orchestrators = find_python(files, "orchestrator.py")
    stages = find_python(files, "stages.py")
    orchestrator_stage_text = "\n".join(safe_read(path) for path in orchestrators + stages).lower()
    checks["single_orchestrator"] = status(
        bool(orchestrators)
        and bool(stages)
        and all(stage in orchestrator_stage_text for stage in PIPELINE_STAGES),
        [rel(path) for path in orchestrators + stages],
        "orchestrator.py/stages.py missing or required stage names not all present",
    )

    cli_entries, gui_entries = detect_entries(files)
    checks["cli_entry"] = status(bool(cli_entries), [rel(path) for path in cli_entries], "CLI entrypoint missing")
    checks["gui_entry"] = status(bool(gui_entries), [rel(path) for path in gui_entries], "GUI entrypoint missing")
    shared_evidence = [rel(path) for path in cli_entries + gui_entries + orchestrators + stages]
    cli_shared = any(has_terms(path, ["orchestrator", "stages"]) for path in cli_entries)
    gui_shared = any(has_terms(path, ["orchestrator", "stages"]) for path in gui_entries)
    checks["shared_gui_cli_core"] = status(
        bool(orchestrators) and bool(stages) and cli_shared and gui_shared,
        shared_evidence,
        "GUI and CLI do not both reference shared orchestrator/stages",
    )

    artifact_paths: dict[str, list[pathlib.Path]] = {name: find_by_name(files, name) for name in REQUIRED_ARTIFACTS}
    existing_artifacts = [path for matches in artifact_paths.values() for path in matches]
    shaped = [path for path in existing_artifacts if artifact_has_required_shape(path)]
    checks["stage_artifacts"] = status(
        len(shaped) == len(REQUIRED_ARTIFACTS),
        [rel(path) for path in shaped],
        "required stage artifacts missing or missing required fields",
    )
    trace_ok: list[pathlib.Path] = []
    for prev, current in zip(REQUIRED_ARTIFACTS, REQUIRED_ARTIFACTS[1:]):
        for candidate in artifact_paths.get(current, []):
            if artifact_references_previous(candidate, prev):
                trace_ok.append(candidate)
                break
    checks["artifact_traceability"] = status(
        len(trace_ok) >= len(REQUIRED_ARTIFACTS) - 1,
        [rel(path) for path in trace_ok],
        "downstream artifacts do not trace to upstream artifacts",
    )

    checks["readme"] = file_status(files, "README.md", "README.md missing")
    checks["test_report"] = file_status(files, "TEST_REPORT.md", "TEST_REPORT.md missing")
    checks["delivery_notes"] = file_status(files, "DELIVERY_NOTES.md", "DELIVERY_NOTES.md missing")
    screenshots = [path for path in files if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and "screenshot" in str(path).lower()]
    checks["screenshot"] = status(bool(screenshots), [rel(path) for path in screenshots], "running screenshot missing")
    final_zips = [path for path in files if path.name == "final_project_bundle.zip"]
    checks["final_zip"] = status(bool(final_zips), [rel(path) for path in final_zips], "final_project_bundle.zip missing")
    manifests = find_by_name(files, "delivery_manifest.json")
    manifest_docs = [json_doc(path) for path in manifests]
    manifest_ok = any(
        isinstance(doc, dict)
        and isinstance(doc.get("files"), dict)
        and bool(doc.get("files", {}).get("final_project_bundle.zip", {}).get("sha256"))
        and int(doc.get("files", {}).get("final_project_bundle.zip", {}).get("size") or 0) > 0
        for doc in manifest_docs
    )
    checks["delivery_manifest"] = status(manifest_ok, [rel(path) for path in manifests], "delivery_manifest.json missing hash/size evidence")
    smoke_ok = any(
        isinstance(doc, dict)
        and isinstance(doc.get("evidence_status"), dict)
        and doc.get("evidence_status", {}).get("smoke_command", {}).get("status") == "PASS"
        for doc in manifest_docs
    )
    smoke_logs = find_by_name(files, "delivery_smoke_command.json") + find_by_name(files, "delivery_smoke_command.log")
    checks["smoke_command"] = status(smoke_ok, [rel(path) for path in smoke_logs], "smoke command missing or failed")
    degraded_evidence = [
        path
        for path in files
        if path.suffix.lower() in {".md", ".txt", ".json", ".py"}
        and has_terms(path, ["degraded", "降级", "honest", "ffmpeg", "model unavailable", "no model", "placeholder"])
    ]
    checks["honest_degraded_mode"] = status(
        bool(degraded_evidence),
        [rel(path) for path in degraded_evidence[:20]],
        "honest degraded mode not clearly documented",
    )

    test_reports = find_by_name(files, "TEST_REPORT.md")
    test_text = "\n".join(safe_read(path) for path in test_reports)
    real_test_evidence = bool(test_reports) and "NO TEST EXECUTED" not in test_text and any(
        term in test_text.lower() for term in ["pytest", "commands_run", "exit_code", "python -m", "test command"]
    )
    checks["real_test_results"] = status(
        real_test_evidence,
        [rel(path) for path in test_reports],
        "TEST_REPORT.md missing real command/result evidence",
    )
    run_dir_exists = run_dir.exists()
    checks["run_dir"] = status(run_dir_exists, [rel(run_dir)] if run_dir_exists else [], "run_dir missing")

    category_scores = {
        "discovery_selection": round(10 * sum(checks[key]["status"] == "PASS" for key in ["discovery_artifacts", "complexity_project_contract"]) / 2),
        "product_planning": round(12 * sum(checks[key]["status"] == "PASS" for key in ["product_brief", "technical_plan", "interaction_design", "acceptance_matrix", "planning_contract_gate"]) / 5),
        "technical_architecture": round(13 * sum(checks[key]["status"] == "PASS" for key in ["single_orchestrator", "cli_entry", "gui_entry"]) / 3),
        "single_main_pipeline": 13 if checks["single_orchestrator"]["status"] == "PASS" else 0,
        "artifact_contract": round(13 * sum(checks[key]["status"] == "PASS" for key in ["stage_artifacts", "artifact_traceability"]) / 2),
        "shared_core": 9 if checks["shared_gui_cli_core"]["status"] == "PASS" else 0,
        "runnability": round(10 * sum(
            [
                command.get("returncode") == 0,
                checks["real_test_results"]["status"] == "PASS",
            ]
        ) / 2),
        "delivery_completeness": round(10 * sum(checks[key]["status"] == "PASS" for key in ["readme", "test_report", "delivery_notes", "screenshot", "final_zip", "delivery_manifest", "smoke_command", "run_dir"]) / 8),
        "acceptance_honesty": round(10 * sum(
            [
                checks["honest_degraded_mode"]["status"] == "PASS",
                checks["real_test_results"]["status"] == "PASS",
            ]
        ) / 2),
    }
    overall_score = int(sum(category_scores.values()))

    critical_missing = [
        key
        for key in ["run_dir", "final_zip", "single_orchestrator", "shared_gui_cli_core"]
        if checks[key]["status"] != "PASS"
    ]
    final_verdict = str(result.get("final_verdict") or result.get("verdict") or "").upper()
    claimed_pass = (
        str(result.get("status", "")).lower() == "pass"
        or final_verdict in {"PASS", "PASS_FINAL", "DELIVER_WITH_WARNINGS"}
        or result.get("final_delivery_allowed") is True
    )
    fake_pass_risk = bool(claimed_pass and critical_missing)

    verdict = "PASS" if overall_score >= 85 else ("PARTIAL" if overall_score >= 65 else "FAIL")
    if critical_missing and verdict == "PASS":
        verdict = "PARTIAL"
    if fake_pass_risk:
        verdict = "FAIL" if overall_score < 65 else "PARTIAL"

    known_gaps = []
    for key, item in checks.items():
        if item["status"] != "PASS":
            known_gaps.append(f"{key}: {item.get('missing', 'missing evidence')}")
    if fake_pass_risk:
        known_gaps.append(f"fake_pass_risk: result claimed pass while missing {', '.join(critical_missing)}")

    root_causes = []
    if checks["discovery_artifacts"]["status"] != "PASS" or checks["complexity_project_contract"]["status"] != "PASS":
        root_causes.append("discovery selection lane did not produce complete upstream contract evidence")
    if checks["planning_contract_gate"]["status"] != "PASS":
        root_causes.append("planning contract gate failed because required product planning docs are missing")
    if checks["single_orchestrator"]["status"] != "PASS":
        root_causes.append("generation did not preserve the requested single orchestrator/stages contract")
    if checks["stage_artifacts"]["status"] != "PASS":
        root_causes.append("artifact contract is not enforced strongly enough during generation/finalization")
    if checks["final_zip"]["status"] != "PASS" or checks["screenshot"]["status"] != "PASS" or checks["delivery_manifest"]["status"] != "PASS" or checks["smoke_command"]["status"] != "PASS":
        root_causes.append("delivery gate or post-build finalization did not produce all requested delivery evidence")
    if command.get("returncode") != 0:
        root_causes.append("CGKN local pipeline command failed before complete delivery")

    recommended = [
        "Add a provider-output validator for required project planning files before materialization is considered acceptable.",
        "Add a generated-project contract check for orchestrator.py/stages.py and GUI/CLI shared imports.",
        "Make stage artifact schema and upstream traceability part of post-build finalization or product acceptance.",
        "Fail public/final promotion when requested screenshot or final_project_bundle.zip is absent.",
        "Require TEST_REPORT.md to include real commands and exit codes, not generated claims.",
    ]

    return {
        "benchmark": BENCHMARK,
        "overall_score": overall_score,
        "requirement_decision_status": layered.get("requirement_decision_status"),
        "product_contract_status": layered.get("product_contract_status"),
        "implementation_status": layered.get("implementation_status"),
        "delivery_status": layered.get("delivery_status"),
        "layered_overall_status": layered.get("overall_status"),
        "category_scores": category_scores,
        "verdict": verdict,
        "checks": {key: {"status": value["status"], "evidence": value.get("evidence", [])} | ({"missing": value["missing"]} if "missing" in value else {}) for key, value in checks.items()},
        "known_gaps": known_gaps,
        "suspected_root_causes": root_causes,
        "recommended_fixes": recommended,
        "fake_pass_risk": fake_pass_risk,
        "discovery_contract_check": discovery_check,
        "critical_missing": critical_missing,
        "layered_acceptance": layered,
    }


def inventory_text(project_dir: pathlib.Path, run_dir: pathlib.Path) -> str:
    lines = ["# Complexity Scale File Inventory", ""]
    for root in [project_dir, run_dir, ARTIFACTS_DIR]:
        lines.append(f"## {root}")
        if not root.exists():
            lines.append("MISSING")
            lines.append("")
            continue
        for path in iter_files(root):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            lines.append(f"{rel(path)}\t{size}")
        lines.append("")
    return "\n".join(lines)


def command_log_text(commands: list[dict[str, Any]]) -> str:
    lines = ["# Complexity Scale Command Log", ""]
    for index, command in enumerate(commands, start=1):
        lines.append(f"## Command {index}")
        lines.append(f"cwd: {command.get('cwd')}")
        lines.append(f"argv: {' '.join(command.get('argv', []))}")
        lines.append(f"started_at: {command.get('started_at')}")
        lines.append(f"duration_seconds: {command.get('duration_seconds')}")
        lines.append(f"returncode: {command.get('returncode')}")
        if command.get("timeout"):
            lines.append(f"timeout: {command.get('timeout')}")
        lines.append("")
        lines.append("### stdout")
        lines.append("```text")
        lines.append(str(command.get("stdout") or "")[-8000:])
        lines.append("```")
        lines.append("")
        lines.append("### stderr")
        lines.append("```text")
        lines.append(str(command.get("stderr") or "")[-8000:])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def acceptance_report_text(acceptance: dict[str, Any], project_dir: pathlib.Path, run_dir: pathlib.Path, final_zip: pathlib.Path | None, screenshot: pathlib.Path | None) -> str:
    lines = [
        "# Complexity Scale Acceptance Report",
        "",
        f"- Benchmark: `{BENCHMARK}`",
        f"- Project dir: `{project_dir}`",
        f"- Run dir: `{run_dir}`",
        f"- Overall score: `{acceptance['overall_score']}`",
        f"- Verdict: `{acceptance['verdict']}`",
        f"- final_project_bundle.zip: `{final_zip if final_zip else 'missing'}`",
        f"- Screenshot: `{screenshot if screenshot else 'missing'}`",
        f"- fake_pass_risk: `{acceptance.get('fake_pass_risk')}`",
        "",
        "## Checks",
        "",
    ]
    for key, item in acceptance["checks"].items():
        evidence = ", ".join(f"`{value}`" for value in item.get("evidence", [])) or "none"
        missing = f" Missing: {item.get('missing')}." if item.get("missing") else ""
        lines.append(f"- {key}: **{item['status']}**. Evidence: {evidence}.{missing}")
    lines.extend(["", "## Known Gaps", ""])
    gaps = acceptance.get("known_gaps", [])
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("- none")
    lines.extend(["", "## Suspected Root Causes", ""])
    causes = acceptance.get("suspected_root_causes", [])
    if causes:
        lines.extend(f"- {cause}" for cause in causes)
    else:
        lines.append("- none")
    lines.extend(["", "## Recommended Fixes", ""])
    lines.extend(f"- {fix}" for fix in acceptance.get("recommended_fixes", []))
    lines.append("")
    return "\n".join(lines)


def gap_analysis_text(acceptance: dict[str, Any]) -> str:
    checks = acceptance["checks"]
    return "\n".join(
        [
            "# Complexity Scale Gap Analysis",
            "",
            f"1. CGKN 当前是否已经能生成 同等复杂度复杂项目？",
            f"   - Verdict: {acceptance['verdict']}; score: {acceptance['overall_score']}. 按本次证据判定。",
            "2. 如果不能，主要差距在哪里？",
            f"   - {('; '.join(acceptance.get('known_gaps', [])[:8]) or 'no major gap recorded')}",
            "3. 是产品计划不足，还是实现主线不足？",
            f"   - 产品计划检查：product_brief={checks['product_brief']['status']}, technical_plan={checks['technical_plan']['status']}, interaction_design={checks['interaction_design']['status']}, acceptance_matrix={checks['acceptance_matrix']['status']}。实现主线检查：single_orchestrator={checks['single_orchestrator']['status']}。",
            f"   - Planning Contract Gate: {checks['planning_contract_gate']['status']}；missing={checks['planning_contract_gate'].get('missing', 'none')}；evidence={checks['planning_contract_gate'].get('evidence', [])}。",
            "4. 是 artifact contract 不足，还是 delivery gate 不足？",
            f"   - artifact_contract: stage_artifacts={checks['stage_artifacts']['status']}, traceability={checks['artifact_traceability']['status']}; delivery: zip={checks['final_zip']['status']}, screenshot={checks['screenshot']['status']}, manifest={checks['delivery_manifest']['status']}, smoke={checks['smoke_command']['status']}。",
            "5. 是 prompt 约束不足，还是代码生成框架不足？",
            "   - 本轮只测试，不修复。若 prompt 已明确要求但输出缺失，优先视为生成框架/验收 gate 未强制。",
            "6. 有没有出现小 demo 退化？",
            f"   - 若 orchestrator/stages 或 stage artifacts 缺失，则存在小 demo 退化风险：{checks['single_orchestrator']['status'] != 'PASS' or checks['stage_artifacts']['status'] != 'PASS'}。",
            "7. 有没有出现假 PASS？",
            f"   - fake_pass_risk={acceptance.get('fake_pass_risk')}。",
            "8. 有没有出现 GUI/CLI 分裂？",
            f"   - shared_gui_cli_core={checks['shared_gui_cli_core']['status']}。",
            "9. 有没有出现阶段证据缺失？",
            f"   - stage_artifacts={checks['stage_artifacts']['status']}; artifact_traceability={checks['artifact_traceability']['status']}。",
            "10. 下一步最小修复应该改哪里？",
            "   - 优先加强 provider 输出验收、post_build_finalize 证据收集、product_acceptance 的项目结构/阶段 artifact 审查，而不是新建第二条生成路线。",
            "",
        ]
    )


def repair_plan_text() -> str:
    return """# Complexity Scale Repair Plan

## A. 必须立即修的 gate 问题

- 目标文件: `scripts/product_acceptance.py`
  - 修改点: 增加 同等复杂度结构检查，包括 planning 文件、orchestrator/stages、GUI/CLI shared imports、required artifact schema、traceability。
  - 为什么要改: 生成物缺关键结构时不能被判为可交付。
  - 对应测试: `tests/test_complexity_scale_benchmark.py` 或新增 focused acceptance tests。
  - 验收标准: 缺任一硬门槛时 verdict 不能 PASS。

- 目标文件: `scripts/post_build_finalize.py`
  - 修改点: requested screenshot、TEST_REPORT real command evidence、DELIVERY_NOTES、known gaps 的强制审查和记录。
  - 为什么要改: 交付证据缺失不能被包装成完成。
  - 对应测试: post-build finalization tests。
  - 验收标准: 缺截图或真实测试日志时 final promotion 被阻止或降级。

- 目标文件: `scripts/final_promotion.py` / `scripts/final_delivery_truth.py`
  - 修改点: 对用户明确要求的 `final_project_bundle.zip`、截图、run_dir、artifact contract 增加硬阻断。
  - 为什么要改: 防止 fake PASS 和候选包冒充最终交付。
  - 对应测试: final promotion/delivery truth tests。
  - 验收标准: 缺 final zip 或截图时不能 PASS。

## B. 应该加强的 product/team planning 问题

- 目标文件: `scripts/provider_generation.py`
  - 修改点: 将用户要求的 planning artifacts 和单主流程 contract 明确注入 provider prompt/checklist。
  - 为什么要改: 降低生成时退化为小 demo 的概率。
  - 对应测试: provider prompt construction regression。
  - 验收标准: prompt 中保留 product_brief、technical_plan、interaction_design、acceptance_matrix、orchestrator/stages、artifact schema。

- 目标文件: `scripts/run_local_pipeline_impl.py`
  - 修改点: 在 provider 生成后增加 bounded semantic review，针对 GUI/CLI shared core 和 stage artifact contract 给出 rework。
  - 为什么要改: 让错误在 candidate 阶段暴露，而不是等最终交付。
  - 对应测试: generated candidate semantic review tests。
  - 验收标准: 缺 shared core 或 required artifacts 时进入 rework/partial，而非 pass。

## C. 可以后置的质量提升问题

- 目标文件: `docs/04_acceptance_and_evidence.md`
  - 修改点: 增加复杂本地工作台项目的证据示例。
  - 为什么要改: 让后续 agent 更容易按证据而非声明验收。
  - 对应测试: docs contract guard if applicable。
  - 验收标准: 文档包含可执行证据清单，不引入新正式生成路线。

- 目标文件: `scripts/run_complexity_scale_workbench_benchmark.py`
  - 修改点: 后续可把人工 heuristic 提炼为更细的 structured validators。
  - 为什么要改: 提升 benchmark 诊断精度。
  - 对应测试: runner unit tests with synthetic project fixtures。
  - 验收标准: PASS/FAIL 均有路径证据且不会生成目标项目代码。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=f"complexity-scale-workbench-{utc_stamp()}")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-live", action="store_true", help="Write reports without invoking CGKN generation.")
    parser.add_argument("--audit-project-dir", default="")
    parser.add_argument("--audit-run-dir", default="")
    parser.add_argument("--audit-result", default="")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id
    run_dir = ROOT / "examples" / "runtime_runs" / run_id
    project_dir = ROOT / "generated" / run_id
    result_path = ARTIFACTS_DIR / "complexity_scale_pipeline_result.json"

    commands: list[dict[str, Any]] = []
    result: dict[str, Any] = {"status": "skipped", "reason": "no_live"}
    if args.no_live:
        if args.audit_project_dir:
            project_dir = pathlib.Path(args.audit_project_dir)
        if args.audit_run_dir:
            run_dir = pathlib.Path(args.audit_run_dir)
        requirement_result = requirement_decision_lane.run_requirement_decision(PROMPT, run_dir)
        discovery_result = discovery_selection_lane.run_discovery_selection(PROMPT, run_dir / "discovery")
        planning_result = planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
        implementation_structure_result = implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
        delivery_evidence_result = delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)
        audit_result = pathlib.Path(args.audit_result) if args.audit_result else None
        if audit_result and audit_result.exists():
            try:
                result = json.loads(audit_result.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                result = {"status": "skipped", "reason": "audit_result_unreadable"}
        result.setdefault("discovery_selection", discovery_result)
        result.setdefault("requirement_decision", requirement_result)
        result.setdefault("selected_requirement", requirement_result.get("selected_requirement", {}))
        result.setdefault("acceptance_contract", requirement_result.get("acceptance_contract", {}))
        result.setdefault("selected_project_direction", discovery_result.get("selected_project_direction", {}))
        result.setdefault("complexity_project_contract", discovery_result.get("complexity_project_contract", {}))
        result.setdefault("planning_materialization", planning_result)
        result.setdefault("implementation_structure_materialization", implementation_structure_result)
        result.setdefault("delivery_evidence", delivery_evidence_result)
        previous_returncode = None
        commands.append({"returncode": previous_returncode, "argv": ["audit-only"], "cwd": str(ROOT), "stdout": "", "stderr": ""})
    else:
        argv = [
            sys.executable,
            str(ROOT / "scripts" / "run_local_pipeline.py"),
            "--goal",
            PROMPT,
            "--out-dir",
            str(project_dir),
            "--run-dir",
            str(run_dir),
            "--result",
            str(result_path),
            "--allow-network",
            "--allow-provider",
            "--use-api",
            "--video",
            "--timeout",
            str(args.timeout),
            "--json",
        ]
        command = run_command(argv, cwd=ROOT, timeout=args.timeout + 120)
        commands.append(command)
        result = parse_json_result(command, result_path)
        for key in ("project_dir", "candidate_project_dir"):
            value = result.get(key)
            if value:
                project_dir = pathlib.Path(str(value))
                break
        value = result.get("run_dir")
        if value:
            run_dir = pathlib.Path(str(value))

    files = iter_files(project_dir, run_dir)
    final_zip = next((path for path in files if path.name == "final_project_bundle.zip"), None)
    screenshot = next((path for path in files if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and "screenshot" in str(path).lower()), None)
    acceptance = evaluate(project_dir, run_dir, result, commands[0] if commands else {"returncode": None})

    run_summary = {
        "benchmark": BENCHMARK,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "generated_project_path": str(project_dir),
        "artifacts_path": str(ARTIFACTS_DIR),
        "reports_path": str(ARTIFACTS_DIR),
        "screenshots_path": str(screenshot.parent if screenshot else ""),
        "final_bundle_path": str(final_zip or ""),
        "logs_path": str(ARTIFACTS_DIR / "complexity_scale_command_log.txt"),
        "command_returncode": commands[0].get("returncode") if commands else None,
        "pipeline_result": result,
        "discovery_dir": str(run_dir / "discovery"),
        "complexity_project_contract": str(run_dir / "discovery" / "complexity_project_contract.json"),
        "discovery_contract_check": acceptance.get("discovery_contract_check", {}),
        "score": acceptance["overall_score"],
        "verdict": acceptance["verdict"],
    }

    write_json(ARTIFACTS_DIR / "complexity_scale_acceptance.json", acceptance)
    write_text(ARTIFACTS_DIR / "complexity_scale_acceptance_report.md", acceptance_report_text(acceptance, project_dir, run_dir, final_zip, screenshot))
    command_log_path = ARTIFACTS_DIR / "complexity_scale_command_log.txt"
    if not args.no_live or not command_log_path.exists():
        write_text(command_log_path, command_log_text(commands))
    write_text(ARTIFACTS_DIR / "complexity_scale_file_inventory.txt", inventory_text(project_dir, run_dir))
    write_json(ARTIFACTS_DIR / "complexity_scale_run_summary.json", run_summary)
    write_text(
        ARTIFACTS_DIR / "complexity_scale_run_summary.md",
        "\n".join(
            [
                "# Complexity Scale Run Summary",
                "",
                f"- run_id: `{run_id}`",
                f"- run_dir: `{run_dir}`",
                f"- generated project path: `{project_dir}`",
                f"- artifacts path: `{ARTIFACTS_DIR}`",
                f"- reports path: `{ARTIFACTS_DIR}`",
                f"- screenshots path: `{screenshot.parent if screenshot else 'missing'}`",
                f"- final bundle path: `{final_zip if final_zip else 'missing'}`",
                f"- logs path: `{ARTIFACTS_DIR / 'complexity_scale_command_log.txt'}`",
                f"- score: `{acceptance['overall_score']}`",
                f"- verdict: `{acceptance['verdict']}`",
                "",
            ]
        ),
    )
    write_text(ARTIFACTS_DIR / "complexity_scale_gap_analysis.md", gap_analysis_text(acceptance))
    write_text(ARTIFACTS_DIR / "complexity_scale_repair_plan.md", repair_plan_text())

    print(json.dumps(run_summary, ensure_ascii=False, indent=2))
    return 0 if acceptance["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
