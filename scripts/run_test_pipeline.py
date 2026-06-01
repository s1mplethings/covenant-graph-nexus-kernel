#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RESULT_PATH = ROOT / "examples" / "test_results" / "test_pipeline_execution_result.json"
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "modular-project-testing"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_command(step: dict[str, Any]) -> dict[str, Any]:
    command = list(step.get("command", []))
    if not command:
        return {"id": step["id"], "status": "fail", "failures": ["missing command"], "stdout": "", "stderr": ""}
    if command[0] == "python":
        command[0] = sys.executable
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=int(step.get("timeout_seconds", 120)),
    )
    return {
        "id": step["id"],
        "kind": "command",
        "command": command,
        "status": "pass" if proc.returncode == 0 else "fail",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "failures": [] if proc.returncode == 0 else [f"command exited {proc.returncode}"],
    }


def project_path(step: dict[str, Any]) -> pathlib.Path | None:
    raw = str(step.get("project_dir", "")).strip()
    if not raw:
        return None
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def check_static_project_contract(step: dict[str, Any]) -> dict[str, Any]:
    project_dir = project_path(step)
    failures: list[str] = []
    if not project_dir or not project_dir.exists():
        failures.append("project_dir is missing or does not exist")
        return {"id": step["id"], "kind": "internal", "status": "fail", "failures": failures}
    required = ["index.html", "README.md"]
    for rel in required:
        if not (project_dir / rel).exists():
            failures.append(f"missing {rel}")
    index = (project_dir / "index.html").read_text(encoding="utf-8", errors="replace") if (project_dir / "index.html").exists() else ""
    if "<script" not in index:
        failures.append("index.html does not load any script")
    if "id=" not in index:
        failures.append("index.html has no stable DOM ids for test automation")
    app_candidates = ["app.js", "src/app.js"]
    if not any((project_dir / rel).exists() for rel in app_candidates):
        failures.append("missing browser app entrypoint: app.js or src/app.js")
    return {
        "id": step["id"],
        "kind": "internal",
        "status": "pass" if not failures else "fail",
        "project_dir": str(project_dir),
        "failures": failures,
    }


def check_browser_smoke_declared(step: dict[str, Any]) -> dict[str, Any]:
    project_dir = project_path(step)
    failures: list[str] = []
    if not project_dir or not project_dir.exists():
        failures.append("project_dir is missing or does not exist")
        return {"id": step["id"], "kind": "internal", "status": "fail", "failures": failures}
    test_path = project_dir / "tests" / "browser_smoke_test.js"
    if not test_path.exists():
        failures.append("missing tests/browser_smoke_test.js")
        return {"id": step["id"], "kind": "internal", "status": "fail", "project_dir": str(project_dir), "failures": failures}
    text = test_path.read_text(encoding="utf-8", errors="replace")
    if "window.runSmokeTest" not in text:
        failures.append("browser_smoke_test.js must expose window.runSmokeTest")
    forbidden = {
        "document.body.innerHTML = \"\"": "test destroys the app DOM",
        "document.body.innerHTML = ''": "test destroys the app DOM",
        "form.submit()": "test bypasses submit event listeners",
        "console.error": "test logs failures instead of throwing",
    }
    for snippet, message in forbidden.items():
        if snippet in text:
            failures.append(message)
    return {
        "id": step["id"],
        "kind": "internal",
        "status": "pass" if not failures else "fail",
        "project_dir": str(project_dir),
        "failures": failures,
    }


def check_runtime_artifacts(step: dict[str, Any]) -> dict[str, Any]:
    run_dir = pathlib.Path(str(step.get("run_dir", DEFAULT_RUN_DIR)))
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    artifacts = run_dir / "artifacts"
    required = ["pipeline_composition.json", "project_blueprint.json", "generation_trace.json", "test_graph.json", "effect_report.json", "runtime_result.json"]
    failures = [f"missing artifacts/{rel}" for rel in required if not (artifacts / rel).exists()]
    return {
        "id": step["id"],
        "kind": "internal",
        "status": "pass" if not failures else "fail",
        "run_dir": str(run_dir.resolve()),
        "failures": failures,
    }


def run_internal(step: dict[str, Any]) -> dict[str, Any]:
    check = step.get("check")
    if check == "static_project_contract":
        return check_static_project_contract(step)
    if check == "browser_smoke_declared":
        return check_browser_smoke_declared(step)
    if check == "runtime_artifact_inspection":
        return check_runtime_artifacts(step)
    return {"id": step["id"], "kind": "internal", "status": "fail", "failures": [f"unknown internal check: {check}"]}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def static_server(root: pathlib.Path):
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_browser_step(step: dict[str, Any]) -> dict[str, Any]:
    project_dir = project_path(step)
    failures: list[str] = []
    if not project_dir or not project_dir.exists():
        failures.append("project_dir is missing or does not exist")
        return {"id": step["id"], "kind": "browser", "status": "fail", "failures": failures}
    index_path = project_dir / "index.html"
    test_path = project_dir / str(step.get("test_file", "")).replace("/", "\\")
    if not index_path.exists():
        failures.append("missing index.html")
    if not test_path.exists():
        failures.append(f"missing {step.get('test_file')}")
    if failures:
        return {"id": step["id"], "kind": "browser", "status": "fail", "project_dir": str(project_dir), "failures": failures}
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return {
            "id": step["id"],
            "kind": "browser",
            "status": "fail",
            "project_dir": str(project_dir),
            "failures": [f"python playwright is unavailable: {exc}"],
        }
    function_name = str(step.get("function_name", "")).strip()
    timeout_ms = int(step.get("timeout_seconds", 60)) * 1000
    with static_server(project_dir) as base_url:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            console_errors: list[str] = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            try:
                page.goto(base_url + "/index.html", wait_until="networkidle", timeout=timeout_ms)
                page.add_script_tag(url=base_url + "/" + quote(str(step.get("test_file", "")).replace("\\", "/")))
                page.wait_for_function(f"typeof window.{function_name} === 'function'", timeout=timeout_ms)
                started = time.time()
                result = page.evaluate(f"() => window.{function_name}()")
                duration_ms = round((time.time() - started) * 1000)
            except Exception as exc:
                browser.close()
                return {
                    "id": step["id"],
                    "kind": "browser",
                    "status": "fail",
                    "project_dir": str(project_dir),
                    "url": base_url + "/index.html",
                    "failures": [str(exc)],
                    "console_errors": console_errors[-20:],
                }
            browser.close()
    return {
        "id": step["id"],
        "kind": "browser",
        "status": "pass",
        "project_dir": str(project_dir),
        "result": result,
        "duration_ms": duration_ms,
        "failures": [],
    }


def execute(plan_doc: dict[str, Any], result_path: pathlib.Path, run_dir: pathlib.Path) -> dict[str, Any]:
    plan = plan_doc.get("test_pipeline_plan", plan_doc)
    payload = plan.get("payload", {})
    steps = payload.get("steps", [])
    step_results: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []
    for step in steps:
        try:
            if step.get("kind") == "command":
                result = run_command(step)
            elif step.get("kind") == "browser":
                result = run_browser_step(step)
            else:
                result = run_internal(step)
        except subprocess.TimeoutExpired as exc:
            result = {"id": step.get("id", "<unknown>"), "status": "fail", "failures": [f"timeout after {exc.timeout}s"]}
        except Exception as exc:
            result = {"id": step.get("id", "<unknown>"), "status": "fail", "failures": [str(exc)]}
        step_results.append(result)
        if result.get("status") != "pass":
            messages = [f"{result.get('id')}: {failure}" for failure in result.get("failures", ["failed"])]
            if step.get("non_blocking") or step.get("gate") == "warning":
                warnings.extend(messages)
            else:
                failures.extend(messages)
    status = "pass" if not failures else "fail"
    live_api_steps = [
        str(step.get("id", ""))
        for step in steps
        if step.get("kind") == "command"
        and "scripts/check_connectivity.py" in " ".join(str(part) for part in step.get("command", []))
        and "--live" in [str(part) for part in step.get("command", [])]
    ]
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "kind": "TestExecutionReport",
        "created_at": now(),
        "payload": {
            "run_id": payload.get("target", {}).get("run_id", run_dir.name),
            "status": status,
            "target": payload.get("target", {}),
            "steps": step_results,
            "failures": failures,
            "warnings": warnings,
        },
    }
    validation_report = {
        "kind": "ValidationReport",
        "created_at": now(),
        "payload": {
            "passed": status == "pass",
            "failures": failures,
            "warnings": warnings,
            "step_count": len(step_results),
        },
    }
    effect_report = {
        "kind": "EffectReport",
        "created_at": now(),
        "payload": {
            "verdict": status,
            "summary": "Executed modular test pipeline with local deterministic checks and live API probes when declared.",
            "fs_read": ["scripts/**", "examples/**", "generated/**", "schemas/**"],
            "fs_write": [str(result_path), str(run_dir)],
            "network": "enabled" if live_api_steps else "disabled",
            "provider": "enabled for live connectivity probes" if live_api_steps else "disabled",
            "api_steps": live_api_steps,
        },
    }
    combined = {
        "kind": "ModularTestPipelineExecutionRun",
        "created_at": now(),
        "test_execution_report": report,
        "validation_report": validation_report,
        "effect_report": effect_report,
    }
    write_json(run_dir / "test_execution_report.json", report)
    write_json(run_dir / "validation_report.json", validation_report)
    write_json(run_dir / "effect_report.json", effect_report)
    write_json(result_path, combined)
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(ROOT / "examples" / "test_results" / "test_pipeline_composition_result.json"))
    parser.add_argument("--result-path", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    plan_path = pathlib.Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    result_path = pathlib.Path(args.result_path)
    if not result_path.is_absolute():
        result_path = ROOT / result_path
    run_dir = pathlib.Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    result = execute(read_json(plan_path), result_path.resolve(), run_dir.resolve())
    status = result["test_execution_report"]["payload"]["status"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"TEST_PIPELINE_EXECUTION: {status.upper()}")
        print(f"result={result_path.resolve()}")
        print(f"run_dir={run_dir.resolve()}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
