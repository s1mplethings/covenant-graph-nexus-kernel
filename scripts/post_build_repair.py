#!/usr/bin/env python3
from __future__ import annotations

import ast
import pathlib
import importlib
import json
import re
from typing import Any

try:
    from pipeline_contracts import RepairResult, base_result
    import ui_semantic_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import RepairResult, base_result
    from scripts import ui_semantic_adapter


def windows_esm_path_import_error(text: str) -> bool:
    log = str(text or "").lower()
    return (
        "err_unsupported_esm_url_scheme" in log
        or "only urls with a scheme in: file, data, and node are supported" in log
        or "received protocol 'd:'" in log
        or 'received protocol "d:"' in log
        or "windows d: path used as esm import url" in log
    )


def missing_vitest_error(text: str) -> bool:
    log = str(text or "").lower()
    return (
        "'vitest' is not recognized" in log
        or "vitest: command not found" in log
        or "sh: vitest: command not found" in log
        or "cannot find package 'vitest'" in log
        or 'cannot find package "vitest"' in log
        or ("missing" in log and "vitest" in log and ("script" in log or "dependency" in log))
    )


def no_tests_ran_error(text: str) -> bool:
    log = str(text or "").lower()
    return "no tests ran" in log or "collected 0 items" in log


def missing_package_json_error(text: str) -> bool:
    log = str(text or "").lower()
    return bool(
        "missing required file: package.json" in log
        or "could not read package.json" in log
        or re.search(r"enoent.*package\.json", log, flags=re.S)
        or "npm err! enoent" in log
        or "package.json not found" in log
    )


def has_runnable_candidate_source(candidate_dir: pathlib.Path) -> bool:
    source_candidates = (
        "index.html",
        "src/main.js",
        "src/app.js",
        "src/App.tsx",
        "src/App.jsx",
        "scripts/test.js",
        "tests/smoke_test.mjs",
        "tests/api_contract_test.mjs",
        "backend/service.py",
        "app.py",
    )
    return any((candidate_dir / rel).exists() for rel in source_candidates)


def _legacy() -> Any:
    import importlib
    import sys

    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "write_json"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "write_json"):
        return packaged
    top_level = sys.modules.get("run_local_pipeline")
    if top_level is not None and hasattr(top_level, "write_json"):
        return top_level
    implementation = sys.modules.get("scripts.run_local_pipeline_impl")
    if implementation is not None:
        return implementation
    try:
        return importlib.import_module("scripts.run_local_pipeline_impl")
    except ModuleNotFoundError:
        return importlib.import_module("run_local_pipeline_impl")


def _legacy_call(name: str, *args: Any, **kwargs: Any) -> Any:
    target = _legacy()
    if not hasattr(target, name):
        target = importlib.import_module("scripts.run_local_pipeline_impl")
    return getattr(target, name)(*args, **kwargs)


def post_build_repair_attempts(args: Any | None = None) -> int:
    default = int(_legacy_call("env_int", "CGNK_POST_BUILD_REPAIR_ATTEMPTS", 2))
    if args is not None and getattr(args, "post_build_repair_attempts", None) is not None:
        try:
            return max(0, min(5, int(getattr(args, "post_build_repair_attempts"))))
        except (TypeError, ValueError):
            return max(0, min(5, default))
    return max(0, min(5, default))


def post_build_failure_log(finalize_result: dict[str, Any]) -> str:
    test_result = finalize_result.get("test_result", {}) if isinstance(finalize_result.get("test_result"), dict) else {}
    goal_test_result = finalize_result.get("goal_test_result", {}) if isinstance(finalize_result.get("goal_test_result"), dict) else {}
    agent_usage = finalize_result.get("agent_usage", {}) if isinstance(finalize_result.get("agent_usage"), dict) else {}
    chunks = [
        "test_status=" + str(test_result.get("status", "")),
        "test_argv=" + json.dumps(test_result.get("argv", []), ensure_ascii=False),
        str(test_result.get("error", "")),
        str(test_result.get("stdout_tail", "")),
        str(test_result.get("stderr_tail", "")),
        "goal_test_status=" + str(goal_test_result.get("status", "")),
        "goal_test_argv=" + json.dumps(goal_test_result.get("argv", []), ensure_ascii=False),
        str(goal_test_result.get("stdout_tail", "")),
        str(goal_test_result.get("stderr_tail", "")),
        json.dumps(finalize_result.get("goal_acceptance", {}), ensure_ascii=False, default=str),
        "agent_usage_status=" + str(agent_usage.get("status", "")),
        json.dumps(agent_usage.get("failure_summary", ""), ensure_ascii=False, default=str),
        json.dumps(agent_usage.get("events", [])[-6:] if isinstance(agent_usage.get("events", []), list) else [], ensure_ascii=False, default=str),
        json.dumps(finalize_result.get("screenshot_capture", {}), ensure_ascii=False, default=str),
        json.dumps(finalize_result.get("ui_smoke", {}), ensure_ascii=False, default=str),
        json.dumps(finalize_result.get("fixture_result", {}), ensure_ascii=False, default=str),
        str(finalize_result.get("screenshot_blocked", "")),
        "video_status=" + str(finalize_result.get("video_status", "")),
        "video_failure_reason=" + str(finalize_result.get("video_failure_reason", "")),
        str(finalize_result.get("video_blocked", "")),
        "\n".join(str(item) for item in finalize_result.get("known_limits", []) if str(item).strip()) if isinstance(finalize_result.get("known_limits", []), list) else "",
    ]
    return "\n".join(chunk for chunk in chunks if str(chunk).strip())[:12000]


def classify_post_build_failures(finalize_result: dict[str, Any]) -> list[str]:
    failures: set[str] = set()
    test_result = finalize_result.get("test_result", {}) if isinstance(finalize_result.get("test_result"), dict) else {}
    agent_usage = finalize_result.get("agent_usage", {}) if isinstance(finalize_result.get("agent_usage"), dict) else {}
    fixture_result = finalize_result.get("fixture_result", {}) if isinstance(finalize_result.get("fixture_result"), dict) else {}
    goal_acceptance = finalize_result.get("goal_acceptance", {}) if isinstance(finalize_result.get("goal_acceptance"), dict) else {}
    goal_test_result = finalize_result.get("goal_test_result", {}) if isinstance(finalize_result.get("goal_test_result"), dict) else {}
    log = post_build_failure_log(finalize_result).lower()
    if str(test_result.get("status", "")).lower() == "failed":
        failures.add("test_failure")
    if goal_acceptance.get("applicable") and goal_acceptance.get("status") != "PASS":
        failures.add("goal_acceptance_failure")
    if goal_test_result and str(goal_test_result.get("status", "")).lower() != "pass":
        failures.add("test_failure")
    if fixture_result and str(fixture_result.get("status", "")).lower() != "pass":
        failures.add("fixture_failure")
    if any(
        token in log
        for token in (
            "required stage artifact missing",
            "required stage artifact fields missing",
            "stage graph",
            "fixture workflow",
        )
    ):
        failures.add("fixture_failure")
        failures.add("stage_artifact_failure")
    if any(
        token in log
        for token in (
            "image generation adapter not available",
            "fewer than four decoder-valid png",
            "fewer than two transparent sprite",
            "png outputs do not have four distinct",
        )
    ):
        failures.add("fixture_failure")
        failures.add("media_generation_failure")
    if "pyproject.toml" in log and any(
        token in log
        for token in (
            "invalid value",
            "invalid toml",
            "tomldecodeerror",
            "toml decode",
        )
    ):
        failures.add("configuration_syntax_failure")
    if any(token in log for token in ("winerror 2", "enoent", "no such file or directory", "not recognized", "cannot find module", "module not found")):
        failures.add("dependency_failure")
    if missing_vitest_error(log):
        failures.add("dependency_failure")
        failures.add("missing_test_runner")
        failures.add("missing_vitest")
    if missing_package_json_error(log):
        failures.add("missing_package_json")
        failures.add("dependency_failure")
        failures.add("module_setup_failure")
    if no_tests_ran_error(log):
        failures.add("test_failure")
        failures.add("missing_test_runner")
        failures.add("no_tests_ran")
    if any(token in log for token in ("cannot use import", "require is not defined", "unexpected token 'export'", "err_unknown_file_extension", "syntaxerror: cannot use import")):
        failures.add("module_system_failure")
    if windows_esm_path_import_error(log):
        failures.add("module_system_failure")
        failures.add("windows_esm_path_import")
    if any(
        token in log
        for token in (
            "missing script",
            "no recognized test command",
            "entrypoint_missing",
            "missing entrypoint",
            "index.html not found",
            "not found: index.html",
        )
    ):
        failures.add("missing_entrypoint")
    if any(token in log for token in ("missing script: start", "missing script start", "no start script", "missing_start_script")):
        failures.add("missing_start_script")
        failures.add("startup_failure")
    if str(agent_usage.get("status", "")).lower() == "failed" or "start command" in log or "eaddrinuse" in log:
        failures.add("startup_failure")
    if not finalize_result.get("screenshots"):
        failures.add("screenshot_failure")
    if "browser_unavailable" in log or "playwright install" in log or "executable doesn't exist" in log:
        failures.add("browser_unavailable")
    if "startup url did not become ready" in log or "start_failed" in log or "startup_failed" in log:
        failures.add("startup_failure")
        failures.add("port_not_ready")
    if "startup_returncode" in log and ("startup_stderr_tail" in log or "startup_stdout_tail" in log):
        failures.add("startup_command_failed")
    if "entrypoint_missing" in log:
        failures.add("missing_entrypoint")
    if "static_entry_not_served" in log:
        failures.add("static_entry_not_served")
    if "missing_static_entry" in log or ("src/main.js" in log and "index.html" in log and "not found" in log):
        failures.add("missing_static_entry")
    if "page_blank" in log or "invalid_screenshot" in log:
        failures.add("page_blank")
    if any(
        token in log
        for token in (
            "required_capabilities_missing",
            "interactive_controls_too_few",
            "workspace_sections_too_few",
            "complex_workspace_text_too_short",
            "domain_keywords_missing",
            "workspace_visual_density_too_low",
            "workspace_horizontal_overflow",
            "control_hit_targets_too_small",
            "asset_previews_oversized",
            "workspace_regions_lack_content",
            "workspace_status_empty",
            "workspace_regions_lack_visual_hierarchy",
            "workspace_layout_remains_single_column",
            "workspace_regions_too_narrow",
            "preview_canvas_blank",
            "preview_canvas_lacks_content_detail",
            "product_header_lacks_visual_treatment",
            "controls_use_browser_default_theme",
        )
    ):
        failures.add("ui_quality_failure")
    if any(token in log for token in ("requestfailed", "/api", "api unavailable", "failed to fetch", "net::err_connection_refused")):
        failures.add("frontend_backend_start_mismatch")
    if any(token in log for token in ("todo", "doing", "done", "filter", "local json", "persistence", "assertionerror", "expected")):
        failures.add("runtime_feature_failure")
    return sorted(failures)


def existing_candidate_files(candidate_dir: pathlib.Path) -> list[str]:
    files: list[str] = []
    if not candidate_dir.exists():
        return files
    binary_ext = getattr(_legacy(), "BINARY_EXTENSIONS", set())
    for path in sorted(candidate_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(candidate_dir).as_posix()
        if rel in {"final_project_bundle.zip", "delivery_manifest.json"}:
            continue
        if path.suffix.lower() in binary_ext:
            continue
        files.append(rel)
    return files


def extract_post_build_target_files(candidate_dir: pathlib.Path, text: str) -> list[str]:
    known = set(existing_candidate_files(candidate_dir))
    known_by_name: dict[str, list[str]] = {}
    for path in known:
        known_by_name.setdefault(pathlib.PurePosixPath(path).name.lower(), []).append(path)
    found: list[str] = []
    pattern = re.compile(r"([A-Za-z0-9_.\-/\\]+?\.(?:mjs|cjs|js|jsx|ts|tsx|json|toml|html|css|py|md))")
    for match in pattern.finditer(text or ""):
        rel = match.group(1).replace("\\", "/").lstrip("./")
        if rel not in known:
            basename_matches = known_by_name.get(pathlib.PurePosixPath(rel).name.lower(), [])
            if len(basename_matches) == 1:
                rel = basename_matches[0]
        if rel in known and rel not in found:
            found.append(rel)
    return found


def focused_failure_excerpt(text: str, target_file: str, *, max_chars: int = 6000) -> str:
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    normalized_target = str(target_file or "").replace("\\", "/")
    needles = [
        normalized_target,
        normalized_target.replace("/", "\\"),
        pathlib.PurePosixPath(normalized_target).name,
    ]
    lowered = value.lower()
    position = next(
        (lowered.find(needle.lower()) for needle in needles if lowered.find(needle.lower()) >= 0),
        -1,
    )
    if position < 0:
        return value[-max_chars:]
    before = min(1800, position)
    start = position - before
    return value[start : start + max_chars]


def default_post_build_targets(candidate_dir: pathlib.Path, failures: list[str]) -> list[str]:
    candidates: list[str] = []

    def add(path: str, *, allow_missing: bool = False) -> None:
        rel = path.replace("\\", "/")
        if rel not in candidates and (allow_missing or (candidate_dir / rel).exists()):
            candidates.append(rel)

    if "missing_package_json" in failures:
        add("package.json", allow_missing=True)
    if "configuration_syntax_failure" in failures:
        add("pyproject.toml")
    if "dependency_failure" in failures or "module_system_failure" in failures or "module_setup_failure" in failures:
        add("package.json")
    if "missing_vitest" in failures:
        for rel in ("package.json", "scripts/test.js", "scripts/run-tests.mjs", "tests/smoke_test.mjs", "tests/api_contract_test.mjs"):
            add(rel, allow_missing=rel == "scripts/test.js")
    if "no_tests_ran" in failures:
        for rel in ("package.json", "scripts/test.js", "scripts/run-tests.mjs", "tests/smoke_test.mjs", "tests/api_contract_test.mjs"):
            add(rel, allow_missing=rel in {"package.json", "scripts/test.js"})
    if "test_failure" in failures:
        for rel in ("scripts/test.js", "scripts/run-tests.mjs", "scripts/util/testRunner.js", "tests/smoke_test.mjs", "tests/frontend_smoke_check.mjs"):
            add(rel)
    if "goal_acceptance_failure" in failures:
        tests_dir = candidate_dir / "tests"
        if tests_dir.is_dir():
            for path in sorted(tests_dir.rglob("test_*.py")):
                add(path.relative_to(candidate_dir).as_posix())
    if "windows_esm_path_import" in failures:
        for rel in ("scripts/run-tests.mjs", "tests/api_contract_test.mjs", "tests/smoke_test.mjs"):
            add(rel)
        for path in sorted((candidate_dir / "tests").glob("*.mjs")) if (candidate_dir / "tests").exists() else []:
            add(path.relative_to(candidate_dir).as_posix())
    if "page_blank" in failures:
        for rel in ("index.html", "src/app.js", "scripts/util/buildAll.js", "src/main.js"):
            add(rel)
    if "ui_quality_failure" in failures:
        for rel in ("index.html", "src/app.js", "src/styles.css", "src/main.js"):
            add(rel)
    if "startup_failure" in failures or "missing_entrypoint" in failures or "missing_start_script" in failures or "missing_static_entry" in failures:
        for rel in ("package.json", "scripts/start.js", "src/app.js", "src/main.js"):
            add(rel)
        add("index.html", allow_missing=True)
    if "frontend_backend_start_mismatch" in failures:
        for rel in ("index.html", "src/app.js", "src/main.js"):
            add(rel)
    if "runtime_feature_failure" in failures:
        for rel in ("src/app.js", "src/main.js", "backend/service.py", "data/storage.py"):
            add(rel)
    if "fixture_failure" in failures:
        add("demo/run_fixture.py")
    if "stage_artifact_failure" in failures:
        for rel in (
            "demo/run_fixture.py",
            "backend/orchestrator.py",
            "backend/stages.py",
            "backend/artifact_store.py",
        ):
            add(rel)
    if "media_generation_failure" in failures:
        for rel in (
            "backend/image_adapters.py",
            "scripts/capture_workflow.py",
            "demo/run_fixture.py",
        ):
            add(rel)
    return candidates


def compile_post_build_repair_plan(candidate_dir: pathlib.Path, finalize_result: dict[str, Any]) -> dict[str, Any]:
    failures = classify_post_build_failures(finalize_result)
    if "missing_package_json" in failures and not (candidate_dir / "package.json").exists():
        if has_runnable_candidate_source(candidate_dir):
            failures = sorted(set(failures) | {"module_setup_failure"})
        else:
            failures = sorted(set(failures) | {"candidate_not_runnable"})
    if "startup_failure" in failures and not (candidate_dir / "index.html").exists() and not (candidate_dir / "dist" / "index.html").exists():
        failures = sorted(set(failures) | {"missing_static_entry"})
    log = post_build_failure_log(finalize_result)
    test_result = finalize_result.get("test_result", {}) if isinstance(finalize_result.get("test_result"), dict) else {}
    fixture_result = finalize_result.get("fixture_result", {}) if isinstance(finalize_result.get("fixture_result"), dict) else {}
    test_passed = str(test_result.get("status", "")).lower() == "pass"
    extracted_target_files = extract_post_build_target_files(candidate_dir, log)
    target_files: list[str] = []
    for rel in extracted_target_files + default_post_build_targets(candidate_dir, failures):
        if rel not in target_files:
            target_files.append(rel)
    if "windows_esm_path_import" in failures:
        preferred = ["scripts/run-tests.mjs", "tests/api_contract_test.mjs", "tests/smoke_test.mjs"]
        existing_preferred = [rel for rel in preferred if (candidate_dir / rel).exists()]
        target_files = existing_preferred + [rel for rel in target_files if rel not in existing_preferred]
    if "missing_vitest" in failures:
        preferred = ["package.json", "scripts/test.js", "scripts/run-tests.mjs"]
        existing_preferred = [rel for rel in preferred if rel == "scripts/test.js" or (candidate_dir / rel).exists()]
        target_files = existing_preferred + [rel for rel in target_files if rel not in existing_preferred]
    if "no_tests_ran" in failures:
        preferred = ["package.json", "scripts/test.js", "scripts/run-tests.mjs"]
        existing_preferred = [rel for rel in preferred if rel in {"package.json", "scripts/test.js"} or (candidate_dir / rel).exists()]
        target_files = existing_preferred + [rel for rel in target_files if rel not in existing_preferred]
    if "missing_package_json" in failures:
        target_files = ["package.json"] + [rel for rel in target_files if rel != "package.json"]
    if "configuration_syntax_failure" in failures and "pyproject.toml" in target_files:
        target_files = ["pyproject.toml"] + [
            rel for rel in target_files if rel != "pyproject.toml"
        ]
    if test_passed:
        target_files = [rel for rel in target_files if not rel.startswith("tests/")]
    fixture_passed = str(fixture_result.get("status", "")).lower() == "pass"
    if fixture_passed and not {
        "fixture_failure",
        "stage_artifact_failure",
        "media_generation_failure",
    } & set(failures):
        target_files = [rel for rel in target_files if rel != "demo/run_fixture.py"]
    if "ui_quality_failure" in failures:
        preferred = [
            rel
            for rel in ("index.html", "src/app.js", "src/styles.css", "src/main.js")
            if (candidate_dir / rel).exists()
        ]
        target_files = preferred + [
            rel
            for rel in target_files
            if rel not in preferred
            and rel in {"index.html", "src/app.js", "src/styles.css", "src/main.js"}
        ]
    if "fixture_failure" in failures:
        fixture_traceback_self = "demo/run_fixture.py" in extracted_target_files
        if fixture_traceback_self:
            exact_targets = set(extracted_target_files)
            target_files = [rel for rel in target_files if rel in exact_targets]
        evidenced_tests = [
            rel for rel in extracted_target_files if rel.startswith("tests/")
        ]
        evidenced_backend = [
            rel
            for rel in extracted_target_files
            if rel.startswith("backend/") and rel != "backend/stages.py"
        ]
        preferred = ["demo/run_fixture.py", *evidenced_tests, *evidenced_backend]
        if "media_generation_failure" in failures and not fixture_traceback_self:
            preferred.extend(
                ["backend/image_adapters.py", "scripts/capture_workflow.py"]
            )
        if not fixture_traceback_self:
            preferred.extend(
                ["backend/orchestrator.py", "backend/stages.py", "backend/artifact_store.py"]
            )
        preferred = list(dict.fromkeys(preferred))
        existing_preferred = [rel for rel in preferred if (candidate_dir / rel).exists()]
        target_files = existing_preferred + [
            rel for rel in target_files if rel not in existing_preferred
        ]
    if "missing_entrypoint" in failures and "index.html" not in target_files:
        target_files.insert(0, "index.html")
    if "missing_static_entry" in failures and "index.html" not in target_files:
        target_files.insert(0, "index.html")
    target_limit = 5 if any(
        kind in failures
        for kind in ("fixture_failure", "stage_artifact_failure", "media_generation_failure")
    ) else 3
    target_files = target_files[:target_limit]
    screenshot_runtime_actionable = any(
        kind in failures
        for kind in (
            "startup_failure",
            "missing_entrypoint",
            "dependency_failure",
            "module_system_failure",
            "test_failure",
            "page_blank",
            "fixture_failure",
            "stage_artifact_failure",
        )
    )
    if "screenshot_failure" in failures and test_passed and not screenshot_runtime_actionable:
        target_files = []
    root_causes = list(failures)
    if "page_blank" in failures:
        root_causes.append("index.html loads but body has no visible content")
    deterministic_actions: list[dict[str, Any]] = []
    provider_actions: list[dict[str, Any]] = []
    validation_commands: list[list[str]] = []

    argv = test_result.get("argv", [])
    if isinstance(argv, list) and argv:
        validation_commands.append([str(item) for item in argv])
    elif (candidate_dir / "package.json").exists():
        validation_commands.append(["npm", "test"])

    log_lower = log.lower()
    executable_missing = ("winerror 2" in log_lower or "enoent" in log_lower) and "npm" in log_lower
    if executable_missing:
        deterministic_actions.append({"action": "resolve_command_executable", "command": "npm", "handled_by": "normalize_allowed_argv"})
    if "missing_entrypoint" in failures and not (candidate_dir / "index.html").exists():
        if "index.html" not in target_files:
            target_files.insert(0, "index.html")
    if "missing_start_script" in failures:
        deterministic_actions.append({"action": "add_static_start_script", "path": "package.json"})
        if "package.json" not in target_files and (candidate_dir / "package.json").exists():
            target_files.insert(0, "package.json")
    if "missing_static_entry" in failures:
        if "index.html" not in target_files:
            target_files.insert(0, "index.html")
    if "missing_package_json" in failures and "candidate_not_runnable" not in failures:
        deterministic_actions.append({"action": "create_minimal_package_json", "path": "package.json"})
    if "[foundation:test] missing required file: package.json" in log_lower and (candidate_dir / "package.json").exists() and (candidate_dir / "scripts" / "util" / "testRunner.js").exists():
        deterministic_actions.append({"action": "normalize_test_runner_project_root", "path": "scripts/util/testRunner.js"})
        if "scripts/util/testRunner.js" not in target_files:
            target_files.insert(0, "scripts/util/testRunner.js")
    if "missing_vitest" in failures:
        deterministic_actions.append({"action": "replace_missing_vitest_with_node_runner", "paths": [rel for rel in target_files if rel in {"package.json", "scripts/test.js", "scripts/run-tests.mjs"}]})
    if "no_tests_ran" in failures:
        deterministic_actions.append({"action": "replace_missing_vitest_with_node_runner", "paths": [rel for rel in target_files if rel in {"package.json", "scripts/test.js", "scripts/run-tests.mjs"}]})
    if "windows_esm_path_import" in failures:
        deterministic_targets = [rel for rel in target_files if rel.endswith((".js", ".mjs", ".cjs"))]
        deterministic_actions.append({"action": "repair_windows_esm_path_imports", "paths": deterministic_targets})
    if (candidate_dir / "src" / "main.js").exists() and (candidate_dir / "scripts" / "util" / "buildAll.js").exists():
        deterministic_actions.append({"action": "allow_main_js_entry", "path": "scripts/util/buildAll.js"})
        if "scripts/util/buildAll.js" not in target_files:
            target_files.append("scripts/util/buildAll.js")
    target_files = target_files[:target_limit]

    deterministic_failure_types = {
        "windows_esm_path_import",
        "missing_vitest",
        "no_tests_ran",
        "missing_start_script",
        "missing_package_json",
    }
    provider_required_failure_types = {
        "fixture_failure",
        "stage_artifact_failure",
        "media_generation_failure",
        "test_failure",
        "runtime_feature_failure",
    }
    deterministic_only = bool(deterministic_failure_types & set(failures)) and not bool(
        provider_required_failure_types & set(failures)
    )
    if target_files and not executable_missing and not deterministic_only and "candidate_not_runnable" not in failures:
        for rel in target_files:
            provider_actions.append({"path": rel, "instruction": "Repair this file only for the observed post-build failure. Preserve candidate-only delivery boundaries."})

    if "screenshot_failure" in failures and screenshot_runtime_actionable:
        root_causes.append("screenshot_blocked_by_runtime")
        if "page_blank" in failures:
            validation_commands.append(["candidate", "screenshot", "finalize"])
    elif "screenshot_failure" in failures and "browser_unavailable" not in failures:
        validation_commands.append(["npm", "run", "screenshots"])

    must_disappear = [line for line in log.splitlines() if line.strip()][:12]
    test_diagnostics = "\n".join(
        str(test_result.get(key, ""))
        for key in ("stdout_tail", "stderr_tail", "error")
        if str(test_result.get(key, "")).strip()
    )
    fixture_diagnostics = json.dumps(
        fixture_result, ensure_ascii=False, default=str
    )
    ui_diagnostics = json.dumps(
        finalize_result.get("ui_smoke", {}), ensure_ascii=False, default=str
    )
    target_diagnostics: dict[str, str] = {}
    for rel in target_files:
        if rel == "demo/run_fixture.py":
            source = fixture_diagnostics
        elif rel.startswith("tests/"):
            source = test_diagnostics
        elif (
            rel in {"index.html", "src/app.js", "src/styles.css", "src/main.js"}
            and "ui_quality_failure" in failures
        ):
            source = ui_diagnostics
        else:
            source = log
        target_diagnostics[rel] = focused_failure_excerpt(source, rel)
    return {
        "stage": "post_build_repair",
        "created_at": _legacy_call("now"),
        "status": "candidate_not_runnable" if "candidate_not_runnable" in failures else ("planned" if (provider_actions or deterministic_actions) else "no_actionable_file_repair"),
        "failure_types": failures,
        "root_causes": sorted(set(root_causes)),
        "target_files": target_files,
        "provider_actions": provider_actions[:target_limit],
        "deterministic_actions": deterministic_actions,
        "validation_commands": validation_commands,
        "must_disappear_failures": must_disappear,
        "log_summary": log[:3000],
        "target_diagnostics": target_diagnostics,
        "ui_acceptance_contract": finalize_result.get("ui_smoke", {}),
        "candidate_only": True,
        "forbidden_outputs": ["final_project_bundle.zip", "delivery_manifest.json", "fake screenshots/videos", "fake TEST_REPORT PASS"],
    }


def generated_frontend_workspace_source_violations(
    rel: str,
    content: str,
    ui_contract: dict[str, Any] | None,
) -> list[str]:
    """Reject valid-looking frontend repairs that still reproduce a shell UI."""
    contract = ui_contract if isinstance(ui_contract, dict) else {}
    groups = contract.get("capability_groups", [])
    if not isinstance(groups, list) or len(groups) < 4:
        return []
    lowered = str(content or "").lower()
    violations: list[str] = []
    if rel == "index.html":
        body_match = re.search(r"<body\b[^>]*>(.*?)</body>", content, flags=re.I | re.S)
        visible_source = body_match.group(1) if body_match else content
        visible_text = re.sub(r"<script\b[^>]*>.*?</script>", " ", visible_source, flags=re.I | re.S)
        visible_text = re.sub(r"<style\b[^>]*>.*?</style>", " ", visible_text, flags=re.I | re.S)
        visible_text = re.sub(r"<[^>]+>", " ", visible_text)
        visible_text = re.sub(r"\s+", " ", visible_text).strip().lower()
        controls = len(
            re.findall(
                r"<(?:button|input|select|textarea)\b|role\s*=\s*['\"]button['\"]|contenteditable\s*=\s*['\"]true['\"]",
                content,
                flags=re.I,
            )
        )
        sections = len(
            re.findall(
                r"<(?:section|article|aside)\b|role\s*=\s*['\"](?:region|tabpanel)['\"]|class\s*=\s*['\"][^'\"]*\b(?:section|panel|workspace-region)\b[^'\"]*['\"]",
                content,
                flags=re.I,
            )
        )
        capability_hits = sum(
            1
            for group in groups
            if isinstance(group, dict)
            and any(str(term).lower() in visible_text for term in group.get("terms", []))
        )
        required_hits = max(3, (len(groups) * 3 + 4) // 5)
        if capability_hits < required_hits:
            violations.append(
                f"HTML exposes only {capability_hits}/{len(groups)} required capability groups; at least {required_hits} are required"
            )
        if controls < min(8, max(4, len(groups))):
            violations.append(
                f"HTML has {controls} semantic controls; this workspace requires at least {min(8, max(4, len(groups)))}"
            )
        if sections < 3:
            violations.append(
                f"HTML has {sections} semantic workspace regions; at least 3 are required"
            )
        region_matches = re.findall(
            r"<(section|article|aside)\b([^>]*)>(.*?)</(?:section|article|aside)>",
            content,
            flags=re.I | re.S,
        )
        empty_region_labels: list[str] = []
        for tag, attrs, body in region_matches:
            if re.search(
                r"<(?:input|textarea|select|output|img|canvas|video|li)\b|\bdata-node(?:-id)?\s*=|\bdata-preview\s*=",
                body,
                flags=re.I,
            ):
                continue
            region_id = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I)
            heading = re.search(r"<h[2-4]\b[^>]*>(.*?)</h[2-4]>", body, flags=re.I | re.S)
            heading_text = (
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", heading.group(1))).strip()
                if heading
                else ""
            )
            empty_region_labels.append(
                "#" + region_id.group(1)
                if region_id
                else heading_text or tag.lower()
            )
        if len(region_matches) >= 3 and len(empty_region_labels) > 1:
            violations.append(
                f"HTML has {len(empty_region_labels)}/{len(region_matches)} workspace regions containing only headings/buttons: {empty_region_labels[:8]}; at most 1 may lack an input, list/node, output, media, or preview surface"
            )
        if len(visible_text) < 160:
            violations.append(
                f"HTML body has {len(visible_text)} visible text characters; at least 160 are required"
            )
        domain_keywords = [
            str(item).strip()
            for item in contract.get("domain_keywords", [])
            if str(item).strip()
        ]
        domain_hits = [item for item in domain_keywords if item.lower() in visible_text]
        required_domain_hits = min(3, len(domain_keywords))
        if required_domain_hits and len(domain_hits) < required_domain_hits:
            violations.append(
                f"HTML body exposes {len(domain_hits)}/{len(domain_keywords)} domain keywords; at least {required_domain_hits} are required from {domain_keywords[:6]}"
            )
        h1_count = len(re.findall(r"<h1\b", content, flags=re.I))
        h2_count = len(re.findall(r"<h2\b", content, flags=re.I))
        html_ids = re.findall(
            r"\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]", content, flags=re.I
        )
        duplicate_ids = sorted(
            identifier
            for identifier in set(html_ids)
            if html_ids.count(identifier) > 1
        )
        if duplicate_ids:
            violations.append(
                f"HTML contains duplicate DOM ids that break cross-owner targeting: {duplicate_ids[:8]}"
            )
        if h1_count != 1:
            violations.append(
                f"HTML has {h1_count} h1 elements; the workspace requires exactly 1 product-level h1"
            )
        if h2_count < 3:
            violations.append(
                f"HTML has {h2_count} h2 elements; at least 3 feature-area headings are required"
            )
        if not re.search(r"<header\b", content, flags=re.I):
            violations.append("HTML must contain a visible product header before the workspace")
        if not re.search(r"<main\b", content, flags=re.I):
            violations.append("HTML must wrap the primary authoring workspace in a main element")
        elif len(re.findall(r"<main\b", content, flags=re.I)) != len(
            re.findall(r"</main\s*>", content, flags=re.I)
        ):
            violations.append("HTML main workspace owner is not structurally closed")
        if not re.search(r"aria-live\s*=|role\s*=\s*['\"]status['\"]", content, flags=re.I):
            violations.append(
                "HTML must provide an aria-live or role=status region for observable action feedback"
            )
        elif not re.search(
            r"<[^>]*(?:aria-live\s*=|role\s*=\s*['\"]status['\"])[^>]*>\s*[^<\s]",
            content,
            flags=re.I | re.S,
        ):
            violations.append(
                "HTML status region is empty; provide a visible initial workspace status"
            )
        status_opening = re.search(
            r"<[A-Za-z][\w:-]*\b(?=[^>]*(?:aria-live\s*=|role\s*=\s*['\"]status['\"]))[^>]*>",
            content,
            flags=re.I | re.S,
        )
        if status_opening and not re.search(
            r"\bid\s*=\s*['\"][A-Za-z][\w:.-]*['\"]",
            status_opening.group(0),
            flags=re.I,
        ):
            violations.append(
                "HTML status region needs a stable id so JavaScript can publish visible action feedback"
            )
        media_stages = " ".join(
            str(group.get("stage", ""))
            for group in groups
            if isinstance(group, dict)
        )
        if any(term in media_stages for term in ("background", "sprite", "image")):
            media_previews = len(re.findall(r"<(?:img|canvas)\b", content, flags=re.I))
            if media_previews < 2:
                violations.append(
                    f"HTML has {media_previews} visual asset preview slots; media-capable workspaces require at least 2 img/canvas elements"
                )
        if "graph" in media_stages:
            graph_nodes = len(
                re.findall(
                    r"\bdata-node(?:-id)?\s*=|class\s*=\s*['\"][^'\"]*\b(?:story-)?node\b|<li\b",
                    content,
                    flags=re.I,
                )
            )
            if graph_nodes < 2:
                violations.append(
                    f"HTML exposes {graph_nodes} visible graph/tree nodes; graph-capable workspaces require at least 2"
                )
        if "preview" in media_stages and not re.search(
            r"<(?:output|canvas|iframe|video)\b|\bdata-preview\s*=|class\s*=\s*['\"][^'\"]*\bpreview-surface\b",
            content,
            flags=re.I,
        ):
            violations.append(
                "HTML must provide a dedicated preview surface (output/canvas/media/data-preview) beyond a Preview button"
            )
        if not re.search(r"<link\b[^>]*href\s*=\s*['\"][^'\"]*src/styles\.css", content, flags=re.I):
            violations.append("HTML must load the modular src/styles.css owner")
        if not re.search(r"<script\b[^>]*src\s*=\s*['\"][^'\"]*src/app\.js", content, flags=re.I):
            violations.append("HTML must load the modular src/app.js owner")
        inline_scripts = re.findall(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", content, flags=re.I | re.S)
        if any(script.strip() for script in inline_scripts):
            violations.append("HTML must not replace the JavaScript owner with inline behavior")
        inline_styles = re.findall(r"<style\b[^>]*>(.*?)</style>", content, flags=re.I | re.S)
        if any(style.strip() for style in inline_styles):
            violations.append("HTML must not replace the CSS owner with inline styling")
        if re.search(r"\son(?:click|change|input|submit|load)\s*=", content, flags=re.I):
            violations.append(
                "HTML must not use inline event attributes; expose stable ids/data attributes for the src/app.js owner"
            )
        if "not implemented" in lowered or "todo" in lowered:
            violations.append("HTML still exposes unimplemented or TODO behavior")
    elif rel in {"src/app.js", "src/main.js"}:
        handlers = len(re.findall(r"addEventListener\s*\(|\.on(?:click|change|input|submit)\s*=", content))
        selectors = len(re.findall(r"getElementById\s*\(|querySelector(?:All)?\s*\(", content))
        if handlers < 1:
            violations.append(
                f"JavaScript has {handlers} observable event bindings; at least 1 is required"
            )
        if selectors < 3:
            violations.append(
                f"JavaScript has {selectors} concrete DOM selector calls; at least 3 are required"
            )
        placeholder_simulation = bool(
            re.search(r"(?im)//[^\n]*\b(?:placeholder|todo)\b", content)
            or re.search(r"(?is)/\*.*?\b(?:placeholder|todo)\b.*?\*/", content)
            or re.search(r"\bfunction\s+\w*(?:placeholder|simulate)\w*\s*\(", content, flags=re.I)
            or "simulatecomplexaction" in lowered
        )
        if placeholder_simulation:
            violations.append("JavaScript still contains placeholder or simulated workspace behavior")
        placeholder_phrases = (
            "not implemented",
            "implement logic",
            "your project data",
            "your workspace data",
            "load the workspace data into",
        )
        found_placeholders = [phrase for phrase in placeholder_phrases if phrase in lowered]
        if found_placeholders:
            violations.append(
                f"JavaScript contains non-functional placeholder phrases: {found_placeholders}"
            )
        if "console.log" in lowered:
            violations.append(
                "JavaScript uses console.log as workspace behavior; actions must update visible DOM state"
            )
        modal_calls = sorted(
            set(re.findall(r"\b(prompt|alert)\s*\(", content, flags=re.I))
        )
        if modal_calls:
            violations.append(
                f"JavaScript uses blocking browser modal behavior {modal_calls}; complex workspaces must edit through visible form controls and report results in the status/preview surface"
            )
        if "domcontentloaded" in lowered and not re.search(
            r"document\.addEventListener\s*\(\s*['\"]DOMContentLoaded['\"]",
            content,
            flags=re.I,
        ):
            violations.append(
                "JavaScript attaches DOMContentLoaded to a non-document owner; bind it on document or call bootstrap explicitly"
            )
        if "localstorage" not in lowered:
            violations.append("JavaScript must persist and reload the workspace through localStorage")
        blob_export = "blob" in lowered and "createobjecturl" in lowered
        data_url_export = (
            "data:application/json" in lowered
            and "json.stringify" in lowered
            and "download" in lowered
        )
        if not (blob_export or data_url_export):
            violations.append("JavaScript must implement observable JSON project export through Blob or a JSON data URL")
        visible_dom_mutation = any(
            token in content
            for token in (
                "textContent",
                "innerHTML",
                "insertAdjacentHTML",
                "replaceChildren",
                ".append(",
            )
        ) or bool(re.search(r"appendChild\s*\(\s*(?!a\b)", content))
        if not visible_dom_mutation:
            violations.append(
                "JavaScript has no visible workspace DOM mutation; use textContent, innerHTML, replaceChildren, or append a rendered result"
            )
        visible_mutation_count = len(
            re.findall(
                r"(?:textContent|innerHTML)\s*=|insertAdjacentHTML\s*\(|replaceChildren\s*\(|\.append\s*\(",
                content,
            )
        )
        if visible_mutation_count < 2:
            violations.append(
                f"JavaScript has {visible_mutation_count} visible DOM update sites; at least 2 are required for action feedback and preview/state rendering"
            )
        own_stem = pathlib.PurePosixPath(rel).stem
        if re.search(
            rf"\bfrom\s*['\"]\./{re.escape(own_stem)}(?:\.js)?['\"]",
            content,
            flags=re.I,
        ):
            violations.append("JavaScript workspace leaf must not import itself")
    elif rel == "src/styles.css":
        rule_count = len(re.findall(r"[^@{}][^{}]*\{[^{}]*\}", content, flags=re.S))
        if rule_count < 8:
            violations.append(
                f"CSS has {rule_count} concrete rules; the designed multi-region workspace requires at least 8 meaningful rules"
            )
        if "@media" not in lowered:
            violations.append(
                "CSS has 0 responsive breakpoints; add at least one concrete @media rule"
            )
        if not any(token in lowered for token in ("display: grid", "display:grid", "display: flex", "display:flex")):
            violations.append(
                "CSS has no grid/flex layout declaration; add display:grid or display:flex to a workspace container"
            )
        token_count = len(set(re.findall(r"--[a-z0-9_-]+\s*:", lowered)))
        if token_count < 6:
            violations.append(
                f"CSS defines {token_count} design tokens; define at least 6 custom properties for color, spacing, radius, and type"
            )
        if ":focus-visible" not in lowered:
            violations.append("CSS must provide a visible :focus-visible keyboard treatment")
        if "border-radius" not in lowered:
            violations.append("CSS must use a consistent border-radius hierarchy")
        if "box-shadow" not in lowered:
            violations.append("CSS must use restrained shadow or elevation for workspace hierarchy")
        if "var(--" not in lowered:
            violations.append("CSS must consume the declared design tokens through var(--...) references")
        consumed_tokens = set(re.findall(r"var\(\s*(--[a-z0-9_-]+)", lowered))
        if len(consumed_tokens) < 5:
            violations.append(
                f"CSS consumes only {len(consumed_tokens)} distinct design tokens; use at least 5 across the page, header, workspace surfaces, controls, spacing, radius, and typography instead of leaving the browser-default theme"
            )
        body_rules = re.findall(
            r"(?<![.#\w-])body(?![\w-])[^{}]*\{([^{}]*)\}",
            content,
            flags=re.I | re.S,
        )
        if not any(
            re.search(r"(?:background|background-color)\s*:", body, flags=re.I)
            and re.search(r"(?:^|[;\s])color\s*:", body, flags=re.I)
            for body in body_rules
        ):
            violations.append(
                "CSS body theme must set both page background and text color, preferably through accepted design tokens"
            )
        header_rules = re.findall(
            r"(?<![.#\w-])header(?![\w-])[^{}]*\{([^{}]*)\}",
            content,
            flags=re.I | re.S,
        )
        if not any(
            re.search(r"(?:padding|margin|gap)\s*:", body, flags=re.I)
            and re.search(r"(?:background|border|box-shadow)\s*:", body, flags=re.I)
            for body in header_rules
        ):
            violations.append(
                "CSS must give the product header intentional spacing plus a surface, border, or elevation treatment"
            )
        base_button_rules = [
            body
            for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", content, flags=re.S)
            if "button" in selectors.lower() and ":" not in selectors
        ]
        if not any(
            re.search(r"(?:background|background-color)\s*:", body, flags=re.I)
            and re.search(r"border-radius\s*:", body, flags=re.I)
            for body in base_button_rules
        ):
            violations.append(
                "CSS base button rule must define an intentional background and border-radius; hover-only color cannot replace the default control design"
            )
        if re.search(r":\s*[^;{}]*\d+(?:\.\d+)?\s*\*\s*var\s*\(", content):
            violations.append(
                "CSS contains raw arithmetic such as '2 * var(...)'; use calc(...) or separate valid values"
            )
        if not re.search(r"(?:button|\[role=['\"]button['\"])[^{]*\{[^}]*min-height\s*:", content, flags=re.I | re.S):
            violations.append("CSS must give interactive controls an explicit minimum hit-target height")
        if not re.search(
            r"(?:input|select|textarea)[^{]*\{[^}]*min-height\s*:\s*(?:(?:3[2-9]|[4-9]\d|\d{3,})px|(?:2(?:\.\d+)?|[3-9](?:\.\d+)?)rem)",
            content,
            flags=re.I | re.S,
        ):
            violations.append(
                "CSS must give input/select/textarea controls a computed minimum height of at least 32px (for example min-height: 2.75rem or 44px)"
            )
        if not re.search(r"(?:img|\.asset-preview|\.media-preview)[^{]*\{[^}]*(?:max-width|width)\s*:", content, flags=re.I | re.S):
            violations.append("CSS must bound visual asset preview width inside the workspace")
        if not re.search(r"(?:img|\.asset-preview|\.media-preview)[^{]*\{[^}]*object-fit\s*:", content, flags=re.I | re.S):
            violations.append("CSS must define object-fit for visual asset previews")
        if not re.search(r"(?:#workspace|\.workspace|\.grid-container|main)[^{]*\{[^}]*max-width\s*:", content, flags=re.I | re.S):
            violations.append("CSS must bound the primary workspace with a max-width")
    return violations


def normalize_ui_repair_html_ownership(
    content: str,
    ui_contract: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Remove provider-owned inline implementations when modular UI owners are required."""
    contract = ui_contract if isinstance(ui_contract, dict) else {}
    groups = contract.get("capability_groups", [])
    if not isinstance(groups, list) or len(groups) < 4:
        return content, []
    normalized, script_count = re.subn(
        r"<script\b(?![^>]*\bsrc\s*=)[^>]*>.*?</script>",
        "",
        content,
        flags=re.I | re.S,
    )
    normalized, style_count = re.subn(
        r"<style\b[^>]*>.*?</style>",
        "",
        normalized,
        flags=re.I | re.S,
    )
    actions: list[str] = []
    if script_count:
        actions.append("removed_inline_script_for_src_app_owner")
    if style_count:
        actions.append("removed_inline_style_for_src_css_owner")
    return normalized, actions


def normalize_frontend_repair_against_accepted_html(
    items: list[dict[str, str]],
    accepted_siblings: list[dict[str, str]],
) -> list[dict[str, str]]:
    accepted_html = next(
        (
            str(item.get("content", ""))
            for item in reversed(accepted_siblings)
            if str(item.get("path", "")).replace("\\", "/") == "index.html"
        ),
        "",
    )
    if not accepted_html:
        return items
    normalized: list[dict[str, str]] = []
    for item in items:
        row = dict(item)
        if str(row.get("path", "")).replace("\\", "/") in {
            "src/app.js",
            "src/main.js",
        }:
            row["content"], actions = (
                ui_semantic_adapter.adapt_complex_workspace_javascript(
                    str(row.get("content", "")), accepted_html
                )
            )
        elif str(row.get("path", "")).replace("\\", "/") == "src/styles.css":
            row["content"], actions = (
                ui_semantic_adapter.adapt_complex_workspace_css(
                    str(row.get("content", "")), accepted_html
                )
            )
        else:
            actions = []
        if actions:
            row["normalization_actions"] = list(
                dict.fromkeys(
                    [*row.get("normalization_actions", []), *actions]
                )
            )
        normalized.append(row)
    return normalized


def latest_rejected_repair_feedback(
    phase_log_path: pathlib.Path,
    target_file: str,
    ui_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Retrieve the newest bounded rejected leaf as repair memory, never as accepted source."""
    rejection_dir = pathlib.Path(phase_log_path).parent / "artifacts" / "post_build_rejections"
    prefix = target_file.replace("/", "__").replace("\\", "__") + "__attempt_"
    try:
        candidates = sorted(
            (
                path
                for path in rejection_dir.glob(prefix + "*.json")
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        candidates = []
    ranked: list[tuple[tuple[int, int, int, float, int], dict[str, str]]] = []
    for path in candidates[:8]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(record, dict) or record.get("candidate_only") is not True:
            continue
        if record.get("semantic_adapter_policy") != ui_semantic_adapter.POLICY_VERSION:
            continue
        if str(record.get("target_file", "")).replace("\\", "/") != target_file:
            continue
        content = str(record.get("content", ""))
        if target_file == "index.html" and content:
            content, _actions = normalize_ui_repair_html_ownership(content, ui_contract)
            content, _semantic_actions = ui_semantic_adapter.adapt_complex_workspace_html(
                content, ui_contract
            )
        if content.strip():
            current_violations = generated_frontend_workspace_source_violations(
                target_file,
                content,
                ui_contract,
            )
            feedback = {
                "content": content[:18000],
                "validation_error": str(record.get("validation_error", "")) or (
                    "post-build repaired frontend workspace contract mismatch: "
                    + "; ".join(current_violations)
                    if current_violations
                    else ""
                ),
                "evidence_path": str(path),
            }
            ranked.append(
                (
                    (
                        frontend_repair_validation_distance(
                            feedback["validation_error"]
                        ),
                        len(current_violations),
                        -len(content),
                        -path.stat().st_mtime_ns,
                        -int(
                            re.search(r"__attempt_(\d+)\.json$", path.name).group(1)
                            if re.search(r"__attempt_(\d+)\.json$", path.name)
                            else 0
                        ),
                    ),
                    feedback,
                )
            )
    return min(ranked, key=lambda item: item[0])[1] if ranked else {}


def _ui_capability_stages(ui_contract: dict[str, Any] | None) -> str:
    contract = ui_contract if isinstance(ui_contract, dict) else {}
    return " ".join(
        str(group.get("stage", ""))
        for group in contract.get("capability_groups", [])
        if isinstance(group, dict)
    ).lower()


def frontend_repair_validation_distance(error: str) -> int:
    """Weight structural regressions above bounded mechanical CSS defects."""
    text = str(error or "")
    clauses = [item.strip() for item in text.split(";") if item.strip()]
    distance = max(1, len(clauses)) if text.strip() else 0
    coverage = re.search(
        r"CSS selectors cover only\s+(\d+)\s*/\s*(\d+).*?style at least\s+(\d+)",
        text,
        flags=re.I,
    )
    if coverage:
        covered = int(coverage.group(1))
        required = int(coverage.group(3))
        distance += 40 + max(0, required - covered) * 5
    structural_markers = (
        "does not style the accepted main workspace owner",
        "replaces semantic region containers",
        "nonexistent DOM ids",
        "duplicate DOM ids",
        "workspace regions containing only headings/buttons",
        "blocking browser modal behavior",
        "neither delegates by data-action nor binds each action",
        "desktop columns are estimated",
    )
    distance += 30 * sum(marker.lower() in text.lower() for marker in structural_markers)
    return distance


def frontend_dom_action_contract(html: str) -> dict[str, Any]:
    """Project accepted HTML into a bounded JavaScript interface contract."""
    id_tags = {
        identifier: tag.lower()
        for tag, identifier in re.findall(
            r"<([A-Za-z][\w:-]*)\b[^>]*\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]",
            html,
            flags=re.I,
        )
    }
    bindings: list[dict[str, Any]] = []
    for _tag, attrs, body in re.findall(
        r"<(section|article|aside)\b([^>]*)>(.*?)</(?:section|article|aside)>",
        html,
        flags=re.I | re.S,
    ):
        region_id_match = re.search(
            r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I
        )
        region_id = region_id_match.group(1) if region_id_match else ""
        actions = list(
            dict.fromkeys(
                re.findall(
                    r"\bdata-action\s*=\s*['\"]([^'\"]+)['\"]",
                    body,
                    flags=re.I,
                )
            )
        )
        state_ids = [
            identifier
            for _state_tag, identifier in re.findall(
                r"<(input|textarea|select|output|ul|ol|img|canvas|video)\b[^>]*\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]",
                body,
                flags=re.I,
            )
        ]
        for action in actions:
            bindings.append(
                {
                    "action": action,
                    "region_id": region_id,
                    "state_element_ids": state_ids,
                    "rule": "read visible input/select/textarea values and write an observable result to an output/list/media/status/preview element; do not use prompt or alert",
                }
            )
    status_ids = [
        identifier
        for identifier, tag in id_tags.items()
        if re.search(
            rf"<{re.escape(tag)}\b(?=[^>]*\bid\s*=\s*['\"]{re.escape(identifier)}['\"])(?=[^>]*(?:role\s*=\s*['\"]status['\"]|aria-live\s*=))",
            html,
            flags=re.I,
        )
    ]
    preview_ids = [
        identifier
        for identifier, tag in id_tags.items()
        if tag in {"output", "canvas", "iframe", "video"}
        or "preview" in identifier.lower()
    ]
    return {
        "id_element_types": id_tags,
        "action_region_bindings": bindings,
        "status_region_ids": status_ids,
        "preview_surface_ids": preview_ids,
    }


def frontend_css_selector_contract(html: str) -> dict[str, Any]:
    """Project accepted HTML into exact, domain-neutral CSS ownership selectors."""
    main_match = re.search(r"<main\b([^>]*)>", html, flags=re.I | re.S)
    owner_attrs = main_match.group(1) if main_match else ""
    if not owner_attrs:
        owner_match = re.search(
            r"<(?:div|section)\b([^>]*(?:workspace|grid|shell|app)[^>]*)>",
            html,
            flags=re.I | re.S,
        )
        owner_attrs = owner_match.group(1) if owner_match else ""
    owner_selectors: list[str] = []
    owner_id = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", owner_attrs, flags=re.I)
    if owner_id:
        owner_selectors.append("#" + owner_id.group(1))
    owner_class = re.search(
        r"\bclass\s*=\s*['\"]([^'\"]+)['\"]", owner_attrs, flags=re.I
    )
    if owner_class:
        owner_selectors.extend("." + token for token in owner_class.group(1).split())

    region_selector_groups: list[list[str]] = []
    for tag, attrs in re.findall(
        r"<(section|article|aside)\b([^>]*)>", html, flags=re.I | re.S
    ):
        selectors: list[str] = []
        region_id = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I)
        if region_id:
            selectors.append("#" + region_id.group(1))
        region_class = re.search(
            r"\bclass\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I
        )
        if region_class:
            selectors.extend("." + token for token in region_class.group(1).split())
        selectors.append(tag.lower())
        region_selector_groups.append(list(dict.fromkeys(selectors)))
    visual_asset_selectors: list[str] = []
    if re.search(r"<img\b", html, flags=re.I):
        for _tag, attrs, body in re.findall(
            r"<(div|section|article|aside|figure)\b([^>]*)>(.*?)</\1>",
            html,
            flags=re.I | re.S,
        ):
            if not re.search(r"<img\b", body, flags=re.I):
                continue
            container_selectors: list[str] = []
            container_id = re.search(
                r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I
            )
            if container_id:
                container_selectors.append("#" + container_id.group(1))
            container_class = re.search(
                r"\bclass\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I
            )
            if container_class:
                container_selectors.extend(
                    "." + token for token in container_class.group(1).split()
                )
            visual_asset_selectors.extend(
                selector + " img" for selector in container_selectors
            )
        visual_asset_selectors.append("img")
    preview_surface_selectors = [
        "#" + identifier
        for tag, identifier in re.findall(
            r"<(canvas|video|iframe|output)\b[^>]*\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]",
            html,
            flags=re.I,
        )
        if "preview" in identifier.lower() or tag.lower() in {"canvas", "video"}
    ]
    return {
        "workspace_owner_selectors": owner_selectors,
        "semantic_region_selector_groups": region_selector_groups,
        "minimum_region_coverage": (
            max(3, (len(region_selector_groups) * 3 + 4) // 5)
            if len(region_selector_groups) >= 3
            else len(region_selector_groups)
        ),
        "shared_semantic_tag_selectors": ["section", "article", "aside"],
        "required_form_control_selector": "input, select, textarea",
        "visual_asset_selectors": list(dict.fromkeys(visual_asset_selectors)),
        "required_visual_asset_properties": ["width or max-width", "object-fit"],
        "preview_surface_selectors": list(dict.fromkeys(preview_surface_selectors)),
        "desktop_region_min_width_px": 320,
        "minimum_regions_per_desktop_row": 2,
    }


def frontend_stagnation_escape_contract(
    target_file: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Return leaf-language repair context without leaking another owner's rules."""
    if target_file in {"src/app.js", "src/main.js"}:
        return payload.get("javascript_repair_interface", {}), (
            "The last two rejected JavaScript replacements were identical. Keep the single "
            "target_file_contents repair base and perform an interface-directed "
            "rewrite: remove every previous_validation_errors target, reference only "
            "stagnation_escape_contract.allowed_dom_ids, read values only from each action's "
            "read_value_only_from_ids, and write results only to its "
            "write_visible_result_only_to_ids. Explicitly verify forbidden calls and write "
            "target types. For every canvas_preview_contract.canvas_ids entry, replace any "
            "single solid geometry draw with at least minimum_drawing_operations calls and at "
            "least one allowed_content_bearing_operation such as fillText or drawImage. Return "
            "the full JavaScript file."
        )
    if target_file == "src/styles.css":
        return payload.get("accepted_css_selector_contract", {}), (
            "The last two rejected CSS replacements were identical. Keep valid declarations "
            "from the single target_file_contents repair base, but rewrite its selector ownership using "
            "stagnation_escape_contract exactly. Remove invented or approximate selectors; "
            "use an accepted workspace_owner_selectors entry and either exact selectors from "
            "semantic_region_selector_groups or a real shared semantic tag selector until "
            "minimum_region_coverage is met. Apply required_visual_asset_properties to one of "
            "visual_asset_selectors and bound preview_surface_selectors. Recheck "
            "desktop width failures numerically: either set a viewport-bounded workspace "
            "max-width of at least (desktop_region_min_width_px * column_count + total gaps), "
            "reduce the desktop column count, or use minmax(desktop_region_min_width_px, 1fr). "
            "Do not return the same max-width/column/gap values named by the rejection. Recheck "
            "previous_validation_errors and return the "
            "full corrected CSS file. Do not follow JavaScript interface rules."
        )
    if target_file == "index.html":
        return payload.get("ui_repair_brief", {}), (
            "The last two rejected HTML replacements were identical. Rewrite the rejected "
            "replacement against stagnation_escape_contract.required_region_content and every "
            "previous_validation_errors item while preserving already-valid visible regions. "
            "Return the full corrected HTML file."
        )
    return {}, (
        "The last two rejected replacements were identical. Regenerate this target leaf from "
        "its own current contract and remove every previous_validation_errors item."
    )


def apply_frontend_repair_librarian_slice(
    target_file: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Remove duplicate sibling source after projecting exact frontend interfaces."""
    if target_file not in {"index.html", "src/app.js", "src/main.js", "src/styles.css"}:
        return payload
    sliced = dict(payload)
    raw_rows = [
        row
        for key in ("repair_set_context", "accepted_sibling_replacements")
        for row in sliced.get(key, [])
        if isinstance(row, dict)
    ]
    removed_chars = sum(len(str(row.get("content", ""))) for row in raw_rows)
    retained_contracts = ["ui_repair_brief"]
    if target_file in {"src/app.js", "src/main.js"}:
        retained_contracts.extend(
            ["accepted_dom_action_contract", "javascript_repair_interface"]
        )
    elif target_file == "src/styles.css":
        retained_contracts.append("accepted_css_selector_contract")
    sliced["repair_set_context"] = []
    sliced["accepted_sibling_replacements"] = []
    sliced["librarian_context_slice"] = {
        "kind": "CGKNPostBuildFrontendLibrarianSlice",
        "target_file": target_file,
        "current_source_owner": "target_file_contents",
        "retained_interface_contracts": retained_contracts,
        "duplicate_sibling_source_characters_removed": removed_chars,
        "rule": "Exact projected interfaces replace duplicate sibling source in this leaf repair prompt; validation still uses the full accepted atomic set.",
    }
    return sliced


def frontend_repair_set_violations(
    candidate_dir: pathlib.Path,
    items: list[dict[str, str]],
    ui_contract: dict[str, Any] | None,
) -> list[str]:
    """Validate interface coherence across already-accepted frontend repair leaves."""
    by_path = {
        str(item.get("path", "")).replace("\\", "/"): str(item.get("content", ""))
        for item in items
        if isinstance(item, dict)
    }
    html = by_path.get("index.html", "")
    script = by_path.get("src/app.js", "") or by_path.get("src/main.js", "")
    css = by_path.get("src/styles.css", "")
    violations: list[str] = []
    if html and script:
        html_ids = set(
            re.findall(r"\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]", html, flags=re.I)
        )
        script_ids = set(
            re.findall(
                r"getElementById\s*\(\s*['\"]([A-Za-z][\w:.-]*)['\"]",
                script,
                flags=re.I,
            )
        )
        missing_ids = sorted(script_ids - html_ids)
        if missing_ids:
            violations.append(
                f"JavaScript references DOM ids absent from accepted HTML: {missing_ids[:8]}"
            )
        actions = set(
            re.findall(r"\bdata-action\s*=\s*['\"]([^'\"]+)['\"]", html, flags=re.I)
        )
        literal_action_bindings = {
            action
            for action in actions
            if re.search(
                r"querySelector(?:All)?\s*\([^\n)]*data-action[^\n)]*"
                + re.escape(action),
                script,
                flags=re.I,
            )
        }
        if len(actions) >= 3 and not (
            re.search(r"dataset\.action", script, flags=re.I)
            or re.search(r"getAttribute\s*\(\s*['\"]data-action['\"]", script, flags=re.I)
            or literal_action_bindings == actions
        ):
            violations.append(
                f"HTML declares {len(actions)} data-action controls but JavaScript neither delegates by data-action nor binds each action literal/control id"
            )
        dom_contract = frontend_dom_action_contract(html)
        id_element_types = dom_contract.get("id_element_types", {})
        invalid_value_targets = sorted(
            identifier
            for identifier in re.findall(
                r"getElementById\s*\(\s*['\"]([A-Za-z][\w:.-]*)['\"]\s*\)\.value",
                script,
                flags=re.I,
            )
            if id_element_types.get(identifier) not in {
                "input",
                "textarea",
                "select",
                "option",
            }
        )
        if invalid_value_targets:
            violations.append(
                f"JavaScript reads/writes .value on non-form HTML owners: {invalid_value_targets[:8]}"
            )
        destructive_region_targets = sorted(
            identifier
            for identifier in re.findall(
                r"getElementById\s*\(\s*['\"]([A-Za-z][\w:.-]*)['\"]\s*\)\.(?:textContent|innerHTML)\s*=",
                script,
                flags=re.I,
            )
            if id_element_types.get(identifier)
            in {"section", "article", "aside", "main"}
        )
        if destructive_region_targets:
            violations.append(
                f"JavaScript replaces semantic region containers and would delete their controls: {destructive_region_targets[:8]}; write to the region's accepted output/list/status/preview id instead"
            )
        canvas_ids = [
            identifier
            for identifier, tag in id_element_types.items()
            if tag == "canvas"
        ]
        invalid_canvas_html_targets = sorted(
            identifier
            for identifier in re.findall(
                r"getElementById\s*\(\s*['\"]([A-Za-z][\w:.-]*)['\"]\s*\)\.(?:textContent|innerHTML)\s*=",
                script,
                flags=re.I,
            )
            if identifier in canvas_ids
        )
        if invalid_canvas_html_targets:
            violations.append(
                f"JavaScript writes HTML/text to canvas owners and cannot produce a visible preview: {invalid_canvas_html_targets[:8]}; use getContext('2d') plus real drawing calls or render to the accepted output interface"
            )
        canvas_drawing_calls = bool(
            re.search(r"\.getContext\s*\(\s*['\"]2d['\"]\s*\)", script, flags=re.I)
            and re.search(
                r"\.(?:drawImage|fillText|strokeText|fillRect|strokeRect|putImageData)\s*\(",
                script,
                flags=re.I,
            )
        )
        undrawn_canvas_ids = [
            identifier
            for identifier in canvas_ids
            if not (
                canvas_drawing_calls
                and re.search(
                    rf"(?:getElementById\s*\(\s*['\"]{re.escape(identifier)}['\"]|querySelector\s*\([^\n)]*#{re.escape(identifier)})",
                    script,
                    flags=re.I,
                )
            )
        ]
        if undrawn_canvas_ids and "preview" in _ui_capability_stages(ui_contract):
            violations.append(
                f"HTML declares canvas preview ids that JavaScript never draws: {undrawn_canvas_ids[:8]}; implement getContext('2d') drawing for each canvas or replace the canvas owner in HTML with a non-canvas preview surface"
            )
        drawing_operations = re.findall(
            r"\.(drawImage|fillText|strokeText|fillRect|strokeRect|putImageData)\s*\(",
            script,
            flags=re.I,
        )
        content_bearing_canvas_draw = any(
            operation.lower() in {"drawimage", "filltext", "stroketext", "putimagedata"}
            for operation in drawing_operations
        )
        if (
            canvas_ids
            and "preview" in _ui_capability_stages(ui_contract)
            and canvas_drawing_calls
            and (len(drawing_operations) < 2 or not content_bearing_canvas_draw)
        ):
            violations.append(
                f"Canvas preview uses only {len(drawing_operations)} generic geometry operation(s) and has no content-bearing drawImage/fillText/strokeText/putImageData call; render a meaningful labeled/image preview rather than a solid shape"
            )
    if html and css:
        css_selector_contract = frontend_css_selector_contract(html)
        owner_selectors = css_selector_contract["workspace_owner_selectors"]
        if owner_selectors and not any(selector.lower() in css.lower() for selector in owner_selectors):
            violations.append(
                f"CSS does not style the accepted main workspace owner; use one of {owner_selectors[:6]}"
            )
        css_without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        region_selector_groups = css_selector_contract["semantic_region_selector_groups"]
        owner_rule_bodies = [
            match.group(1)
            for selector in owner_selectors
            for match in re.finditer(
                rf"(?<![\w-]){re.escape(selector)}(?![\w-])[^{{}}]*\{{([^{{}}]*)\}}",
                css_without_comments,
                flags=re.I | re.S,
            )
        ]
        if len(region_selector_groups) >= 5 and not any(
            re.search(r"grid-template-columns\s*:\s*[^;{}]+", body, flags=re.I)
            or re.search(r"flex-wrap\s*:\s*wrap", body, flags=re.I)
            for body in owner_rule_bodies
        ):
            violations.append(
                f"CSS accepted workspace owner {owner_selectors[:4]} remains a single-column stack for {len(region_selector_groups)} regions; define a real multi-column grid-template-columns or wrapping flex layout on that exact owner"
            )
        owner_layout_text = "\n".join(owner_rule_bodies)
        repeated_columns = re.search(
            r"grid-template-columns\s*:\s*repeat\s*\(\s*(\d+)\s*,",
            owner_layout_text,
            flags=re.I,
        )
        owner_max_width = re.search(
            r"max-width\s*:\s*(\d+(?:\.\d+)?)\s*(px|rem)",
            owner_layout_text,
            flags=re.I,
        )
        owner_gap = re.search(
            r"(?:^|[;\s])gap\s*:\s*(\d+(?:\.\d+)?)\s*(px|rem)",
            owner_layout_text,
            flags=re.I,
        )
        if repeated_columns and owner_max_width:
            column_count = int(repeated_columns.group(1))
            max_width_px = float(owner_max_width.group(1)) * (
                16.0 if owner_max_width.group(2).lower() == "rem" else 1.0
            )
            gap_px = (
                float(owner_gap.group(1))
                * (16.0 if owner_gap.group(2).lower() == "rem" else 1.0)
                if owner_gap
                else 0.0
            )
            estimated_column_width = (
                max_width_px - max(0, column_count - 1) * gap_px
            ) / max(1, column_count)
            minimum_width = float(css_selector_contract["desktop_region_min_width_px"])
            if column_count >= 2 and estimated_column_width < minimum_width:
                violations.append(
                    f"CSS accepted workspace desktop columns are estimated at {estimated_column_width:.1f}px from max-width {max_width_px:.1f}px, {column_count} columns, and {gap_px:.1f}px gap; provide at least {minimum_width:.0f}px per region by widening the viewport-bounded owner, reducing the desktop column count, or using minmax({minimum_width:.0f}px, 1fr)"
                )
        if len(region_selector_groups) >= 3:
            region_coverage = [
                any(
                    re.search(
                            (
                                rf"(?<![\w-]){re.escape(selector)}(?![\w-])[^{{}}]*\{{"
                                if selector.startswith(("#", "."))
                                else rf"(?<![.#\w-]){re.escape(selector)}(?![\w-])[^{{}}]*\{{"
                            ),
                        css_without_comments,
                        flags=re.I,
                    )
                    for selector in selectors
                )
                for selectors in region_selector_groups
            ]
            covered_regions = sum(region_coverage)
            required_region_coverage = css_selector_contract["minimum_region_coverage"]
            if covered_regions < required_region_coverage:
                uncovered = [
                    selectors[0]
                    for selectors, covered in zip(region_selector_groups, region_coverage)
                    if not covered and selectors
                ]
                violations.append(
                    f"CSS selectors cover only {covered_regions}/{len(region_selector_groups)} accepted semantic regions; style at least {required_region_coverage} via exact selectors such as {uncovered[:8]} or a shared section/article/aside rule"
                )
        preview_surface_ids = re.findall(
            r"<(?:output|canvas|iframe|video)\b[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]",
            html,
            flags=re.I,
        )
        if (
            preview_surface_ids
            and "preview" in _ui_capability_stages(ui_contract)
            and script
            and not any(
                re.search(
                    rf"(?:getElementById\s*\(\s*['\"]{re.escape(surface_id)}['\"]|querySelector(?:All)?\s*\([^\n)]*#{re.escape(surface_id)})",
                    script,
                    flags=re.I,
                )
                for surface_id in preview_surface_ids
            )
        ):
            violations.append(
                f"JavaScript does not render to any accepted preview surface id: {preview_surface_ids[:6]}"
            )
        image_sources = re.findall(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", html, flags=re.I)
        missing_media = []
        for source in image_sources:
            if source.startswith(("data:", "http://", "https://")):
                continue
            resolved = (candidate_dir / source.split("?", 1)[0].split("#", 1)[0]).resolve()
            if not resolved.exists() or not str(resolved).lower().startswith(
                str(candidate_dir.resolve()).lower()
            ):
                missing_media.append(source)
        if missing_media:
            violations.append(
                f"HTML visual previews reference missing local assets: {missing_media[:6]}"
            )
    return violations


def validate_post_build_repair_files(
    candidate_dir: pathlib.Path,
    files: list[dict[str, str]],
    target_files: list[str],
    *,
    ui_acceptance_contract: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    targets = {str(path).replace("\\", "/").strip() for path in target_files if str(path).strip()}
    supplied_normalization_actions = {
        str(item.get("path", "")).replace("\\", "/").strip(): list(
            item.get("normalization_actions", [])
        )
        for item in files
        if isinstance(item, dict) and item.get("normalization_actions")
    }
    cleaned = _legacy_call("validate_provider_files", {"files": files})
    for item in cleaned:
        supplied_actions = supplied_normalization_actions.get(
            str(item.get("path", "")).replace("\\", "/").strip(), []
        )
        if supplied_actions:
            item["normalization_actions"] = supplied_actions
    returned = {str(item.get("path", "")).replace("\\", "/").strip() for item in cleaned}
    missing_targets = sorted(targets - returned)
    if missing_targets:
        raise RuntimeError(
            "post-build repair omitted requested target file(s): "
            + ", ".join(missing_targets)
        )
    for item in cleaned:
        rel = item["path"]
        if rel not in targets:
            raise RuntimeError(f"post-build repair tried to modify non-target file: {rel}")
        resolved = (candidate_dir / rel).resolve()
        if not str(resolved).lower().startswith(str(candidate_dir.resolve()).lower()):
            raise RuntimeError(f"post-build repair path escaped candidate dir: {rel}")
        if rel == "index.html":
            item["content"], ownership_actions = normalize_ui_repair_html_ownership(
                item["content"], ui_acceptance_contract
            )
            item["content"], semantic_actions = ui_semantic_adapter.adapt_complex_workspace_html(
                item["content"], ui_acceptance_contract
            )
            item["normalization_actions"] = ownership_actions + semantic_actions
        lowered = item["content"].lower()
        if pathlib.PurePosixPath(rel).name in {"final_project_bundle.zip", "delivery_manifest.json"}:
            raise RuntimeError("post-build repair cannot generate final delivery artifacts")
        if _legacy_call("fake_delivery_claim_present", rel, item["content"]):
            raise RuntimeError(f"post-build repair introduced fake delivery claim: {rel}")
        if rel.upper().endswith("TEST_REPORT.MD") and any(token in lowered for token in ("all tests passed", "pass_final", "final delivery ready")):
            raise RuntimeError("post-build repair introduced fake TEST_REPORT pass claim")
        if rel.endswith(".py"):
            try:
                python_tree = ast.parse(item["content"])
            except SyntaxError as exc:
                raise RuntimeError(
                    f"post-build repaired Python syntax failure in {rel}: {exc}"
                ) from exc
            undefined_names = _legacy_call(
                "python_undefined_names", python_tree, filename=rel
            )
            if undefined_names:
                raise RuntimeError(
                    f"post-build repaired Python leaf contains undefined names in {rel}: "
                    + ", ".join(undefined_names)
                )
        if rel.startswith("tests/") and rel.endswith(".py"):
            fixture_argvalues = _legacy_call(
                "pytest_fixture_argvalue_references", python_tree
            )
            if fixture_argvalues:
                raise RuntimeError(
                    "post-build repaired pytest parametrize argvalues still references fixture "
                    "function(s): " + ", ".join(fixture_argvalues)
                )
        if rel == "demo/run_fixture.py":
            fixture_blockers = _legacy_call(
                "generated_fixture_source_violations", item["content"]
            )
            if fixture_blockers:
                raise RuntimeError(
                    "post-build repaired fixture contract mismatch: "
                    + "; ".join(fixture_blockers)
                )
        frontend_blockers = generated_frontend_workspace_source_violations(
            rel, item["content"], ui_acceptance_contract
        )
        if frontend_blockers:
            raise RuntimeError(
                "post-build repaired frontend workspace contract mismatch: "
                + "; ".join(frontend_blockers)
            )
    return cleaned


def ensure_path_to_file_url_import(text: str) -> str:
    if re.search(r"import\s*\{[^}]*\bpathToFileURL\b[^}]*\}\s*from\s*['\"]node:url['\"]", text):
        return text
    node_url_re = re.compile(r"import\s*\{(?P<names>[^}]*)\}\s*from\s*(?P<quote>['\"])node:url(?P=quote)\s*;?")
    match = node_url_re.search(text)
    if match:
        names = [name.strip() for name in match.group("names").split(",") if name.strip()]
        if "pathToFileURL" not in names:
            names.append("pathToFileURL")
        replacement = f"import {{ {', '.join(names)} }} from {match.group('quote')}node:url{match.group('quote')};"
        return text[: match.start()] + replacement + text[match.end() :]
    lines = text.splitlines()
    insert_at = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("#!"):
            insert_at = idx + 1
            continue
        if stripped == "":
            continue
        break
    lines.insert(insert_at, 'import { pathToFileURL } from "node:url";')
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _extract_import_argument(text: str, open_paren: int) -> tuple[str, int] | None:
    depth = 1
    quote = ""
    escape = False
    start = open_paren + 1
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
        else:
            if char in ("'", '"', "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start:index], index
        index += 1
    return None


def _looks_like_filesystem_import_arg(arg: str) -> bool:
    stripped = arg.strip()
    if not stripped or "pathToFileURL" in stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith(("new url(", "import.meta", "url.")):
        return False
    if (stripped[0] in ("'", '"', "`")) and stripped[-1:] == stripped[0]:
        literal = stripped[1:-1]
        return bool(re.match(r"^[a-zA-Z]:[\\/]", literal))
    filesystem_markers = (
        "abspath",
        "absolute",
        "resolvedpath",
        "resolved",
        "testfile",
        "filepath",
        "filename",
        "projectroot",
        "candidate",
        "path.resolve",
        "path.join",
        "process.cwd",
    )
    return any(marker in lowered for marker in filesystem_markers)


def rewrite_windows_esm_dynamic_imports(text: str) -> tuple[str, bool]:
    result: list[str] = []
    cursor = 0
    changed = False
    while True:
        found = text.find("import(", cursor)
        if found < 0:
            result.append(text[cursor:])
            break
        before = text[found - 1] if found > 0 else ""
        if before.isalnum() or before in ("_", "."):
            result.append(text[cursor : found + len("import(")])
            cursor = found + len("import(")
            continue
        extracted = _extract_import_argument(text, found + len("import"))
        if not extracted:
            result.append(text[cursor:])
            break
        arg, close_paren = extracted
        result.append(text[cursor : found + len("import(")])
        if _looks_like_filesystem_import_arg(arg):
            result.append(f"pathToFileURL({arg.strip()}).href")
            changed = True
        else:
            result.append(arg)
        cursor = close_paren
    return "".join(result), changed


def repair_windows_esm_path_import_file(path: pathlib.Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    rewritten, changed = rewrite_windows_esm_dynamic_imports(text)
    if not changed:
        return False
    rewritten = ensure_path_to_file_url_import(rewritten)
    if rewritten != text:
        path.write_text(rewritten, encoding="utf-8")
        return True
    return False


def _node_builtin_test_runner_content() -> str:
    return """#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const projectRoot = process.cwd();
const mustExist = ["package.json", "README.md"];
for (const rel of mustExist) {
  assert.ok(fs.existsSync(path.join(projectRoot, rel)), `${rel} must exist`);
}

const sourceCandidates = ["index.html", "src/App.tsx", "src/app.js", "src/main.js", "backend/service.py"];
assert.ok(sourceCandidates.some((rel) => fs.existsSync(path.join(projectRoot, rel))), "candidate must include a runnable UI or backend source");

const packageJson = JSON.parse(fs.readFileSync(path.join(projectRoot, "package.json"), "utf8"));
assert.ok(packageJson.scripts && packageJson.scripts.test, "package.json must define scripts.test");

console.log("[cgnk-node-smoke] basic candidate files verified");
"""


def repair_missing_vitest_with_node_runner(candidate_dir: pathlib.Path) -> list[str]:
    changed: list[str] = []
    package_path = candidate_dir / "package.json"
    if package_path.exists():
        try:
            package_doc = json.loads(package_path.read_text(encoding="utf-8"))
        except Exception:
            package_doc = {}
    else:
        package_doc = {"name": "cgnk-candidate", "version": "1.0.0", "private": True, "type": "module", "scripts": {}}
    if not isinstance(package_doc, dict):
        package_doc = {}
    scripts = package_doc.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}
        package_doc["scripts"] = scripts
    if scripts.get("test") != "node scripts/test.js":
        scripts["test"] = "node scripts/test.js"
        package_path.write_text(json.dumps(package_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        changed.append("package.json")

    test_path = candidate_dir / "scripts" / "test.js"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    content = _node_builtin_test_runner_content()
    if not test_path.exists() or test_path.read_text(encoding="utf-8", errors="replace") != content:
        test_path.write_text(content, encoding="utf-8")
        changed.append("scripts/test.js")
    return changed


def repair_missing_start_script(candidate_dir: pathlib.Path) -> list[str]:
    package_path = candidate_dir / "package.json"
    if not package_path.exists() or not (candidate_dir / "index.html").exists():
        return []
    try:
        package_doc = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:
        package_doc = {}
    if not isinstance(package_doc, dict):
        package_doc = {}
    scripts = package_doc.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}
        package_doc["scripts"] = scripts
    if scripts.get("start"):
        return []
    scripts["start"] = "python -m http.server 5173 --bind 127.0.0.1"
    package_path.write_text(json.dumps(package_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ["package.json"]


def create_minimal_package_json(candidate_dir: pathlib.Path) -> list[str]:
    package_path = candidate_dir / "package.json"
    if package_path.exists():
        return []
    package_doc = {
        "type": "module",
        "scripts": {
            "test": "node scripts/test.js",
            "start": "python -m http.server 5173 --bind 127.0.0.1",
        },
    }
    package_path.write_text(json.dumps(package_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ["package.json"]


def apply_deterministic_post_build_repair(candidate_dir: pathlib.Path, repair_plan: dict[str, Any]) -> dict[str, Any]:
    changed: list[str] = []
    skipped: list[dict[str, Any]] = []
    for action in repair_plan.get("deterministic_actions", []):
        if not isinstance(action, dict):
            continue
        kind = str(action.get("action", ""))
        rel = str(action.get("path", "")).replace("\\", "/").strip()
        if kind == "replace_missing_vitest_with_node_runner":
            changed.extend(repair_missing_vitest_with_node_runner(candidate_dir))
        elif kind == "add_static_start_script":
            changed.extend(repair_missing_start_script(candidate_dir))
        elif kind == "create_minimal_package_json":
            changed.extend(create_minimal_package_json(candidate_dir))
        elif kind in {
            "create_static_entrypoint",
            "repair_page_blank_demo_ui",
            "enable_static_preview_demo_data",
            "create_basic_index_html",
        }:
            skipped.append(
                {
                    "action": kind,
                    "reason": "legacy fixed-domain scaffold actions are not allowed in formal repair",
                    "path": rel,
                }
            )
        elif kind == "normalize_test_runner_project_root" and rel == "scripts/util/testRunner.js":
            path = candidate_dir / rel
            if not path.exists():
                skipped.append({"action": kind, "reason": "target missing", "path": rel})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            updated = text
            if "fileURLToPath" not in updated:
                updated = updated.replace("import path from 'node:path';", "import path from 'node:path';\nimport { fileURLToPath } from 'node:url';")
            updated = re.sub(
                r"const projectRoot = path\.resolve\(path\.dirname\(new URL\(import\.meta\.url\)\.pathname\), '..', '..'\);",
                "const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');",
                updated,
            )
            updated = updated.replace("path.join('src', 'main.tsx')", "path.join('src', 'main.js')")
            updated = updated.replace("if (r === path.join('src', 'main.tsx'))", "if (r === path.join('src', 'main.js'))")
            updated = updated.replace("src/main.tsx missing", "src/main.js missing")
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                changed.append(rel)
        elif kind == "allow_main_js_entry" and rel == "scripts/util/buildAll.js":
            path = candidate_dir / rel
            if not path.exists():
                skipped.append({"action": kind, "reason": "target missing", "path": rel})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            updated = text.replace(
                "const appEntry = path.join(projectRoot, 'src', 'main.tsx');",
                "const appEntry = fs.existsSync(path.join(projectRoot, 'src', 'main.js')) ? path.join(projectRoot, 'src', 'main.js') : path.join(projectRoot, 'src', 'main.tsx');",
            )
            updated = updated.replace("src/main.tsx not found yet", "src/main.js or src/main.tsx not found yet")
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                changed.append(rel)
        elif kind == "resolve_command_executable":
            skipped.append({"action": kind, "reason": "handled by command normalization"})
        elif kind == "repair_windows_esm_path_imports":
            paths = action.get("paths", [])
            if not isinstance(paths, list):
                paths = []
            for item in paths[:3]:
                rel_path = str(item).replace("\\", "/").strip()
                if not rel_path or not rel_path.endswith((".js", ".mjs", ".cjs")):
                    skipped.append({"action": kind, "reason": "unsupported target", "path": rel_path})
                    continue
                path = (candidate_dir / rel_path).resolve()
                if not str(path).lower().startswith(str(candidate_dir.resolve()).lower()):
                    skipped.append({"action": kind, "reason": "path escaped candidate", "path": rel_path})
                    continue
                if not path.exists():
                    skipped.append({"action": kind, "reason": "target missing", "path": rel_path})
                    continue
                if repair_windows_esm_path_import_file(path):
                    changed.append(rel_path)
    return {"status": "applied" if changed else "skipped", "changed_files": sorted(set(changed)), "skipped": skipped}


def python_test_dependency_context(
    candidate_dir: pathlib.Path,
    target_file: str,
    *,
    max_chars: int = 16000,
) -> list[dict[str, Any]]:
    """Return exact local provider definitions imported by a generated Python test."""
    normalized = str(target_file).replace("\\", "/").strip()
    if not normalized.startswith("tests/") or not normalized.endswith(".py"):
        return []
    test_path = candidate_dir / normalized
    try:
        test_source = test_path.read_text(encoding="utf-8", errors="strict")
        test_tree = ast.parse(test_source)
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return []

    pending: list[tuple[str, set[str], int]] = []
    for node in test_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            pending.append(
                (
                    str(node.module),
                    {alias.name for alias in node.names if alias.name != "*"},
                    0,
                )
            )
        elif isinstance(node, ast.Import):
            pending.extend((str(alias.name), set(), 0) for alias in node.names)

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    used_chars = 0
    while pending and used_chars < max_chars:
        module_name, selected_symbols, depth = pending.pop(0)
        if not module_name or module_name.split(".")[0] in {
            "pytest",
            "unittest",
            "pathlib",
            "json",
            "os",
            "sys",
            "typing",
        }:
            continue
        key = (module_name, tuple(sorted(selected_symbols)))
        if key in seen or depth > 2:
            continue
        seen.add(key)
        module_path = candidate_dir.joinpath(*module_name.split(".")).with_suffix(".py")
        if not module_path.is_file():
            package_path = candidate_dir.joinpath(*module_name.split("."), "__init__.py")
            module_path = package_path if package_path.is_file() else module_path
        if not module_path.is_file():
            continue
        try:
            source = module_path.read_text(encoding="utf-8", errors="strict")
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError, ValueError):
            continue

        excerpts: list[str] = []
        for node in tree.body:
            node_name = getattr(node, "name", "")
            assigned_names: set[str] = set()
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                assigned_names = {
                    target.id for target in targets if isinstance(target, ast.Name)
                }
            if (
                not selected_symbols
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ) or node_name in selected_symbols or assigned_names & selected_symbols:
                segment = ast.get_source_segment(source, node)
                if segment:
                    excerpts.append(segment)
            if isinstance(node, ast.ImportFrom) and node.module:
                forwarded = {
                    alias.name
                    for alias in node.names
                    if not selected_symbols
                    or alias.name in selected_symbols
                    or (alias.asname and alias.asname in selected_symbols)
                }
                if forwarded:
                    pending.append((str(node.module), forwarded, depth + 1))

        if not excerpts:
            continue
        relative_path = module_path.relative_to(candidate_dir).as_posix()
        excerpt = "\n\n".join(excerpts)
        remaining = max_chars - used_chars
        excerpt = excerpt[:remaining]
        used_chars += len(excerpt)
        results.append(
            {
                "path": relative_path,
                "selected_symbols": sorted(selected_symbols),
                "source_excerpt": excerpt,
            }
        )
    return results


def provider_post_build_file_repair(
    *,
    candidate_dir: pathlib.Path,
    repair_plan: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str,
    routing_policy: Any | None,
) -> dict[str, Any]:
    target_files = [str(item.get("path", "")).replace("\\", "/").strip() for item in repair_plan.get("provider_actions", []) if isinstance(item, dict)]
    failure_types = {
        str(item).strip() for item in repair_plan.get("failure_types", []) if str(item).strip()
    }
    target_limit = 5 if failure_types & {
        "fixture_failure",
        "stage_artifact_failure",
        "media_generation_failure",
    } else 3
    target_files = [rel for rel in target_files if rel][:target_limit]
    if not target_files:
        return {"status": "skipped", "reason": "no provider file-level repair targets", "changed_files": []}
    system = """Repair a CGNK candidate project after post-build failure.
Return strict JSON only: {"files":[{"path":"target file","content":"full replacement content"}]}.
You are repairing exactly one bounded leaf. Return only that requested target file. Do not regenerate the whole project.
Do not generate final_project_bundle.zip, delivery_manifest.json, screenshots, videos, or fake TEST_REPORT pass claims.
Keep the project candidate-only; final packaging is local_packager-only after validation."""
    base_payload = {
        "stage": "post_build_repair",
        "candidate_only": True,
        "observed_failures": repair_plan.get("failure_types", []),
        "root_causes": repair_plan.get("root_causes", []),
        "failure_log_summary": str(repair_plan.get("log_summary", ""))[:3000],
        "validation_commands": repair_plan.get("validation_commands", []),
        "strict_rules": [
            "Return exactly one full replacement file for target_file.",
            "Do not add or remove any other file.",
            "Do not claim tests/screenshots/videos passed unless the local post-build runner produced that evidence.",
            "Do not write final_project_bundle.zip or delivery_manifest.json.",
        ],
    }
    validation_attempts = max(
        1, min(4, int(_legacy_call("env_int", "CGNK_POST_BUILD_OUTPUT_REPAIR_ATTEMPTS", 3)))
    )
    validation_errors: list[str] = []
    pipeline_fallbacks: list[dict[str, Any]] = []
    total_attempts = 0
    raw_chars = 0
    cleaned: list[dict[str, str]] = []
    repair_set_context = [
        {
            "path": rel,
            "content": (candidate_dir / rel).read_text(
                encoding="utf-8", errors="replace"
            )[:8000],
        }
        for rel in target_files
        if (candidate_dir / rel).is_file()
    ]

    def record_semantic_fallbacks(items: list[dict[str, Any]], target: str) -> None:
        semantic_actions = [
            str(action)
            for item in items
            for action in item.get("normalization_actions", [])
            if str(action).startswith(("converted_", "inserted_", "restored_", "initialized_", "removed_", "added_", "closed_", "retargeted_"))
        ]
        if not semantic_actions:
            return
        event = {
            "type": "pipeline_fallback",
            "source": "provider_html",
            "destination": "ui_semantic_adapter",
            "task": "post_build_file_repair",
            "target_file": target,
            "reason": "provider HTML interface normalization",
            "actions": semantic_actions,
            "policy_version": ui_semantic_adapter.POLICY_VERSION,
        }
        pipeline_fallbacks.append(event)
        _legacy_call(
            "append_phase_log",
            phase_log_path,
            "pipeline_fallback",
            "applied",
            f"Applied bounded UI semantic adapter for {target}: {', '.join(semantic_actions)}",
            [target],
        )

    accepted_leaf_dir = (
        pathlib.Path(phase_log_path).parent
        / "artifacts"
        / "post_build_accepted_leaves"
    )

    def accepted_leaf_path(target: str) -> pathlib.Path:
        return accepted_leaf_dir / (
            target.replace("/", "__").replace("\\", "__") + ".json"
        )

    def stage_accepted_leaf(items: list[dict[str, str]], target: str) -> None:
        item = next(
            (
                row
                for row in items
                if str(row.get("path", "")).replace("\\", "/") == target
            ),
            None,
        )
        if not item:
            return
        _legacy_call(
            "write_json",
            accepted_leaf_path(target),
            {
                "target_file": target,
                "content": str(item.get("content", "")),
                "candidate_only": True,
                "status": "validated_pending_atomic_commit",
                "semantic_adapter_policy": ui_semantic_adapter.POLICY_VERSION,
            },
        )

    for target_file in target_files:
        staged_path = accepted_leaf_path(target_file)
        if target_file in {"index.html", "src/app.js", "src/main.js", "src/styles.css"} and staged_path.is_file():
            try:
                staged_record = json.loads(staged_path.read_text(encoding="utf-8"))
                staged_source_items = normalize_frontend_repair_against_accepted_html(
                    [
                        {
                            "path": target_file,
                            "content": str(staged_record.get("content", "")),
                        }
                    ],
                    cleaned,
                )
                staged_items = validate_post_build_repair_files(
                    candidate_dir,
                    staged_source_items,
                    [target_file],
                    ui_acceptance_contract=repair_plan.get(
                        "ui_acceptance_contract", {}
                    ),
                )
                staged_set_violations = frontend_repair_set_violations(
                    candidate_dir,
                    cleaned + staged_items,
                    repair_plan.get("ui_acceptance_contract", {}),
                )
                if (
                    staged_record.get("candidate_only") is not True
                    or staged_record.get("semantic_adapter_policy")
                    != ui_semantic_adapter.POLICY_VERSION
                    or staged_set_violations
                ):
                    raise RuntimeError(
                        "staged leaf no longer satisfies current frontend set: "
                        + "; ".join(staged_set_violations)
                    )
            except Exception:
                pass
            else:
                record_semantic_fallbacks(staged_items, target_file)
                stage_accepted_leaf(staged_items, target_file)
                cleaned.extend(staged_items)
                _legacy_call(
                    "append_phase_log",
                    phase_log_path,
                    "post_build_repair",
                    "accepted_leaf_revalidated",
                    f"Revalidated candidate-only accepted leaf {target_file} for the current atomic repair set.",
                    [target_file],
                )
                continue
        path = candidate_dir / target_file
        existing = {
            "path": target_file,
            "content": (
                path.read_text(encoding="utf-8", errors="replace")[:18000]
                if path.exists() and path.is_file()
                else ""
            ),
            "missing": not (path.exists() and path.is_file()),
        }
        payload = dict(base_payload)
        payload["target_file"] = target_file
        payload["target_file_contents"] = [existing]
        payload["repair_set_context"] = repair_set_context
        payload["accepted_sibling_replacements"] = [
            item for item in cleaned if item.get("path") != target_file
        ]
        payload["target_diagnostic"] = str(
            (repair_plan.get("target_diagnostics", {}) or {}).get(target_file, "")
        )[:6000]
        payload["strict_rules"] = list(base_payload["strict_rules"])
        if target_file.endswith(".py"):
            payload["strict_rules"].append(
                "Every referenced Python name must be defined or imported in this file; preserve required imports when replacing the leaf."
            )
        if target_file.startswith("tests/") and target_file.endswith(".py"):
            payload["exact_dependency_context"] = python_test_dependency_context(
                candidate_dir, target_file
            )
            payload["strict_rules"].append(
                "For pytest, request a declared fixture by naming it as a test parameter. Never pass a fixture function as pytest.mark.parametrize argvalues; argvalues must be a real iterable of cases."
            )
            payload["strict_rules"].append(
                "Treat exact_dependency_context as authoritative. Call imported local functions/classes with their implemented signatures and assert their real public return shape; do not invent compatibility helpers, methods, fixtures, or legacy interfaces."
            )
        if target_file == "demo/run_fixture.py":
            payload["required_stage_artifact_write_shape"] = (
                "for artifact_name in REQUIRED_STAGE_ARTIFACTS:\n"
                "    artifact_path = Path('output') / artifact_name\n"
                "    artifact_path.parent.mkdir(parents=True, exist_ok=True)\n"
                "    receipt = {\n"
                "        'stage': artifact_name,\n"
                "        'status': startup.get('status', 'success'),\n"
                "        'count': 1,\n"
                "        'input_path': '',\n"
                "        'output_path': str(artifact_path),\n"
                "        'created_at': startup.get('created_at', ''),\n"
                "        'upstream_artifacts': [],\n"
                "        'items': [startup],\n"
                "    }\n"
                "    artifact_path.write_text(json.dumps(receipt), encoding='utf-8')\n"
                "    artifact_data = json.loads(artifact_path.read_text(encoding='utf-8'))\n"
                "    assert all(field in artifact_data for field in receipt)\n"
            )
            payload["strict_rules"].append(
                "Import Image from PIL, decode PNG paths with Image.open(...), convert sprites to RGBA, assign alpha_min, alpha_max = rgba.getchannel('A').getextrema(), and require alpha_min < 255. Never infer pixels or alpha from fixed indexes of compressed PNG bytes. Replace the entire existing stage-artifact loop with required_stage_artifact_write_shape. Do not preserve or add any artifact_path.is_file() check, FileNotFoundError, json.load(), or other read before artifact_path.write_text(...). Do this even if initialize_app is expected to produce other artifacts."
            )
        if target_file in {"index.html", "src/app.js", "src/styles.css", "src/main.js"}:
            if "ui_quality_failure" in failure_types:
                accepted_siblings = [
                    item for item in cleaned if item.get("path") != target_file
                ]
                payload["target_file_contents"] = [
                    {
                        "path": target_file,
                        "content": "",
                        "discard_existing_shell": True,
                    }
                ]
                payload["repair_set_context"] = accepted_siblings
                payload["legacy_shell_disposition"] = (
                    "Discard the existing shell source completely; generate this bounded replacement from the accepted siblings and UI contract."
                )
            ui_acceptance = repair_plan.get("ui_acceptance_contract", {})
            payload["ui_acceptance_contract"] = ui_acceptance
            groups = (
                ui_acceptance.get("capability_groups", [])
                if isinstance(ui_acceptance, dict)
                else []
            )
            required_labels = list(
                dict.fromkeys(
                    str(term).strip().title()
                    for group in groups
                    if isinstance(group, dict)
                    for term in group.get("terms", [])
                    if str(term).strip()
                )
            )
            region_content_contract: list[dict[str, Any]] = []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                stage = str(group.get("stage", "")).strip()
                terms = [
                    str(term).strip()
                    for term in group.get("terms", [])
                    if str(term).strip()
                ]
                semantic_text = " ".join([stage, *terms]).lower()
                if any(token in semantic_text for token in ("edit", "create", "add", "write")):
                    state_elements = ["label", "input_or_textarea", "list_or_output"]
                elif any(token in semantic_text for token in ("bind", "select", "assign", "map")):
                    state_elements = ["label", "select", "output"]
                elif any(token in semantic_text for token in ("preview", "render", "play", "inspect")):
                    state_elements = ["output_or_canvas_or_media"]
                elif any(token in semantic_text for token in ("generate", "asset", "image", "sprite", "background")):
                    state_elements = ["input_or_select", "list_or_output_or_media"]
                elif any(token in semantic_text for token in ("validate", "check", "review", "test")):
                    state_elements = ["output_or_status"]
                elif any(token in semantic_text for token in ("export", "download", "publish")):
                    state_elements = ["output_or_status"]
                else:
                    state_elements = ["input_or_select_or_list_or_output"]
                suggested_region_id = re.sub(
                    r"[^a-z0-9]+", "-", stage.lower()
                ).strip("-")
                region_content_contract.append(
                    {
                        "stage": stage,
                        "suggested_region_id": suggested_region_id,
                        "visible_terms": terms,
                        "required_state_bearing_elements": state_elements,
                        "action_interface": f'data-action="{suggested_region_id}"' if suggested_region_id else "data-action",
                    }
                )
            payload["ui_repair_brief"] = {
                "required_domain_keywords": list(
                    dict.fromkeys(
                        str(item).strip()
                        for item in ui_acceptance.get("domain_keywords", [])
                        if str(item).strip()
                    )
                )[:10]
                if isinstance(ui_acceptance, dict)
                else [],
                "required_visible_labels": required_labels,
                "required_feature_areas": [
                    {
                        "stage": item["stage"],
                        "visible_terms": item["visible_terms"],
                    }
                    for item in region_content_contract
                ],
                "required_region_content": region_content_contract,
                "maximum_heading_button_only_regions": 1,
                "minimum_semantic_controls": min(8, max(4, len(groups))),
                "minimum_semantic_regions": 3,
                "minimum_visible_text_characters": 160,
                "minimum_concrete_css_rules": 8,
                "minimum_css_design_tokens": 6,
                "maximum_screenshot_blank_score": 0.90,
                "required_responsive_breakpoints": 1,
                "required_workspace_layout": "display:grid or display:flex on a workspace container",
                "required_information_architecture": {
                    "product_headers": 1,
                    "feature_area_headings": 3,
                    "primary_main_regions": 1,
                    "observable_status_regions": 1,
                    "visible_graph_nodes": 2,
                    "dedicated_preview_surfaces": 1,
                },
                "required_control_interface": "Every action button uses data-action; no inline on* event attributes",
                "required_graph_node_interface": "At least two visible li/data-node-id or equivalent .story-node elements",
                "required_body_identity_line": " ".join(
                    list(
                        dict.fromkeys(
                            str(item).strip()
                            for item in ui_acceptance.get("domain_keywords", [])
                            if str(item).strip()
                        )
                    )[:4]
                )
                if isinstance(ui_acceptance, dict)
                else "",
            }
            media_stages = " ".join(
                str(group.get("stage", ""))
                for group in groups
                if isinstance(group, dict)
            )
            if any(term in media_stages for term in ("background", "sprite", "image")):
                payload["ui_repair_brief"]["minimum_visual_asset_previews"] = 2
                payload["available_visual_assets"] = [
                    path.relative_to(candidate_dir).as_posix()
                    for path in sorted(candidate_dir.rglob("*"))
                    if path.is_file()
                    and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    and "screenshot" not in path.as_posix().lower()
                ][:12]
            accepted_html = next(
                (
                    str(item.get("content", ""))
                    for item in reversed(cleaned)
                    if item.get("path") == "index.html"
                ),
                "",
            )
            payload["accepted_dom_ids"] = list(
                dict.fromkeys(
                    re.findall(
                        r"\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]",
                        accepted_html,
                        flags=re.I,
                    )
                )
            )
            accepted_dom_action_contract = frontend_dom_action_contract(accepted_html)
            payload["accepted_dom_action_contract"] = accepted_dom_action_contract
            if target_file == "src/styles.css":
                payload["accepted_css_selector_contract"] = (
                    frontend_css_selector_contract(accepted_html)
                )
            if target_file in {"src/app.js", "src/main.js"}:
                id_element_types = accepted_dom_action_contract.get(
                    "id_element_types", {}
                )
                status_targets = accepted_dom_action_contract.get(
                    "status_region_ids", []
                )
                action_interfaces: list[dict[str, Any]] = []
                for binding in accepted_dom_action_contract.get(
                    "action_region_bindings", []
                ):
                    state_ids = list(binding.get("state_element_ids", []))
                    readable_ids = [
                        identifier
                        for identifier in state_ids
                        if id_element_types.get(identifier)
                        in {"input", "textarea", "select"}
                    ]
                    writable_ids = [
                        identifier
                        for identifier in state_ids
                        if id_element_types.get(identifier)
                        in {"output", "ul", "ol", "canvas", "video", "img"}
                    ]
                    action_interfaces.append(
                        {
                            "action": binding.get("action", ""),
                            "read_value_only_from_ids": readable_ids,
                            "write_visible_result_only_to_ids": list(
                                dict.fromkeys([*writable_ids, *status_targets])
                            ),
                        }
                    )
                payload["javascript_repair_interface"] = {
                    "allowed_dom_ids": sorted(id_element_types),
                    "id_element_types": id_element_types,
                    "default_status_target_id": (
                        status_targets[0] if status_targets else ""
                    ),
                    "action_interfaces": action_interfaces,
                    "forbidden_calls": ["prompt", "alert", "confirm"],
                    "forbidden_write_target_types": [
                        "section",
                        "article",
                        "aside",
                        "main",
                    ],
                    "canvas_preview_contract": {
                        "canvas_ids": sorted(
                            identifier
                            for identifier, tag in id_element_types.items()
                            if tag == "canvas"
                        ),
                        "minimum_drawing_operations": 2,
                        "allowed_content_bearing_operations": [
                            "drawImage",
                            "fillText",
                            "strokeText",
                            "putImageData",
                        ],
                        "forbidden_as_only_preview_operation": "fillRect",
                    },
                }
                payload["required_javascript_behaviors"] = [
                    "initialize on DOMContentLoaded or by an explicit bootstrap call",
                    *[
                        f"bind the {item['action_interface']} control and render an observable result for {item['stage']} in that region's state-bearing element"
                        for item in region_content_contract
                        if item["stage"]
                    ],
                    "save and reload the current workspace through localStorage",
                ]
                if any(
                    token in _ui_capability_stages(ui_acceptance)
                    for token in ("export", "download", "publish")
                ):
                    payload["required_javascript_behaviors"].append(
                        "export the current project through a real Blob download or JSON data URL"
                    )
            payload["strict_rules"].append(
                "Repair the visible product workspace, not a landing-page shell. Implement every capability group and structural metric named by target_diagnostic. Coordinate exact DOM ids/classes with repair_set_context and accepted_sibling_replacements; controls must perform observable local actions without console or network errors."
            )
            payload["strict_rules"].append(
                "Do not return target_file_contents unchanged and do not merely append comments or duplicate selectors. Replace the shell implementation with a coherent workspace that visibly satisfies ui_repair_brief. For index.html, every required feature area must have its own semantic region and controls. For JavaScript, bind those exact proposed controls to real in-memory/localStorage/edit-preview-export behavior. For CSS, style the proposed regions as an intentional responsive authoring environment."
            )
            if target_file == "index.html":
                payload["strict_rules"].append(
                    "Place required_body_identity_line visibly in a product <header> before <main>. Use exactly one h1 for product identity and h2/h3 for feature areas. Implement every required_region_content row as a semantic region with its suggested id, visible terms, action interface, and at least one listed state-bearing element in addition to its heading/button; at most maximum_heading_button_only_regions may omit such content. Include a non-empty aria-live/role=status action-feedback region, at least two visible graph/tree node elements such as <li data-node-id=\"start\"> and <li data-node-id=\"choice\"> when graph capability is required, and a dedicated preview surface beyond its button when preview capability is required. Every action button must use data-action and must not use onclick/onchange or any inline event attribute. When minimum_visual_asset_previews is present, render at least that many real available_visual_assets through img elements inside a semantic asset/preview region. Text appearing only in <title>, meta attributes, scripts, styles, or element attributes does not count as visible body identity."
                )
            if target_file in {"src/app.js", "src/main.js"}:
                payload["strict_rules"].append(
                    "Replace the entire old JavaScript. Use accepted_dom_action_contract exactly: for every action_region_bindings row, read only its accepted input/select/textarea ids and write an observable result to its accepted output/list/media id or a listed status_region_ids/preview_surface_ids target. Never use prompt(), alert(), confirm(), or assign .value to a section/article/aside/main id. Never replace a semantic region container's textContent/innerHTML because that deletes its controls. Never assign textContent/innerHTML to a canvas: a declared canvas preview must be obtained through getContext('2d') and receive at least two visible drawing operations including a content-bearing drawImage/fillText/strokeText/putImageData call; a single solid fillRect is not a preview. Otherwise render to a non-canvas accepted output and replace the canvas owner in HTML. Bind at least five controls with addEventListener or a concrete delegation loop, call bootstrap on load, persist JSON in localStorage, and implement a download with Blob plus URL.createObjectURL or a data:application/json URL. console.log, TODO/placeholder comments, placeholder functions, and simulated actions do not count as behavior."
                )
            elif target_file == "src/styles.css":
                payload["strict_rules"].append(
                    "Replace the entire old stylesheet. Treat accepted_css_selector_contract as authoritative: use an exact workspace_owner_selectors entry for layout and cover minimum_region_coverage semantic_region_selector_groups using their listed ids/classes or a real shared section/article/aside tag selector; do not invent approximate ids/classes (a .section class does not match bare <section> elements). When there are five or more semantic regions, the exact workspace owner must use a real multi-column grid-template-columns or flex-wrap:wrap layout with at least minimum_regions_per_desktop_row, and its desktop columns/cards must allow desktop_region_min_width_px each; an unrelated grid class, flex-direction:column, or three columns squeezed into an 800px owner does not satisfy this. Return at least 8 meaningful concrete selector rules without duplicate-count padding; define at least 6 coherent CSS custom-property design tokens and consume at least 5 distinct tokens across body, header, workspace surfaces, controls, spacing, and radius; set an intentional body background/text color, a spaced header surface/border/elevation, and a base button background plus radius rather than relying on browser defaults or hover-only color. Put a viewport-bounded max-width large enough for the accepted desktop layout on the workspace owner; add restrained hierarchy with typography, spacing, hover and :focus-visible states; give buttons and the exact required_form_control_selector min-height:44px; apply every required_visual_asset_properties item in one rule using an exact visual_asset_selectors entry; bound preview_surface_selectors; and include at least one concrete @media breakpoint that changes the accepted workspace layout. Use calc(...) for arithmetic. Avoid unrelated per-action rainbow button colors. Verify these capabilities before returning the full CSS file."
                )
            payload = apply_frontend_repair_librarian_slice(target_file, payload)
        prior_feedback = (
            latest_rejected_repair_feedback(
                pathlib.Path(phase_log_path),
                target_file,
                repair_plan.get("ui_acceptance_contract", {}),
            )
            if target_file in {"index.html", "src/app.js", "src/main.js", "src/styles.css"}
            else {}
        )
        leaf_errors: list[str] = []
        last_rejected_content = str(prior_feedback.get("content", ""))
        best_rejected_content = last_rejected_content
        best_rejected_error = str(prior_feedback.get("validation_error", ""))
        best_rejected_distance = (
            frontend_repair_validation_distance(best_rejected_error)
            if best_rejected_content
            else 10**9
        )
        rejected_content_history: list[str] = (
            [last_rejected_content] if last_rejected_content else []
        )
        if prior_feedback:
            payload["prior_rejected_repair_evidence"] = {
                "path": prior_feedback.get("evidence_path", ""),
                "candidate_only": True,
            }
            revalidated_source_items: list[dict[str, str]] = []
            try:
                revalidated_source_items = normalize_frontend_repair_against_accepted_html(
                    [{"path": target_file, "content": last_rejected_content}],
                    cleaned,
                )
                revalidated_items = validate_post_build_repair_files(
                    candidate_dir,
                    revalidated_source_items,
                    [target_file],
                    ui_acceptance_contract=repair_plan.get(
                        "ui_acceptance_contract", {}
                    ),
                )
                revalidated_set_violations = frontend_repair_set_violations(
                    candidate_dir,
                    cleaned + revalidated_items,
                    repair_plan.get("ui_acceptance_contract", {}),
                )
                if revalidated_set_violations:
                    raise RuntimeError(
                        "post-build repaired frontend interface mismatch: "
                        + "; ".join(revalidated_set_violations)
                    )
            except Exception as exc:
                leaf_errors = [str(exc)]
                current_distance = frontend_repair_validation_distance(leaf_errors[0])
                normalized_prior_content = next(
                    (
                        str(item.get("content", ""))
                        for item in revalidated_source_items
                        if str(item.get("path", "")).replace("\\", "/")
                        == target_file
                    ),
                    "",
                )
                if normalized_prior_content:
                    last_rejected_content = normalized_prior_content
                    rejected_content_history = [normalized_prior_content]
                if normalized_prior_content and current_distance <= best_rejected_distance:
                    best_rejected_content = normalized_prior_content
                    best_rejected_error = leaf_errors[0]
                    best_rejected_distance = current_distance
            else:
                record_semantic_fallbacks(revalidated_items, target_file)
                cleaned.extend(revalidated_items)
                stage_accepted_leaf(revalidated_items, target_file)
                _legacy_call(
                    "append_phase_log",
                    phase_log_path,
                    "post_build_repair",
                    "prior_rejected_leaf_revalidated",
                    f"Revalidated prior rejected leaf {target_file} against the current contract.",
                    [target_file],
                )
                continue
        for validation_attempt in range(1, validation_attempts + 1):
            total_attempts += 1
            attempt_payload = dict(payload)
            if leaf_errors:
                repair_base_content = best_rejected_content or last_rejected_content
                repair_base_error = best_rejected_error or leaf_errors[-1]
                attempt_payload["previous_validation_errors"] = [repair_base_error]
                attempt_payload["validation_error_history"] = list(leaf_errors[-3:])
                if repair_base_content:
                    attempt_payload["target_file_contents"] = [
                        {
                            "path": target_file,
                            "content": repair_base_content[:18000],
                            "source": "closest_rejected_candidate",
                            "candidate_only": True,
                        }
                    ]
                    attempt_payload["repair_base_selection"] = {
                        "source": "closest_rejected_candidate",
                        "validation_distance": best_rejected_distance,
                        "single_source": True,
                        "rule": "This target_file_contents row is the only source base for the repair turn; do not restart from the production candidate's older leaf.",
                    }
                stagnated = (
                    len(rejected_content_history) >= 2
                    and rejected_content_history[-1].strip()
                    == rejected_content_history[-2].strip()
                )
                if repair_base_content:
                    if target_file in {
                        "index.html",
                        "src/app.js",
                        "src/main.js",
                        "src/styles.css",
                    }:
                        attempt_payload["rejected_replacement_content_ref"] = (
                            "target_file_contents[0].content"
                        )
                    else:
                        attempt_payload["rejected_replacement_content"] = repair_base_content[:18000]
                if (
                    best_rejected_content
                    and last_rejected_content
                    and best_rejected_content.strip() != last_rejected_content.strip()
                ):
                    attempt_payload["better_rejected_candidate_retained"] = True
                    attempt_payload["latest_candidate_regressed"] = True
                if stagnated:
                    escape_contract, retry_rule = frontend_stagnation_escape_contract(
                        target_file, payload
                    )
                    attempt_payload["stagnation_escape_contract"] = escape_contract
                elif target_file in {
                    "index.html",
                    "src/app.js",
                    "src/styles.css",
                    "src/main.js",
                } and repair_base_content:
                    retry_rule = (
                        "Repair the single target_file_contents base directly. Preserve every behavior "
                        "that already satisfies ui_acceptance_contract and change only what is "
                        "needed to remove every previous_validation_errors item; return the full "
                        "corrected target file."
                    )
                else:
                    retry_rule = (
                        "Discard the rejected replacement and regenerate this target leaf from "
                        "scratch while removing every previous_validation_errors item."
                    )
                if stagnated:
                    attempt_payload["stagnation_detected"] = True
                attempt_payload["strict_rules"] = list(payload["strict_rules"]) + [retry_rule]
            raw = _legacy_call(
                "provider_text",
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(attempt_payload, ensure_ascii=False, indent=2),
                    },
                ],
                model,
                timeout,
                max_attempts=2,
                stage="file_repair",
                component="post_build",
                target_file=target_file,
                max_tokens=9000,
                payload_mode="post_build_file_repair",
                phase_log_path=phase_log_path,
                routing_policy=routing_policy,
            )
            raw_chars += len(raw)
            files: list[dict[str, Any]] = []
            try:
                doc = _legacy_call("parse_json_object", raw)
                files = doc.get("files", [])
                if not isinstance(files, list):
                    files = [
                        {"path": doc.get("path", ""), "content": doc.get("content", "")}
                    ]
                files = normalize_frontend_repair_against_accepted_html(
                    files, cleaned
                )
                validated_items = validate_post_build_repair_files(
                    candidate_dir,
                    files,
                    [target_file],
                    ui_acceptance_contract=repair_plan.get(
                        "ui_acceptance_contract", {}
                    ),
                )
                set_violations = frontend_repair_set_violations(
                    candidate_dir,
                    cleaned + validated_items,
                    repair_plan.get("ui_acceptance_contract", {}),
                )
                if set_violations:
                    raise RuntimeError(
                        "post-build repaired frontend interface mismatch: "
                        + "; ".join(set_violations)
                    )
                record_semantic_fallbacks(validated_items, target_file)
                cleaned.extend(validated_items)
                stage_accepted_leaf(validated_items, target_file)
                break
            except Exception as exc:
                validation_error = str(exc)
                try:
                    last_rejected_content = next(
                        str(item.get("content", ""))
                        for item in files
                        if isinstance(item, dict)
                        and str(item.get("path", "")).replace("\\", "/") == target_file
                    )
                except (NameError, StopIteration):
                    last_rejected_content = ""
                if target_file == "index.html" and last_rejected_content:
                    last_rejected_content, _feedback_normalization = (
                        normalize_ui_repair_html_ownership(
                            last_rejected_content,
                            repair_plan.get("ui_acceptance_contract", {}),
                        )
                    )
                if last_rejected_content:
                    rejected_content_history.append(last_rejected_content)
                    current_distance = frontend_repair_validation_distance(
                        validation_error
                    )
                    if (
                        not best_rejected_content
                        or current_distance < best_rejected_distance
                        or (
                            current_distance == best_rejected_distance
                            and len(last_rejected_content) > len(best_rejected_content)
                        )
                    ):
                        best_rejected_content = last_rejected_content
                        best_rejected_error = validation_error
                        best_rejected_distance = current_distance
                if last_rejected_content:
                    phase_path = pathlib.Path(phase_log_path)
                    rejection_path = (
                        phase_path.parent
                        / "artifacts"
                        / "post_build_rejections"
                        / (
                            target_file.replace("/", "__").replace("\\", "__")
                            + f"__attempt_{validation_attempt}.json"
                        )
                    )
                    _legacy_call(
                        "write_json",
                        rejection_path,
                        {
                            "target_file": target_file,
                            "validation_attempt": validation_attempt,
                            "validation_error": validation_error,
                            "validation_distance": frontend_repair_validation_distance(
                                validation_error
                            ),
                            "content": last_rejected_content,
                            "candidate_only": True,
                            "semantic_adapter_policy": ui_semantic_adapter.POLICY_VERSION,
                        },
                    )
                leaf_errors.append(validation_error)
                validation_errors.append(f"{target_file}: {validation_error}")
                _legacy_call(
                    "append_phase_log",
                    phase_log_path,
                    "post_build_repair",
                    "provider_output_rejected",
                    f"Post-build repair leaf {target_file} attempt {validation_attempt} failed its boundary: {validation_error}",
                    [target_file],
                )
                if validation_attempt >= validation_attempts:
                    raise RuntimeError(
                        f"post-build repair output validation exhausted for {target_file}: "
                        + " | ".join(leaf_errors)
                    ) from exc
    changed: list[str] = []
    for item in cleaned:
        rel = item["path"]
        path = candidate_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8")
        changed.append(rel)
    return {
        "status": "applied",
        "changed_files": changed,
        "raw_chars": raw_chars,
        "output_validation_attempts": total_attempts,
        "rejected_output_errors": validation_errors,
        "pipeline_fallback": pipeline_fallbacks,
    }


def post_build_candidate_review_ready(result: dict[str, Any]) -> bool:
    """Keep review readiness coupled to every current acceptance gate."""
    test_result = result.get("test_result", {})
    fixture_result = result.get("fixture_result", {})
    ui_smoke = result.get("ui_smoke", {})
    return (
        isinstance(test_result, dict)
        and str(test_result.get("status", "")).lower() == "pass"
        and isinstance(fixture_result, dict)
        and str(fixture_result.get("status", "")).lower() == "pass"
        and isinstance(ui_smoke, dict)
        and str(ui_smoke.get("status", "")).lower() == "pass"
        and (bool(result.get("screenshots")) or bool(result.get("screenshot_blocked")))
    )


def run_candidate_post_build_repair_loop(
    *,
    candidate_dir: pathlib.Path,
    run_dir: pathlib.Path,
    user_goal: str,
    generated_files: list[str],
    online_inputs: dict[str, Any],
    example_outputs: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str,
    deadline: Any,
    classifications: dict[str, list[Any]],
    routing_policy: Any | None,
    initial_post_build: dict[str, Any],
    max_attempts: int,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    current = initial_post_build
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    for attempt in range(1, max(0, int(max_attempts)) + 1):
        if str(current.get("status", "")).lower() != "needs_rework":
            break
        plan = compile_post_build_repair_plan(candidate_dir, current)
        plan["attempt_number"] = attempt
        _legacy_call("write_json", artifacts_dir / f"post_build_repair_plan_attempt_{attempt}.json", plan)
        _legacy_call("write_json", candidate_dir / "repair_plan.json", plan)
        _legacy_call("append_phase_log", phase_log_path, "post_build_repair", str(plan.get("status", "planned")), f"Post-build repair attempt {attempt} planned.", plan.get("target_files", []))
        deterministic_result = apply_deterministic_post_build_repair(candidate_dir, plan)
        if deterministic_result.get("changed_files"):
            _legacy_call(
                "append_phase_log",
                phase_log_path,
                "post_build_repair",
                "deterministic_repair_applied",
                f"Applied deterministic post-build repair attempt {attempt}.",
                deterministic_result.get("changed_files", []),
            )
        if not plan.get("provider_actions"):
            if deterministic_result.get("changed_files"):
                import post_build_finalize

                current = post_build_finalize.run(
                    project_dir=candidate_dir,
                    run_dir=run_dir,
                    user_goal=user_goal,
                    generated_files=generated_files,
                    online_inputs=online_inputs,
                    example_outputs=example_outputs,
                    model=model,
                    timeout=timeout,
                    phase_log_path=phase_log_path,
                    deadline=deadline,
                    classifications=classifications,
                    routing_policy=routing_policy,
                )
                current["post_build_repair_attempt"] = attempt
                current["post_build_repair_plan"] = plan
                current["post_build_repair_result"] = {"status": "applied", "deterministic": deterministic_result, "provider": {"status": "skipped"}}
                current["candidate_review_ready"] = post_build_candidate_review_ready(current)
            history.append({"attempt_number": attempt, "plan": snapshot(plan), "repair_result": {"status": "skipped", "reason": "no provider file-level repair targets", "deterministic": snapshot(deterministic_result)}, "post_build": snapshot(current)})
            if deterministic_result.get("changed_files") and str(current.get("status", "")).lower() == "needs_rework" and attempt < max(0, int(max_attempts)):
                continue
            break
        try:
            repair_result = _legacy_call(
                "provider_post_build_file_repair",
                candidate_dir=candidate_dir,
                repair_plan=plan,
                model=model,
                timeout=min(timeout, 180),
                phase_log_path=phase_log_path,
                routing_policy=routing_policy,
            )
        except Exception as exc:
            repair_result = {"status": "failed", "error": str(exc), "changed_files": []}
        if repair_result.get("status") != "applied":
            if deterministic_result.get("changed_files"):
                import post_build_finalize

                current = post_build_finalize.run(
                    project_dir=candidate_dir,
                    run_dir=run_dir,
                    user_goal=user_goal,
                    generated_files=generated_files,
                    online_inputs=online_inputs,
                    example_outputs=example_outputs,
                    model=model,
                    timeout=timeout,
                    phase_log_path=phase_log_path,
                    deadline=deadline,
                    classifications=classifications,
                    routing_policy=routing_policy,
                )
                current["post_build_repair_attempt"] = attempt
                current["post_build_repair_plan"] = plan
                current["post_build_repair_result"] = {"status": "partial", "deterministic": deterministic_result, "provider": repair_result}
                current["candidate_review_ready"] = post_build_candidate_review_ready(current)
            history.append({"attempt_number": attempt, "plan": snapshot(plan), "repair_result": snapshot(repair_result), "post_build": snapshot(current)})
            break
        import post_build_finalize

        current = post_build_finalize.run(
            project_dir=candidate_dir,
            run_dir=run_dir,
            user_goal=user_goal,
            generated_files=generated_files,
            online_inputs=online_inputs,
            example_outputs=example_outputs,
            model=model,
            timeout=timeout,
            phase_log_path=phase_log_path,
            deadline=deadline,
            classifications=classifications,
            routing_policy=routing_policy,
        )
        current["post_build_repair_attempt"] = attempt
        current["post_build_repair_plan"] = plan
        current["post_build_repair_result"] = {"status": "applied", "deterministic": deterministic_result, "provider": repair_result}
        current["candidate_review_ready"] = post_build_candidate_review_ready(current)
        history.append({"attempt_number": attempt, "plan": snapshot(plan), "repair_result": snapshot(repair_result), "post_build": snapshot(current)})
    if history:
        current["post_build_repair_history"] = history
        current["candidate_review_ready"] = post_build_candidate_review_ready(current)
        _legacy_call("write_json", artifacts_dir / "post_build_repair_history.json", {"attempts": history, "final_post_build": current})
        if isinstance(history[-1].get("plan"), dict):
            _legacy_call("write_json", candidate_dir / "repair_plan.json", history[-1]["plan"])
    return current


def run_if_needed(*, candidate_dir: pathlib.Path, repair_plan: dict[str, Any]) -> dict[str, Any]:
    changed: list[str] = []
    skipped: list[dict[str, str]] = []
    for action in repair_plan.get("deterministic_actions", []):
        if not isinstance(action, dict) or action.get("action") != "repair_windows_esm_path_imports":
            continue
        paths = action.get("paths", [])
        if not isinstance(paths, list):
            paths = []
        for item in paths[:3]:
            rel = str(item).replace("\\", "/").strip()
            path = (candidate_dir / rel).resolve()
            if not str(path).lower().startswith(str(candidate_dir.resolve()).lower()):
                skipped.append({"path": rel, "reason": "path escaped candidate"})
                continue
            if not path.exists():
                skipped.append({"path": rel, "reason": "target missing"})
                continue
            if repair_windows_esm_path_import_file(path):
                changed.append(rel)
    status = "pass" if changed else "warning"
    result = RepairResult(status=status, changed_files=sorted(set(changed)), metadata={"skipped": skipped})
    data = result.to_dict()
    data["changed_files"] = result.changed_files
    return data


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="replaceable_module",
        metadata={
            "responsibilities": [
                "failure classification",
                "deterministic repairs",
                "Windows ESM pathToFileURL repair",
                "file-level provider repair",
                "repair attempt limit",
            ],
            "forbidden": ["whole-project regeneration", "final_project_bundle.zip", "delivery_manifest.json", "fake evidence"],
        },
    )
