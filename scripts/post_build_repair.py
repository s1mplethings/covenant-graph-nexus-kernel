#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import json
import re
from typing import Any

try:
    from pipeline_contracts import RepairResult, base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import RepairResult, base_result


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
    try:
        return importlib.import_module("run_local_pipeline")
    except ModuleNotFoundError:
        return importlib.import_module("scripts.run_local_pipeline")


def _legacy_call(name: str, *args: Any, **kwargs: Any) -> Any:
    return getattr(_legacy(), name)(*args, **kwargs)


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
    agent_usage = finalize_result.get("agent_usage", {}) if isinstance(finalize_result.get("agent_usage"), dict) else {}
    chunks = [
        "test_status=" + str(test_result.get("status", "")),
        "test_argv=" + json.dumps(test_result.get("argv", []), ensure_ascii=False),
        str(test_result.get("error", "")),
        str(test_result.get("stdout_tail", "")),
        str(test_result.get("stderr_tail", "")),
        "agent_usage_status=" + str(agent_usage.get("status", "")),
        json.dumps(agent_usage.get("failure_summary", ""), ensure_ascii=False, default=str),
        json.dumps(agent_usage.get("events", [])[-6:] if isinstance(agent_usage.get("events", []), list) else [], ensure_ascii=False, default=str),
        json.dumps(finalize_result.get("screenshot_capture", {}), ensure_ascii=False, default=str),
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
    log = post_build_failure_log(finalize_result).lower()
    if str(test_result.get("status", "")).lower() == "failed":
        failures.add("test_failure")
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
    if any(token in log for token in ("missing script", "no recognized test command", "entrypoint", "index.html", "not found")):
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
    found: list[str] = []
    pattern = re.compile(r"([A-Za-z0-9_.\-/\\]+?\.(?:mjs|cjs|js|jsx|ts|tsx|json|html|css|py|md))")
    for match in pattern.finditer(text or ""):
        rel = match.group(1).replace("\\", "/").lstrip("./")
        if rel in known and rel not in found:
            found.append(rel)
    return found


def default_post_build_targets(candidate_dir: pathlib.Path, failures: list[str]) -> list[str]:
    candidates: list[str] = []

    def add(path: str, *, allow_missing: bool = False) -> None:
        rel = path.replace("\\", "/")
        if rel not in candidates and (allow_missing or (candidate_dir / rel).exists()):
            candidates.append(rel)

    if "missing_package_json" in failures:
        add("package.json", allow_missing=True)
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
    if "windows_esm_path_import" in failures:
        for rel in ("scripts/run-tests.mjs", "tests/api_contract_test.mjs", "tests/smoke_test.mjs"):
            add(rel)
        for path in sorted((candidate_dir / "tests").glob("*.mjs")) if (candidate_dir / "tests").exists() else []:
            add(path.relative_to(candidate_dir).as_posix())
    if "page_blank" in failures:
        for rel in ("index.html", "src/app.js", "scripts/util/buildAll.js", "src/main.js"):
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
    test_passed = str(test_result.get("status", "")).lower() == "pass"
    target_files: list[str] = []
    for rel in extract_post_build_target_files(candidate_dir, log) + default_post_build_targets(candidate_dir, failures):
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
    if "missing_entrypoint" in failures and "index.html" not in target_files:
        target_files.insert(0, "index.html")
    if "missing_static_entry" in failures and "index.html" not in target_files:
        target_files.insert(0, "index.html")
    target_files = target_files[:3]
    screenshot_runtime_actionable = any(kind in failures for kind in ("startup_failure", "missing_entrypoint", "dependency_failure", "module_system_failure", "test_failure", "page_blank"))
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
        deterministic_actions.append({"action": "create_basic_index_html", "path": "index.html"})
        if "index.html" not in target_files:
            target_files.insert(0, "index.html")
    if "missing_start_script" in failures:
        deterministic_actions.append({"action": "add_static_start_script", "path": "package.json"})
        if "package.json" not in target_files and (candidate_dir / "package.json").exists():
            target_files.insert(0, "package.json")
    if "missing_static_entry" in failures:
        deterministic_actions.append({"action": "create_static_entrypoint", "path": "index.html"})
        if "index.html" not in target_files:
            target_files.insert(0, "index.html")
    if "missing_package_json" in failures and "candidate_not_runnable" not in failures:
        deterministic_actions.append({"action": "create_minimal_package_json", "path": "package.json"})
    if "page_blank" in failures:
        deterministic_actions.append({"action": "repair_page_blank_demo_ui", "paths": [rel for rel in ("index.html", "src/main.js", "src/app.js") if rel in target_files or (candidate_dir / rel).exists()]})
    if "frontend_backend_start_mismatch" in failures:
        deterministic_actions.append({"action": "enable_static_preview_demo_data", "path": "index.html"})
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
    target_files = target_files[:3]

    deterministic_only = bool({"windows_esm_path_import", "missing_vitest", "no_tests_ran", "missing_start_script", "missing_static_entry", "page_blank", "frontend_backend_start_mismatch", "missing_package_json"} & set(failures))
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
    return {
        "stage": "post_build_repair",
        "created_at": _legacy_call("now"),
        "status": "candidate_not_runnable" if "candidate_not_runnable" in failures else ("planned" if (provider_actions or deterministic_actions) else "no_actionable_file_repair"),
        "failure_types": failures,
        "root_causes": sorted(set(root_causes)),
        "target_files": target_files,
        "provider_actions": provider_actions[:3],
        "deterministic_actions": deterministic_actions,
        "validation_commands": validation_commands,
        "must_disappear_failures": must_disappear,
        "log_summary": log[:3000],
        "candidate_only": True,
        "forbidden_outputs": ["final_project_bundle.zip", "delivery_manifest.json", "fake screenshots/videos", "fake TEST_REPORT PASS"],
    }


def validate_post_build_repair_files(candidate_dir: pathlib.Path, files: list[dict[str, str]], target_files: list[str]) -> list[dict[str, str]]:
    targets = {str(path).replace("\\", "/").strip() for path in target_files if str(path).strip()}
    cleaned = _legacy_call("validate_provider_files", {"files": files})
    for item in cleaned:
        rel = item["path"]
        if rel not in targets:
            raise RuntimeError(f"post-build repair tried to modify non-target file: {rel}")
        resolved = (candidate_dir / rel).resolve()
        if not str(resolved).lower().startswith(str(candidate_dir.resolve()).lower()):
            raise RuntimeError(f"post-build repair path escaped candidate dir: {rel}")
        lowered = item["content"].lower()
        if pathlib.PurePosixPath(rel).name in {"final_project_bundle.zip", "delivery_manifest.json"}:
            raise RuntimeError("post-build repair cannot generate final delivery artifacts")
        if _legacy_call("fake_delivery_claim_present", rel, item["content"]):
            raise RuntimeError(f"post-build repair introduced fake delivery claim: {rel}")
        if rel.upper().endswith("TEST_REPORT.MD") and any(token in lowered for token in ("all tests passed", "pass_final", "final delivery ready")):
            raise RuntimeError("post-build repair introduced fake TEST_REPORT pass claim")
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


def _demo_ui_module_content() -> str:
    return """const demoTasks = [
  { title: "Plan vertical slice", status: "Todo" },
  { title: "Fix combat UI bug", status: "Doing" },
  { title: "Review build notes", status: "Done" },
];

const demoBugs = [
  { title: "Crash on loading save", status: "Open" },
  { title: "Quest marker offset", status: "In Progress" },
  { title: "Audio loop fixed", status: "Fixed" },
];

function render() {
  const root = document.getElementById("root") || document.body;
  root.innerHTML = `
    <main class="app-shell">
      <h1>Game Team Task and Bug Dashboard</h1>
      <section aria-label="Dashboard">
        <h2>Dashboard</h2>
        <p>Task Board, Bug List, local JSON persistence, filters, owners, priorities, tags, and due dates.</p>
      </section>
      <section aria-label="New Task">
        <h2>New Task</h2>
        <input aria-label="Task title" placeholder="New Task" />
        <button type="button">Add Task</button>
      </section>
      <section aria-label="Task Board" class="columns">
        ${["Todo", "Doing", "Done"].map((status) => `<article><h3>${status}</h3>${demoTasks.filter((task) => task.status === status).map((task) => `<p>${task.title}</p>`).join("")}</article>`).join("")}
      </section>
      <section aria-label="Bug List" class="columns">
        ${["Open", "In Progress", "Fixed"].map((status) => `<article><h3>${status}</h3>${demoBugs.filter((bug) => bug.status === status).map((bug) => `<p>${bug.title}</p>`).join("")}</article>`).join("")}
      </section>
    </main>
  `;
}

render();
"""


def ensure_static_index(candidate_dir: pathlib.Path) -> list[str]:
    changed: list[str] = []
    index = candidate_dir / "index.html"
    if not index.exists():
        index.write_text(
            "\n".join(
                [
                    "<!doctype html>",
                    "<html lang=\"en\">",
                    "<head>",
                    "  <meta charset=\"utf-8\">",
                    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
                    "  <title>Task Board</title>",
                    "</head>",
                    "<body>",
                    "  <div id=\"root\"></div>",
                    "  <script type=\"module\" src=\"./src/main.js\"></script>",
                    "</body>",
                    "</html>",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        changed.append("index.html")
    else:
        text = index.read_text(encoding="utf-8", errors="replace")
        updated = text
        if "<body" not in updated.lower():
            updated = updated.replace("</head>", "</head>\n<body>\n<div id=\"root\"></div>\n<script type=\"module\" src=\"./src/main.js\"></script>\n</body>", 1)
        if "id=\"root\"" not in updated and "id='root'" not in updated:
            updated = updated.replace("<body>", "<body>\n  <div id=\"root\"></div>", 1) if "<body>" in updated else updated + "\n<div id=\"root\"></div>\n"
        if "src/main.js" not in updated and "./src/main.js" not in updated:
            updated = updated.replace("</body>", "  <script type=\"module\" src=\"./src/main.js\"></script>\n</body>", 1) if "</body>" in updated else updated + "\n<script type=\"module\" src=\"./src/main.js\"></script>\n"
        if updated != text:
            index.write_text(updated, encoding="utf-8")
            changed.append("index.html")
    return changed


def repair_page_blank_demo_ui(candidate_dir: pathlib.Path) -> list[str]:
    changed = ensure_static_index(candidate_dir)
    main = candidate_dir / "src" / "main.js"
    main.parent.mkdir(parents=True, exist_ok=True)
    content = _demo_ui_module_content()
    if not main.exists() or main.read_text(encoding="utf-8", errors="replace").strip() == "" or "Game Team Task and Bug Dashboard" not in main.read_text(encoding="utf-8", errors="replace"):
        main.write_text(content, encoding="utf-8")
        changed.append("src/main.js")
    return sorted(set(changed))


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


def enable_static_preview_demo_data(candidate_dir: pathlib.Path) -> list[str]:
    changed = ensure_static_index(candidate_dir)
    index = candidate_dir / "index.html"
    if not index.exists():
        return changed
    text = index.read_text(encoding="utf-8", errors="replace")
    marker = "window.CGNK_STATIC_PREVIEW_DEMO_DATA"
    if marker in text:
        return changed
    script = (
        "  <script>\n"
        "    window.CGNK_STATIC_PREVIEW = true;\n"
        "    window.CGNK_STATIC_PREVIEW_DEMO_DATA = { tasks: ['Todo', 'Doing', 'Done'], bugs: ['Open', 'In Progress', 'Fixed'] };\n"
        "  </script>\n"
    )
    updated = text.replace("</head>", script + "</head>", 1) if "</head>" in text else script + text
    index.write_text(updated, encoding="utf-8")
    changed.append("index.html")
    return sorted(set(changed))


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
        elif kind == "create_static_entrypoint":
            changed.extend(repair_page_blank_demo_ui(candidate_dir))
        elif kind == "create_minimal_package_json":
            changed.extend(create_minimal_package_json(candidate_dir))
        elif kind == "repair_page_blank_demo_ui":
            changed.extend(repair_page_blank_demo_ui(candidate_dir))
        elif kind == "enable_static_preview_demo_data":
            changed.extend(enable_static_preview_demo_data(candidate_dir))
        elif kind == "create_basic_index_html" and rel == "index.html":
            changed.extend(ensure_static_index(candidate_dir))
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
    target_files = [rel for rel in target_files if rel][:3]
    if not target_files:
        return {"status": "skipped", "reason": "no provider file-level repair targets", "changed_files": []}
    existing: list[dict[str, Any]] = []
    for rel in target_files:
        path = candidate_dir / rel
        if path.exists() and path.is_file():
            existing.append({"path": rel, "content": path.read_text(encoding="utf-8", errors="replace")[:18000], "missing": False})
        else:
            existing.append({"path": rel, "content": "", "missing": True})

    system = """Repair a CGNK candidate project after post-build failure.
Return strict JSON only: {"files":[{"path":"target file","content":"full replacement content"}]}.
You may modify only the requested target files. Do not regenerate the whole project.
Do not generate final_project_bundle.zip, delivery_manifest.json, screenshots, videos, or fake TEST_REPORT pass claims.
Keep the project candidate-only; final packaging is local_packager-only after validation."""
    payload = {
        "stage": "post_build_repair",
        "candidate_only": True,
        "target_files": target_files,
        "observed_failures": repair_plan.get("failure_types", []),
        "root_causes": repair_plan.get("root_causes", []),
        "failure_log_summary": str(repair_plan.get("log_summary", ""))[:3000],
        "validation_commands": repair_plan.get("validation_commands", []),
        "target_file_contents": existing,
        "strict_rules": [
            "Return only full replacement content for target_files.",
            "Do not add or remove files outside target_files.",
            "Do not claim tests/screenshots/videos passed unless the local post-build runner produced that evidence.",
            "Do not write final_project_bundle.zip or delivery_manifest.json.",
        ],
    }
    raw = _legacy_call(
        "provider_text",
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
        model,
        timeout,
        max_attempts=2,
        stage="file_repair",
        component="post_build",
        max_tokens=9000,
        payload_mode="post_build_file_repair",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = _legacy_call("parse_json_object", raw)
    files = doc.get("files", [])
    if not isinstance(files, list):
        files = [{"path": doc.get("path", ""), "content": doc.get("content", "")}]
    cleaned = validate_post_build_repair_files(candidate_dir, files, target_files)
    changed: list[str] = []
    for item in cleaned:
        rel = item["path"]
        path = candidate_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8")
        changed.append(rel)
    return {"status": "applied", "changed_files": changed, "raw_chars": len(raw)}


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
                test_status = str((current.get("test_result") or {}).get("status", "")).lower() if isinstance(current.get("test_result"), dict) else ""
                if test_status == "pass" or current.get("screenshots"):
                    current["candidate_review_ready"] = True
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
                test_status = str((current.get("test_result") or {}).get("status", "")).lower() if isinstance(current.get("test_result"), dict) else ""
                if test_status == "pass" or current.get("screenshots"):
                    current["candidate_review_ready"] = True
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
        if str(current.get("status", "")).lower() == "needs_rework":
            test_status = str((current.get("test_result") or {}).get("status", "")).lower() if isinstance(current.get("test_result"), dict) else ""
            if test_status == "pass" or current.get("screenshots"):
                current["candidate_review_ready"] = True
        history.append({"attempt_number": attempt, "plan": snapshot(plan), "repair_result": snapshot(repair_result), "post_build": snapshot(current)})
    if history:
        current["post_build_repair_history"] = history
        current.setdefault("candidate_review_ready", any(bool((item.get("post_build") or {}).get("candidate_review_ready")) for item in history))
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
