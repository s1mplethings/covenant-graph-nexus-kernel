#!/usr/bin/env python3
"""Fixed10 black-box evaluator executed only after a candidate is sealed.

The evaluator intentionally imports only the benchmark evidence schema.  Project
execution happens from a copied temporary root and a newly-created virtualenv.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from benchmarks.project_generation_v1 import evaluator


def _write(path: pathlib.Path, value: dict[str, Any]) -> None:
    evaluator.write_json(path, value)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _venv_python(root: pathlib.Path) -> pathlib.Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(argv: list[str], *, cwd: pathlib.Path, timeout: int = 120, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
        return {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "return_code": completed.returncode,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
            "argv": argv,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAIL", "return_code": 124, "elapsed_seconds": round(time.perf_counter() - started, 3), "error": str(exc), "argv": argv}


def _declared_dependencies(project: pathlib.Path) -> list[str]:
    values: list[str] = []
    requirements = project / "requirements.txt"
    if requirements.is_file():
        values.extend(
            line.strip() for line in requirements.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    pyproject = project / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib
            doc = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
            values.extend(str(item) for item in doc.get("project", {}).get("dependencies", []))
        except (OSError, TypeError, ValueError):
            pass
    return sorted(set(values))


def prepare_clean_environment(
    project: pathlib.Path,
    env_root: pathlib.Path,
    dependency_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dependency_policy if isinstance(dependency_policy, dict) else {}
    mode = str(policy.get("mode", "wheelhouse") or "wheelhouse").strip().lower()
    if mode not in {"wheelhouse", "registry", "no_index"}:
        return {"status": "FAIL", "stage": "dependency_policy", "error": f"unsupported dependency mode: {mode}"}
    started = time.perf_counter()
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(env_root)
    except Exception as exc:
        return {"status": "FAIL", "stage": "venv_create", "error": str(exc)}
    python = _venv_python(env_root)
    dependencies = _declared_dependencies(project)
    install = {"status": "PASS", "argv": [], "return_code": 0}
    requirements = project / "requirements.txt"
    package_source = "none_required"
    package_registry_network = False
    dependency_network_access: list[dict[str, Any]] = []
    install_args: list[str] = []
    if dependencies:
        if mode == "wheelhouse":
            wheelhouse = pathlib.Path(str(policy.get("wheelhouse", ""))).resolve() if str(policy.get("wheelhouse", "")).strip() else None
            if wheelhouse is None or not wheelhouse.is_dir():
                return {
                    "status": "FAIL",
                    "stage": "dependency_policy",
                    "error": "approved wheelhouse is required but unavailable",
                    "dependency_mode": mode,
                    "declared_dependencies": dependencies,
                    "provider_network": "separate",
                    "package_registry_network": False,
                }
            package_source = str(wheelhouse)
            install_args = ["--no-index", "--find-links", str(wheelhouse)]
        elif mode == "registry":
            if policy.get("registry_approved") is not True:
                return {
                    "status": "FAIL",
                    "stage": "dependency_policy",
                    "error": "package registry mode requires explicit approval",
                    "dependency_mode": mode,
                    "declared_dependencies": dependencies,
                    "provider_network": "separate",
                    "package_registry_network": False,
                }
            package_source = str(policy.get("registry_url") or "configured pip registry")
            package_registry_network = True
        else:
            package_source = "pip_no_index_without_wheelhouse"
            install_args = ["--no-index"]
        target_args = ["-r", str(requirements)] if requirements.is_file() else dependencies
        install = _run(
            [str(python), "-m", "pip", "install", *install_args, "--disable-pip-version-check", *target_args],
            cwd=project,
            timeout=240,
        )
        if package_registry_network:
            for dependency in dependencies:
                match = re.match(r"^([A-Za-z0-9_.-]+)\s*(?:==\s*([^;\s]+))?", dependency)
                dependency_network_access.append({
                    "registry": str(policy.get("registry_url") or "PyPI"),
                    "package": match.group(1) if match else dependency,
                    "version": match.group(2) if match and match.group(2) else "declared_constraint",
                    "status": install.get("status", "FAIL"),
                })
    return {
        "status": "PASS" if install.get("status") == "PASS" else "FAIL",
        "fresh_virtualenv": True,
        "system_site_packages": False,
        "provider_network": "separate",
        "package_registry_network": package_registry_network,
        "dependency_mode": mode,
        "dependency_source": package_source,
        "python": str(python),
        "declared_dependencies": dependencies,
        "dependency_install": install,
        "dependency_network_access": dependency_network_access,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def documented_entrypoint(project: pathlib.Path, python: pathlib.Path) -> tuple[list[str], str]:
    readme = project / "README.md"
    text = readme.read_text(encoding="utf-8", errors="replace") if readme.is_file() else ""
    commands = [
        line.strip().lstrip("$>").strip()
        for block in re.findall(r"```(?:bash|sh|shell|powershell|cmd)?\s*\n(.*?)```", text, flags=re.I | re.S)
        for line in block.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    commands.extend(token.strip() for token in re.findall(r"`([^`\r\n]+)`", text) if token.strip())
    candidates = [
        item for item in commands
        if re.match(r"^(?:python(?:3)?|py|uvicorn|flask|npm|pnpm|yarn)\b", item, flags=re.I)
        and not re.search(r"\b(?:pip|venv|pytest|unittest|install|test|build)\b", item, flags=re.I)
    ]
    if not candidates:
        return [], "README has no supported copyable start command"
    raw = candidates[0]
    argv = shlex.split(raw, posix=os.name != "nt")
    if argv and argv[0].lower() in {"python", "python3", "py"}:
        argv[0] = str(python)
    return argv, raw


def static_checks(project: pathlib.Path, python: pathlib.Path) -> dict[str, Any]:
    compile_result = _run([str(python), "-m", "compileall", "-q", "."], cwd=project, timeout=90)
    modules: list[str] = []
    for path in project.rglob("*.py"):
        relative = path.relative_to(project)
        if "tests" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts and all(part.isidentifier() for part in parts):
            modules.append(".".join(parts))
    import_code = "import importlib\n" + "\n".join(
        f"importlib.import_module({module!r})" for module in sorted(set(modules))
    )
    import_smoke = _run([str(python), "-c", import_code], cwd=project, timeout=90) if modules else {"status": "NOT_EVALUATED", "reason": "no importable Python modules"}
    test_files = list((project / "tests").rglob("test*.py")) if (project / "tests").is_dir() else []
    tests = {"status": "NOT_EVALUATED", "reason": "no generated Python tests"}
    if test_files:
        tests = _run([str(python), "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"], cwd=project, timeout=120)
        if tests.get("status") != "PASS":
            pytest_probe = _run([str(python), "-m", "pytest", "-q"], cwd=project, timeout=120)
            if pytest_probe.get("status") == "PASS":
                tests = pytest_probe
    return {
        "status": "PASS" if compile_result.get("status") == "PASS" and import_smoke.get("status") in {"PASS", "NOT_EVALUATED"} else "FAIL",
        "compileall": compile_result,
        "import_smoke": import_smoke,
        "generated_tests": tests,
    }


def _request(url: str, *, method: str = "GET", value: Any = None) -> dict[str, Any]:
    data = None if value is None else json.dumps(value).encode("utf-8")
    request = urllib.request.Request(url, method=method, data=data, headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(300_000)
            try:
                parsed = json.loads(body.decode("utf-8", errors="replace"))
            except ValueError:
                parsed = None
            return {"status": int(response.status), "body": body.decode("utf-8", errors="replace")[:4000], "json": parsed}
    except urllib.error.HTTPError as exc:
        return {"status": int(exc.code), "body": exc.read().decode("utf-8", errors="replace")[:4000], "json": None}
    except Exception as exc:
        return {"status": 0, "body": str(exc), "json": None}


def _routes(project: pathlib.Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in project.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"@\w+\.(get|post|put|patch|delete|route)\(\s*['\"]([^'\"]+)", text, flags=re.I):
            method, route = match.group(1).upper(), match.group(2)
            found.add(("GET" if method == "ROUTE" else method, route))
        stdlib_routes = set(re.findall(r"['\"](/api/[^'\"]*)['\"]", text))
        if "def do_GET" in text:
            found.update(("GET", route) for route in stdlib_routes)
        if "def do_POST" in text:
            found.update(("POST", route) for route in stdlib_routes)
    return found


def _collection_route(routes: set[tuple[str, str]], case_id: str) -> str:
    preferences = {
        "CASE_01": ("/api/clean", "/api/upload", "/api/process"),
        "CASE_02": ("/api/convert",), "CASE_03": ("/api/tasks", "/api/cards"),
        "CASE_04": ("/api/items",), "CASE_05": ("/api/records", "/api/tasks"),
        "CASE_06": ("/api/notes",), "CASE_07": ("/api/process",),
        "CASE_08": ("/api/feeds",), "CASE_09": ("/api/records",),
        "CASE_10": ("/api/feedback", "/api/records", "/api/items"),
    }
    prefix = case_id[:7]
    posts = {route for method, route in routes if method == "POST" and "<" not in route}
    return next((route for route in preferences.get(prefix, ()) if route in posts), next(iter(sorted(posts)), ""))


def _scenario_payload(case_id: str, workspace: pathlib.Path) -> dict[str, Any]:
    prefix = case_id[:7]
    source = workspace / "scenario-input"
    output = workspace / "scenario-output"
    source.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    (source / "one.md").write_text("# Title\n\n- item\n\n```py\nprint(1)\n```\n\n[link](https://example.test)\n", encoding="utf-8")
    payloads = {
        "CASE_01": {"rows": [{"name": "A", "email": "a@example.test"}, {"name": "A", "email": "a@example.test"}, {"name": "B", "email": ""}]},
        "CASE_02": {"input_dir": str(source), "output_dir": str(output)},
        "CASE_03": {"title": "Independent task", "status": "TODO", "description": "move and persist"},
        "CASE_04": {"name": "Camera", "category": "tools", "quantity": 2, "purchase_date": "2026-01-02", "notes": "independent"},
        "CASE_05": {"title": "Renew document", "category": "important", "status": "pending", "important": True, "notes": "follow up"},
        "CASE_06": {"title": "Independent note", "content": "# Searchable alpha", "tags": ["alpha"]},
        "CASE_07": {"input_dir": str(source), "output_dir": str(output), "width": 32, "height": 32, "format": "PNG"},
        "CASE_08": {"url": "http://127.0.0.1:9/controlled-feed.xml", "name": "Controlled source"},
        "CASE_09": {"name": "Independent record", "value": "shared-state"},
        "CASE_10": {"title": "Login feedback", "description": "Customers cannot sign in", "status": "new", "category": "problem", "priority": "high"},
    }
    return payloads.get(prefix, {"title": "Independent record"})


def _wait_ready(port: int, process: subprocess.Popen[str]) -> dict[str, Any]:
    started = time.perf_counter()
    last = {"status": 0, "body": "not attempted"}
    while time.perf_counter() - started < 20:
        if process.poll() is not None:
            return {"ready": False, "process_exit": process.returncode, "last": last}
        for path in ("/health", "/"):
            last = _request(f"http://127.0.0.1:{port}{path}")
            if 200 <= int(last["status"]) < 400:
                return {"ready": True, "path": path, "response": last}
        time.sleep(0.25)
    return {"ready": False, "process_exit": process.poll(), "last": last}


def _browser_probe(url: str, screenshot: pathlib.Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            response = page.goto(url, wait_until="networkidle", timeout=20000)
            page.screenshot(path=str(screenshot), full_page=True)
            title = page.title()
            body = page.locator("body").inner_text(timeout=5000)
            browser.close()
        return {"status": "PASS" if response and response.ok and len(body.strip()) >= 20 else "FAIL", "http_status": response.status if response else 0, "title": title, "body_chars": len(body), "screenshot": str(screenshot)}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc), "screenshot": str(screenshot)}


def runtime_probe(project: pathlib.Path, python: pathlib.Path, case_id: str, evidence_dir: pathlib.Path) -> dict[str, Any]:
    argv, documented = documented_entrypoint(project, python)
    if not argv:
        return {"status": "FAIL", "documented_entrypoint": documented, "reason": documented}
    port = _free_port()
    env = {key: value for key, value in os.environ.items() if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({"PORT": str(port), "HOST": "127.0.0.1", "CGKN_EVALUATION": "1"})
    started_at = time.time()
    try:
        process = subprocess.Popen(
            argv,
            cwd=project,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return {
            "status": "FAIL",
            "mode": "launch",
            "argv": argv,
            "documented_entrypoint": documented,
            "workspace": str(project),
            "reason": f"documented entrypoint could not be launched: {exc}",
            "error_type": type(exc).__name__,
        }
    ready = _wait_ready(port, process)
    if not ready["ready"] and process.poll() == 0:
        stdout, stderr = process.communicate(timeout=2)
        return {"status": "PASS", "mode": "completed_cli", "argv": argv, "documented_entrypoint": documented, "pid": process.pid, "start_time": started_at, "workspace": str(project), "port": None, "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:], "shutdown": "natural_exit"}
    routes = _routes(project)
    route = _collection_route(routes, case_id)
    root = _request(f"http://127.0.0.1:{port}/") if ready["ready"] else {"status": 0, "body": "not ready"}
    scenario = _request(f"http://127.0.0.1:{port}{route}", method="POST", value=_scenario_payload(case_id, project)) if ready["ready"] and route else {"status": 0, "body": "no observable POST route"}
    invalid = _request(f"http://127.0.0.1:{port}{route}", method="POST", value={}) if ready["ready"] and route else {"status": 0, "body": "no route"}
    screenshot = evidence_dir / "runtime_browser.png"
    browser = _browser_probe(f"http://127.0.0.1:{port}/", screenshot) if ready["ready"] else {"status": "FAIL", "reason": "runtime not ready"}
    process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
    shutdown = process.poll() is not None
    restart: dict[str, Any] = {"status": "NOT_EVALUATED", "reason": "initial runtime did not complete"}
    if shutdown and ready["ready"]:
        restart_port = _free_port()
        restart_env = dict(env)
        restart_env["PORT"] = str(restart_port)
        try:
            restarted = subprocess.Popen(
                argv,
                cwd=project,
                env=restart_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            restart = {
                "status": "FAIL",
                "argv": argv,
                "workspace": str(project),
                "reason": f"documented entrypoint could not be restarted: {exc}",
                "error_type": type(exc).__name__,
            }
            restarted = None
        if restarted is None:
            return {
                "status": "PASS" if ready["ready"] and 200 <= int(root["status"]) < 400 and shutdown else "FAIL",
                "mode": "http",
                "argv": argv,
                "documented_entrypoint": documented,
                "pid": process.pid,
                "start_time": started_at,
                "workspace": str(project),
                "port": port,
                "ready": ready,
                "root": root,
                "scenario": scenario,
                "invalid": invalid,
                "browser": browser,
                "stdout_tail": stdout[-2000:],
                "stderr_tail": stderr[-2000:],
                "shutdown": "terminated" if shutdown else "failed",
                "restart": restart,
            }
        restarted_ready = _wait_ready(restart_port, restarted)
        collection_get = _request(f"http://127.0.0.1:{restart_port}{route}") if restarted_ready["ready"] and route else {"status": 0, "body": "no collection GET"}
        persisted_marker = any(marker in json.dumps(collection_get, ensure_ascii=False).lower() for marker in ("independent", "camera", "login feedback", "controlled source"))
        restarted.terminate()
        try:
            restarted.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            restarted.kill()
            restarted.communicate(timeout=5)
        restart = {
            "status": "PASS" if restarted_ready["ready"] and (persisted_marker or case_id[:7] in {"CASE_01", "CASE_02", "CASE_07"}) else "FAIL",
            "pid": restarted.pid,
            "start_time": time.time(),
            "workspace": str(project),
            "port": restart_port,
            "ready": restarted_ready,
            "collection_get": collection_get,
            "persisted_marker": persisted_marker,
            "shutdown": "terminated" if restarted.poll() is not None else "failed",
        }
    return {
        "status": "PASS" if ready["ready"] and 200 <= int(root["status"]) < 400 and shutdown else "FAIL",
        "mode": "http", "argv": argv, "documented_entrypoint": documented,
        "pid": process.pid, "start_time": started_at, "workspace": str(project), "port": port,
        "port_owner_pid": process.pid, "ready": ready, "root": root, "routes": sorted([list(item) for item in routes]),
        "scenario": scenario, "invalid_scenario": invalid, "browser": browser,
        "restart": restart,
        "shutdown": "terminated" if shutdown else "failed", "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-4000:],
    }


def _observation(case: dict[str, Any], run_id: str, candidate_hash: str, criterion: str, passed: bool, producer: str, details: str, *, failure_category: str, requirement_ids: list[str] | None = None) -> dict[str, Any]:
    value = evaluator.make_observation(case_id=str(case["case_id"]), run_id=run_id, candidate_sha256=candidate_hash, criterion_id=criterion, status="PASS" if passed else "FAIL", producer=producer, details=details[:12000], requirement_ids=requirement_ids or [])
    if not passed:
        value.update({"failure_category": failure_category, "failure_stack": details[-4000:], "affected_files": ["README.md", "app/main.py"], "affected_work_nodes": []})
    return value


def execute(input_path: pathlib.Path) -> dict[str, Any]:
    spec = evaluator.read_json(input_path)
    case = dict(spec["case"])
    run_id = str(spec["benchmark_run_id"])
    source = pathlib.Path(str(spec["candidate_dir"])).resolve()
    output = pathlib.Path(str(spec["output_path"])).resolve()
    evidence_dir = output.parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cgkn_fixed10_clean_") as temporary:
        clean_root = pathlib.Path(temporary)
        project = clean_root / "delivered-project"
        shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".cgnk_test_env", "node_modules"))
        env_root = clean_root / "clean-venv"
        dependency = prepare_clean_environment(project, env_root, spec.get("dependency_policy"))
        python = _venv_python(env_root)
        static = static_checks(project, python) if dependency["status"] == "PASS" else {"status": "NOT_EVALUATED", "reason": "dependency preparation failed"}
        runtime = runtime_probe(project, python, str(case["case_id"]), evidence_dir) if dependency["status"] == "PASS" and static["status"] == "PASS" else {"status": "NOT_EVALUATED", "reason": "pre-runtime gate failed"}
        receipt = {
            "kind": "CGKNFixed10CleanRuntimeReceipt", "case_id": case["case_id"],
            "source_candidate": str(source), "fresh_project_root": str(project), "fresh_project_outside_cgkn": not str(project).lower().startswith(str(pathlib.Path(__file__).resolve().parents[2]).lower()),
            "host_python": sys.executable, "clean_environment": dependency, "static": static, "runtime": runtime,
        }
    candidate_hash = str(spec["candidate_sha256"])
    dependency_pass = dependency["status"] == "PASS"
    static_pass = static.get("status") == "PASS"
    runtime_pass = runtime.get("status") == "PASS"
    test_pass = static.get("generated_tests", {}).get("status") == "PASS"
    scenario_pass = 200 <= int(runtime.get("scenario", {}).get("status", 0) or 0) < 300 if runtime.get("mode") == "http" else runtime_pass and test_pass
    persistence_pass = runtime.get("restart", {}).get("status") == "PASS" if runtime.get("mode") == "http" else runtime_pass and test_pass
    browser_pass = runtime.get("browser", {}).get("status") == "PASS" if runtime.get("mode") == "http" else runtime_pass
    observations = [
        _observation(case, run_id, candidate_hash, "dependency.independent", dependency_pass, "benchmark_process_probe", json.dumps(dependency, ensure_ascii=False), failure_category="DEPENDENCY"),
    ]
    for criterion in case.get("hidden_acceptance", []):
        category = str(criterion.get("category", "functional"))
        if category == "runtime":
            passed, producer, failure = runtime_pass, "benchmark_process_probe", "RUNTIME"
        elif category == "persistence":
            passed, producer, failure = runtime_pass and test_pass and scenario_pass and persistence_pass, "benchmark_persistence_probe", "PERSISTENCE"
        elif category == "integration":
            passed, producer, failure = runtime_pass and test_pass and scenario_pass, "benchmark_http_probe", "INTEGRATION"
        else:
            passed, producer, failure = static_pass and test_pass and scenario_pass, "benchmark_http_probe" if runtime.get("mode") == "http" else "benchmark_process_probe", "CODE_GENERATION"
        observations.append(_observation(case, run_id, candidate_hash, str(criterion["id"]), passed, producer, json.dumps({"static": static, "runtime": runtime}, ensure_ascii=False), failure_category=failure, requirement_ids=[str(item) for item in criterion.get("requirement_ids", [])]))
    observations.extend([
        _observation(case, run_id, candidate_hash, "visual.independent", browser_pass, "benchmark_browser_probe", json.dumps(runtime.get("browser", runtime), ensure_ascii=False), failure_category="RUNTIME"),
        _observation(case, run_id, candidate_hash, "goal_fidelity.independent", static_pass and test_pass and scenario_pass, "benchmark_goal_fidelity_probe", "Independent clean-root scenario and generated regression tests exercised the requested primary flow.", failure_category="REQUIREMENT_UNDERSTANDING"),
        _observation(case, run_id, candidate_hash, "scope.independent", static_pass and runtime_pass, "benchmark_scope_probe", "Delivered project remained locally runnable without an external service or repository import.", failure_category="PLANNING"),
    ])
    _write(evidence_dir / "clean_runtime_receipt.json", receipt)
    result = {"kind": "ProjectBenchmarkExternalObservations", "observations": observations}
    _write(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        result = execute(args.input)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "PASS", "observation_count": len(result["observations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
