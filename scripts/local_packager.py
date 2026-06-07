#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import time
import zipfile
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _infer_startup_command(project_dir: pathlib.Path) -> str:
    if (project_dir / "package.json").exists():
        return "npm install && npm start"
    if (project_dir / "app.py").exists():
        return "python app.py"
    if (project_dir / "main.py").exists():
        return "python main.py"
    if (project_dir / "index.html").exists():
        return "open index.html"
    return ""


def _ensure_readme(project_dir: pathlib.Path, startup_command: str) -> pathlib.Path:
    readme = project_dir / "README.md"
    if readme.exists():
        return readme
    lines = ["# Generated Project", ""]
    if startup_command:
        lines.extend(["## Run", "", f"```bash\n{startup_command}\n```", ""])
    lines.append("This project was packaged by the local CGNK packager.")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme


def _read_text(path: pathlib.Path, limit: int = 50000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _has_nonempty_commands_run(text: str) -> bool:
    lowered = text.lower()
    if "commands_run" not in lowered:
        return False
    match = re.search(r"commands_run\s*:?(.*?)(?:\n\s*(?:results|failures|repairs|remaining_warnings)\s*:|\Z)", text, flags=re.I | re.S)
    section = match.group(1) if match else ""
    cleaned = re.sub(r"[\s`\-:\[\],]+", "", section).lower()
    return bool(cleaned) and cleaned not in {"none", "null", "empty", "无", "未执行"}


def _is_placeholder_preview(path: pathlib.Path) -> bool:
    lowered = path.name.lower()
    if any(token in lowered for token in ("placeholder", "mock", "fallback", "delivery_summary", "summary_preview")):
        return True
    if path.suffix.lower() in {".html", ".txt", ".md", ".svg"}:
        text = _read_text(path, limit=8000).lower()
        return any(token in text for token in ("placeholder", "mock screenshot", "占位", "示例预览", "自动生成的交付摘要图"))
    return False


def _preview_candidates(project: pathlib.Path) -> list[pathlib.Path]:
    preview_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".html"}
    if not project.exists():
        return []
    return [path for path in project.rglob("*") if path.is_file() and path.suffix.lower() in preview_suffixes]


def _sample_input_found(project: pathlib.Path) -> bool:
    tokens = ("sample", "samples", "fixture", "fixtures", "test_data", "input", "inputs", "demo")
    suffixes = {".dem", ".demo", ".json", ".csv", ".txt", ".mp4", ".avi", ".mov", ".png", ".jpg", ".jpeg"}
    if not project.exists():
        return False
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(project)).replace("\\", "/").lower()
        if any(token in rel for token in tokens) and path.suffix.lower() in suffixes:
            if path.name not in {"delivery_manifest.json"}:
                return True
    return False


def _looks_like_demo_data_project(project: pathlib.Path, known_limits: list[str] | None) -> bool:
    haystack = "\n".join(str(item) for item in known_limits or [])
    for name in ("README.md", "PRODUCT_PLAN.md", "OUTPUT_CONTRACT.md", "TECHNICAL_PLAN.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        haystack += "\n" + _read_text(project / name, limit=12000)
    lowered = haystack.lower()
    return any(token in lowered for token in ("csgo", "csgo2", "cs2", "demo", "数据分析", "data analysis", "鉴挂", "反作弊", "外部文件", "样例输入"))


def collect_quality_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    paths = {
        "readme": project / "README.md",
        "test_report": project / "TEST_REPORT.md",
        "delivery_notes": project / "DELIVERY_NOTES.md",
        "product_plan": project / "PRODUCT_PLAN.md",
        "output_contract": project / "OUTPUT_CONTRACT.md",
        "technical_plan": project / "TECHNICAL_PLAN.md",
        "build_plan": project / "BUILD_PLAN.md",
    }
    test_report_text = _read_text(paths["test_report"])
    preview_candidates = _preview_candidates(project)
    real_preview_candidates = [path for path in preview_candidates if not _is_placeholder_preview(path)]
    placeholder_preview_candidates = [path for path in preview_candidates if _is_placeholder_preview(path)]
    return {
        "readme_found": paths["readme"].exists(),
        "test_report_found": paths["test_report"].exists(),
        "test_report_has_commands": _has_nonempty_commands_run(test_report_text),
        "test_report_has_no_test_executed": "NO TEST EXECUTED" in test_report_text.upper(),
        "test_report_mentions_sample_input": bool(re.search(r"\b(sample|fixture|demo|input|test_data)\b|样例|示例|真实输入|测试数据", test_report_text, flags=re.I)),
        "delivery_notes_found": paths["delivery_notes"].exists(),
        "product_plan_found": paths["product_plan"].exists(),
        "output_contract_found": paths["output_contract"].exists(),
        "technical_plan_found": paths["technical_plan"].exists(),
        "build_plan_found": paths["build_plan"].exists(),
        "preview_evidence_found": bool(real_preview_candidates),
        "preview_placeholder_found": bool(placeholder_preview_candidates),
        "sample_input_found": _sample_input_found(project),
        "test_report_path": str(paths["test_report"].resolve()) if paths["test_report"].exists() else "",
        "delivery_notes_path": str(paths["delivery_notes"].resolve()) if paths["delivery_notes"].exists() else "",
    }


def collect_user_review_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    evidence_review = project / "EVIDENCE_REVIEW.md"
    test_report = project / "TEST_REPORT.md"
    media_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
    preview_suffixes = media_suffixes | {".html", ".csv", ".json"}

    def rel(path: pathlib.Path) -> str:
        try:
            return str(path.resolve().relative_to(project)).replace("\\", "/")
        except ValueError:
            return str(path)

    def files(patterns: tuple[str, ...], suffixes: set[str] | None = None) -> list[str]:
        out: list[str] = []
        for pattern in patterns:
            for path in sorted(project.glob(pattern)):
                if path.is_file() and (suffixes is None or path.suffix.lower() in suffixes):
                    value = rel(path)
                    if value not in out:
                        out.append(value)
        return out[:80]

    return {
        "evidence_review_found": evidence_review.exists(),
        "test_report_found": test_report.exists(),
        "test_code_files": files(("tests/**/*.py", "test_*.py", "*_test.py")),
        "sample_inputs": files(("samples/**/*", "test_data/**/*", "demo/**/*")),
        "screenshots": files(("screenshots/**/*", "artifacts/**/*", "preview/**/*", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp"), {".png", ".jpg", ".jpeg", ".webp"}),
        "videos": files(("artifacts/**/*", "preview/**/*", "**/*.mp4", "**/*.webm", "**/*.gif"), {".mp4", ".webm", ".gif"}),
        "preview_files": files(("artifacts/**/*", "preview/**/*", "**/*.html", "**/*.csv", "**/*.json", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif", "**/*.mp4", "**/*.webm"), preview_suffixes),
    }


def package_project(
    project_dir: str | pathlib.Path,
    *,
    output_dir: str | pathlib.Path | None = None,
    startup_command: str = "",
    run_log_path: str | pathlib.Path | None = None,
    screenshot_path: str | pathlib.Path | None = None,
    known_limits: list[str] | None = None,
    user_review_required: bool = False,
    user_review_completed: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists() or not project.is_dir():
        raise RuntimeError(f"project_dir does not exist: {project}")
    target_dir = pathlib.Path(output_dir).resolve() if output_dir else project
    target_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    startup = startup_command.strip() or _infer_startup_command(project)
    readme_existed = (project / "README.md").exists()
    readme = _ensure_readme(project, startup)
    quality_evidence = collect_quality_evidence(project)
    user_review_evidence = collect_user_review_evidence(project)
    user_review_evidence["user_review_required"] = bool(user_review_required)
    user_review_evidence["user_review_completed"] = bool(user_review_completed)
    if not readme_existed:
        warnings.append("README.md 由 packager 自动补齐，内容可能不完整")
    if not quality_evidence["test_report_found"]:
        warnings.append("未找到 TEST_REPORT.md，本轮测试证据不足")
    elif quality_evidence["test_report_has_no_test_executed"]:
        warnings.append("测试报告存在，但未执行真实测试命令")
    if not quality_evidence["delivery_notes_found"]:
        warnings.append("未找到 DELIVERY_NOTES.md，本轮交付复核不足")
    if quality_evidence.get("preview_placeholder_found"):
        warnings.append("预览为占位示例，不算真实运行证据")
    if not quality_evidence["preview_evidence_found"]:
        warnings.append("未找到预览证据")
    if _looks_like_demo_data_project(project, known_limits) and not quality_evidence.get("sample_input_found") and not quality_evidence.get("test_report_mentions_sample_input"):
        warnings.append("缺少真实 demo 或样例输入，未完成真实数据验证")
    if user_review_required and not user_review_completed:
        warnings.append("用户尚未确认中间测试/预览证据")
    run_log = pathlib.Path(run_log_path).resolve() if run_log_path else target_dir / "packager_run_log.txt"
    if not run_log.exists():
        run_log.write_text(f"{now()} packaged project\n", encoding="utf-8")
    if screenshot_path:
        screenshot = pathlib.Path(screenshot_path)
        if not screenshot.exists():
            warnings.append(f"效果预览文件未找到: {screenshot}")
        elif _is_placeholder_preview(screenshot):
            warnings.append("预览为占位示例，不算真实运行证据")
    else:
        warnings.append("本轮没有生成效果预览图，已先交付可运行项目文件")

    package_path = target_dir / "final_project_bundle.zip"
    tmp_package = target_dir / f"final_project_bundle.{int(time.time() * 1000)}.tmp"
    with zipfile.ZipFile(tmp_package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() in {package_path.resolve(), tmp_package.resolve()}:
                continue
            if path.name == "delivery_manifest.json" and path.parent.resolve() == target_dir.resolve():
                continue
            zf.write(path, path.relative_to(project))
    tmp_package.replace(package_path)

    combined_limits = list(known_limits or []) + warnings
    manifest = {
        "kind": "CGNKDeliveryManifest",
        "created_at": now(),
        "status": "ready_with_warnings" if combined_limits else "ready",
        "project_dir": str(project),
        "package_path": str(package_path.resolve()),
        "readme_path": str(readme.resolve()),
        "startup_command": startup,
        "run_log_path": str(run_log.resolve()),
        "known_limits": combined_limits,
        "quality_evidence": quality_evidence,
        "user_review_evidence": user_review_evidence,
    }
    manifest_path = target_dir / "delivery_manifest.json"
    manifest["manifest_path"] = str(manifest_path.resolve())
    _write_json(manifest_path, manifest)
    return manifest
