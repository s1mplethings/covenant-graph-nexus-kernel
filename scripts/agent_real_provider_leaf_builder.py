from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    import check_connectivity
    from agent_leaf_provider_guard import build_leaf_provider_prompt, build_provider_request, call_responses_provider, classify_provider_error, provider_readiness, redact_secret, save_redacted_provider_request
    from agent_leaf_scope_enforcer import enforce_leaf_scope
    from agent_scope_contract import load_scope_contract
    from agent_tree_contracts import append_jsonl, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts import check_connectivity
    from scripts.agent_leaf_provider_guard import build_leaf_provider_prompt, build_provider_request, call_responses_provider, classify_provider_error, provider_readiness, redact_secret, save_redacted_provider_request
    from scripts.agent_leaf_scope_enforcer import enforce_leaf_scope
    from scripts.agent_scope_contract import load_scope_contract
    from scripts.agent_tree_contracts import append_jsonl, write_json


def parse_provider_files(raw_text: str) -> dict[str, str]:
    raw = str(raw_text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    first = raw.find("{")
    last = raw.rfind("}")
    candidate = raw[first : last + 1] if first >= 0 and last > first else raw
    try:
        doc = json.loads(candidate)
    except json.JSONDecodeError:
        return _salvage_provider_files(candidate)
    files = doc.get("files", [])
    if not isinstance(files, list):
        return {}
    result: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).replace("\\", "/").strip()
        content = item.get("content", "")
        if path and isinstance(content, str):
            result[path] = content
    return result


def _salvage_provider_files(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    path_pattern = re.compile(r'"path"\s*:\s*"([^"]+)"\s*,\s*"content"\s*:\s*"', flags=re.S)
    matches = list(path_pattern.finditer(raw))
    for index, match in enumerate(matches):
        path = match.group(1).replace("\\\\", "/").replace("\\", "/").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else raw.rfind("}")
        chunk = raw[start:end]
        # Provider sometimes returns raw newlines inside JSON strings. Trim only the structural tail.
        for tail in ('"}', '"}]', '"}]}'):
            pos = chunk.rfind(tail)
            if pos >= 0:
                chunk = chunk[:pos]
                break
        chunk = chunk.rstrip().rstrip(",")
        content = chunk.replace('\\"', '"').replace("\\n", "\n")
        if path:
            result[path] = content
    return result


def _call_provider(prompt: str, *, model: str, timeout: int) -> tuple[str, str]:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    root = str(creds.get("base_url", "")).strip()
    payload = build_provider_request(model=model, prompt=prompt, base_url=root)
    doc, error, _attempts = call_responses_provider(
        base_url=root,
        token=token,
        payload=payload,
        timeout=timeout,
    )
    if error:
        return "", error
    if not doc:
        return "", "empty provider response"
    return check_connectivity._extract_text(doc), ""


def _repair_prompt(base_prompt: str, *, classification: str, missing: list[str], test_result: dict[str, Any] | None) -> str:
    details = [
        base_prompt,
        "",
        "Previous real provider attempt did not pass. Return a complete replacement JSON response.",
        f"failure_classification: {classification}",
        f"missing_files: {json.dumps(missing, ensure_ascii=False)}",
    ]
    if test_result:
        details.extend(
            [
                f"test_command: {test_result.get('command', '')}",
                f"test_exit_code: {test_result.get('exit_code')}",
                "test_stdout_tail:",
                str(test_result.get("stdout_tail", ""))[-1200:],
                "test_stderr_tail:",
                str(test_result.get("stderr_tail", ""))[-1200:],
            ]
        )
    details.append("Do not add files outside allowed_files. Include every allowed file exactly once.")
    return "\n".join(details)


def _prepare_python_test_harness(project: pathlib.Path, allowed_files: list[str]) -> list[str]:
    scaffold: list[str] = []
    package_dirs: set[pathlib.Path] = set()
    for rel in allowed_files:
        path = pathlib.PurePosixPath(str(rel).replace("\\", "/"))
        if path.suffix != ".py" or not path.parts or path.parts[0] != "app":
            continue
        current = pathlib.Path(path.parts[0])
        package_dirs.add(current)
        for part in path.parts[1:-1]:
            current = current / part
            package_dirs.add(current)
    for rel_dir in sorted(package_dirs, key=lambda item: len(item.parts)):
        marker = project / rel_dir / "__init__.py"
        if marker.exists():
            continue
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
        scaffold.append(str((rel_dir / "__init__.py").as_posix()))
    return scaffold


def _test_leaf_read_context(project: pathlib.Path, agent_id: str) -> str:
    if agent_id not in {"smoke_test_leaf", "backend_tests_leaf", "backend_tests_leaf_v2", "ui_route_tests_leaf", "ui_route_tests_leaf_v2"}:
        return ""
    candidates = ["app/main.py", "app/routes.py"]
    if agent_id.startswith("backend_tests_leaf"):
        candidates.extend(
            [
                "app/services/document_import_service.py",
                "app/services/search_service.py",
                "app/services/task_service.py",
                "app/services/report_service.py",
                "app/services/model_adapter.py",
            ]
        )
    sections: list[str] = []
    for rel in candidates:
        path = project / rel
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        sections.append(f"--- {rel} (read-only) ---\n{content[:5000]}")
    if not sections:
        return ""
    return (
        "\nExisting integrated project context follows. It is read-only and may be imported by the generated test. "
        "Do not assume a framework or API that is absent from this context.\n"
        + "\n".join(sections)
    )


def run_real_provider_leaf(
    *,
    agent_id: str,
    out_dir: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    user_goal: str,
    model: str = "gpt-5.4-nano",
    readiness: dict[str, Any] | None = None,
    provider_output_override: str | None = None,
    timeout: int = 90,
    max_repair_attempts: int = 1,
    run_leaf_tests: bool = True,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    project = pathlib.Path(project_dir)
    out.mkdir(parents=True, exist_ok=True)
    contract = load_scope_contract(out, agent_id)
    allowed_files = list(contract.get("allowed_files", []))
    forbidden_files = list(contract.get("forbidden_files", []))
    ready = readiness if isinstance(readiness, dict) else provider_readiness(out_dir=out, model=model)
    prompt = build_leaf_provider_prompt(agent_id=agent_id, allowed_files=allowed_files, forbidden_files=forbidden_files, user_goal=user_goal)
    prompt += _test_leaf_read_context(project, agent_id)
    request_doc = build_provider_request(model=model, prompt=prompt)
    save_redacted_provider_request(out_dir=out, request_doc=request_doc, prompt=prompt)
    if not ready.get("provider_ready") and provider_output_override is None:
        result = {
            "classification": "provider_unavailable",
            "verdict": "BLOCKED",
            "checkpoint": "FAIL",
            "agent_id": agent_id,
            "provider_ready": False,
            "allowed_files": allowed_files,
            "forbidden_write_attempts": [],
        }
        write_json(out / f"checkpoint_{agent_id}.json", result)
        return result

    attempts_allowed = 1 if provider_output_override is not None else max(1, int(max_repair_attempts) + 1)
    classification = "real_provider_leaf_missing_files"
    checkpoint = "FAIL"
    enforcement: dict[str, Any] = {"blocked_files": [], "written_files": []}
    harness_scaffold_files: list[str] = []
    test_result: dict[str, Any] = {}
    missing: list[str] = []
    current_prompt = prompt
    for attempt in range(1, attempts_allowed + 1):
        if provider_output_override is not None:
            raw_text = provider_output_override
            provider_error = ""
        else:
            raw_text, provider_error = _call_provider(current_prompt, model=model, timeout=timeout)
        (out / "provider_output_raw_redacted.txt").write_text(redact_secret(raw_text or provider_error), encoding="utf-8")
        append_jsonl(out / "provider_attempts.jsonl", {"attempt": attempt, "provider_error": bool(provider_error), "raw_length": len(raw_text or provider_error or "")})
        if provider_error:
            provider_failure = classify_provider_error(provider_error)
            result = {
                **provider_failure,
                "checkpoint": "FAIL",
                "agent_id": agent_id,
                "attempt": attempt,
            }
            write_json(out / f"checkpoint_{agent_id}.json", result)
            return result

        try:
            files = parse_provider_files(raw_text)
        except Exception as exc:
            files = {}
            parse_error = str(exc)
        else:
            parse_error = ""
        write_json(out / "provider_output_files.json", {"files": [{"path": path, "content_length": len(content)} for path, content in files.items()], "parse_error": parse_error, "attempt": attempt})
        enforcement = enforce_leaf_scope(contract=contract, candidate_files=files, project_dir=project, out_dir=out, write_allowed=True)
        if enforcement["blocked_files"]:
            classification = "real_provider_leaf_scope_violation_blocked"
            checkpoint = "FAIL"
            break
        missing = [path for path in allowed_files if not (project / path).exists()]
        if missing:
            classification = "real_provider_leaf_missing_files"
            checkpoint = "FAIL"
        else:
            harness_scaffold_files = _prepare_python_test_harness(project, allowed_files)
            test_file = next((path for path in allowed_files if path.startswith("tests/") and path.endswith(".py")), "")
            if test_file and run_leaf_tests:
                env = os.environ.copy()
                env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
                python_paths = [str(project.resolve())]
                if env.get("PYTHONPATH"):
                    python_paths.append(env["PYTHONPATH"])
                env["PYTHONPATH"] = os.pathsep.join(python_paths)
                proc = subprocess.run([sys.executable, "-m", "pytest", test_file], cwd=project, capture_output=True, text=True, timeout=60, env=env)
                test_result = {"exit_code": proc.returncode, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:], "command": f"python -m pytest {test_file}"}
            elif test_file:
                test_result = {"exit_code": 0, "stdout_tail": "", "stderr_tail": "", "command": f"deferred pytest for {test_file}", "deferred": True}
            else:
                test_result = {"exit_code": 0, "stdout_tail": "", "stderr_tail": "", "command": ""}
            write_json(out / "test_execution_result.json", test_result)
            classification = "real_provider_leaf_pass" if test_result["exit_code"] == 0 else "real_provider_leaf_test_failed"
            checkpoint = "PASS" if classification == "real_provider_leaf_pass" else "FAIL"
        append_jsonl(out / "repair_attempts.jsonl", {"attempt": attempt, "classification": classification, "checkpoint": checkpoint, "missing_files": missing, "test_exit_code": test_result.get("exit_code")})
        if checkpoint == "PASS" or attempt >= attempts_allowed or provider_output_override is not None:
            break
        current_prompt = _repair_prompt(prompt, classification=classification, missing=missing, test_result=test_result)
    result = {
        "classification": classification,
        "verdict": "PASS" if classification == "real_provider_leaf_pass" else "NEEDS_REWORK",
        "checkpoint": checkpoint,
        "agent_id": agent_id,
        "provider_ready": bool(ready.get("provider_ready") or provider_output_override is not None),
        "allowed_files": allowed_files,
        "forbidden_write_attempts": enforcement["blocked_files"],
        "written_files": enforcement["written_files"],
        "harness_scaffold_files": harness_scaffold_files if "harness_scaffold_files" in locals() else [],
        "repair_attempts": attempts_allowed,
    }
    write_json(out / f"checkpoint_{agent_id}.json", result)
    return result
