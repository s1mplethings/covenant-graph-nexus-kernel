#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
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


def package_project(
    project_dir: str | pathlib.Path,
    *,
    output_dir: str | pathlib.Path | None = None,
    startup_command: str = "",
    run_log_path: str | pathlib.Path | None = None,
    screenshot_path: str | pathlib.Path | None = None,
    known_limits: list[str] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    if not project.exists() or not project.is_dir():
        raise RuntimeError(f"project_dir does not exist: {project}")
    target_dir = pathlib.Path(output_dir).resolve() if output_dir else project
    target_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    startup = startup_command.strip() or _infer_startup_command(project)
    readme = _ensure_readme(project, startup)
    run_log = pathlib.Path(run_log_path).resolve() if run_log_path else target_dir / "packager_run_log.txt"
    if not run_log.exists():
        run_log.write_text(f"{now()} packaged project\n", encoding="utf-8")
    if screenshot_path:
        screenshot = pathlib.Path(screenshot_path)
        if not screenshot.exists():
            warnings.append(f"效果预览文件未找到: {screenshot}")
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
    }
    manifest_path = target_dir / "delivery_manifest.json"
    manifest["manifest_path"] = str(manifest_path.resolve())
    _write_json(manifest_path, manifest)
    return manifest
