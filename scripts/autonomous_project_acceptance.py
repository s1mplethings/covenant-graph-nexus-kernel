#!/usr/bin/env python3
"""Production integration for contract-driven autonomous project acceptance.

The module consumes one declarative Testability Contract, reuses the Pass 3
model client and validation evidence primitives, executes only real public
project entrypoints in isolated copies, applies deterministic oracles, and
reproduces every issue in a second fresh copy.  Its recommendation status is
deliberately separate from CGKN formal EvidenceStatus and delivery authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from typing import Any

from jsonschema import Draft202012Validator


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import adaptive_autonomous_validation as adaptive
import autonomous_validation_pass3 as p3
import role_driven_validation as v1
import repair_evidence_contract


KIND = "CGKNAutonomousProjectAcceptanceReport"
SCHEMA_VERSION = "1.0"
FORMAL_STATUS = "NOT_EVALUATED"
RECOMMENDATION_STATUSES = {"ACCEPTED", "REPAIR_REQUIRED", "BLOCKED", "NOT_EVALUATED"}
CONTRACT_FILE = "testability_contract.json"
REPORT_FILE = "autonomous_acceptance_report.json"
MODEL_CALL_LIMIT = 1
SEMANTIC_ACTION_LIMIT = 4


class AcceptanceError(RuntimeError):
    pass


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    v1.write_json(path, value)
    return path


def _hash(value: Any) -> str:
    return p3.canonical_hash(value)


def plain_tree_hash(root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    excluded = {"__pycache__", ".pytest_cache", ".git"}
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _contract_schema() -> dict[str, Any]:
    return _read(ROOT / "schemas" / "testability_contract_v1.schema.json")


def _safe_relative(root: pathlib.Path, value: str) -> pathlib.Path:
    raw = str(value or "").replace("\\", "/").strip()
    candidate = (root / raw).resolve()
    if not raw or pathlib.PurePosixPath(raw).is_absolute() or candidate != root and root not in candidate.parents:
        raise AcceptanceError(f"unsafe contract path: {value}")
    return candidate


def validate_contract(contract: dict[str, Any], project: pathlib.Path) -> list[str]:
    errors = [error.message for error in sorted(Draft202012Validator(_contract_schema()).iter_errors(contract), key=lambda item: list(item.path))]
    if errors:
        return errors
    operation_ids = [str(item["id"]) for item in contract["operations"]]
    if len(operation_ids) != len(set(operation_ids)):
        errors.append("operation ids must be unique")
    known = set(operation_ids)
    for scenario in contract["scenarios"]:
        for step in scenario["steps"]:
            if step["operation"] not in known:
                errors.append(f"scenario {scenario['id']} references unknown operation {step['operation']}")
    adapter = contract["adapter"]
    entrypoint = _safe_relative(project, adapter["business_logic_entrypoint"])
    if not entrypoint.is_file():
        errors.append("business logic entrypoint does not exist")
    for record in [*contract["observable_state"], *contract["final_artifacts"]]:
        try:
            _safe_relative(project, record["path"])
        except AcceptanceError as exc:
            errors.append(str(exc))
    forbidden = re.compile(r"(?:^|[\\/_.-])(test|fixture|mock|fake|stub)(?:[\\/_.-]|$)", re.I)
    for operation in contract["operations"]:
        argv_text = " ".join(operation["argv"])
        if forbidden.search(argv_text):
            errors.append(f"operation {operation['id']} uses a test-only entrypoint")
        if operation["argv"][0].lower() not in {"python", "python3", "py", "node"}:
            errors.append(f"operation {operation['id']} executable is outside the allowlist")
        if "-c" in operation["argv"] or "--eval" in operation["argv"]:
            errors.append(f"operation {operation['id']} uses inline code")
        for path in [*operation.get("affected_files", []), *operation["oracle"].get("state_paths", []), *operation["oracle"].get("required_artifacts", [])]:
            try:
                _safe_relative(project, path)
            except AcceptanceError as exc:
                errors.append(str(exc))
    if contract["adapter"]["type"] != "cli":
        errors.append("this minimum integration currently requires a CLI contract; other adapters are unsupported")
    return sorted(set(errors))


def adapter_assessment(project: pathlib.Path) -> dict[str, Any]:
    readme = project / "README.md"
    text = readme.read_text(encoding="utf-8", errors="replace") if readme.is_file() else ""
    entrypoints = [name for name in ("main.py", "app.py", "package.json") if (project / name).is_file()]
    commands = re.findall(r"(?:python|python3|py|node)\s+[A-Za-z0-9_./-]+[^\r\n`]*", text, flags=re.I)
    can_generate = bool(entrypoints and commands)
    return {
        "contract_present": (project / CONTRACT_FILE).is_file(),
        "documented_entrypoints": entrypoints,
        "documented_command_examples": commands[:12],
        "isolated_adapter_feasible": can_generate,
        "reason": "documented CLI examples can be converted into a reviewed isolated adapter" if can_generate else "no complete declarative operation and oracle contract is available",
    }


def _copy_project(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc", REPORT_FILE))
    return target


def _windows_execution_path_too_long(
    path: pathlib.Path, *, platform_name: str | None = None
) -> bool:
    return (platform_name or os.name) == "nt" and len(str(path.resolve())) >= 240


def _snapshot(project: pathlib.Path, paths: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for relative in paths:
        path = _safe_relative(project, relative)
        if not path.is_file():
            result[relative] = {"exists": False, "sha256": "", "value": None}
            continue
        value: Any = None
        if path.suffix.lower() == ".json":
            value = _read(path)
            if not value:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    value = None
        result[relative] = {"exists": True, "sha256": v1.file_hash(path), "value": p3.safe_json(value)}
    return result


def _render_arg(token: str, args: dict[str, Any]) -> str:
    pattern = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
    matched = pattern.fullmatch(token)
    if not matched:
        if "{" in token or "}" in token:
            raise AcceptanceError("argv templates must use a whole-token {argument} placeholder")
        return token
    name = matched.group(1)
    if name not in args:
        raise AcceptanceError(f"missing operation argument: {name}")
    value = args[name]
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _safe_env(project: pathlib.Path) -> dict[str, str]:
    blocked = {"CGKN_OPENAI_API_KEY_OVERRIDE", "CGKN_OPENAI_API_KEY", "OPENAI_API_KEY", "QWEN_API_KEY"}
    env = {key: value for key, value in os.environ.items() if key not in blocked}
    env.update({"PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1", "APP_ENV": "test"})
    return env


def _operation_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in contract["operations"]}


def _declared_path_arguments(operation: dict[str, Any]) -> set[str]:
    """Return placeholders explicitly used as CLI path/output arguments."""
    result: set[str] = set()
    argv = operation.get("argv", [])
    placeholder = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
    for index, token in enumerate(argv):
        matched = placeholder.fullmatch(str(token))
        previous = str(argv[index - 1]).casefold() if index else ""
        if matched and previous.startswith("-") and any(
            marker in previous
            for marker in ("out", "output", "path", "file", "dest", "destination")
        ):
            result.add(matched.group(1))
    return result


def _safe_declared_path_value(value: Any) -> bool:
    text = str(value).strip()
    if not text:
        return False
    posix = pathlib.PurePosixPath(text.replace("\\", "/"))
    windows = pathlib.PureWindowsPath(text)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and ".." not in posix.parts
    )


def validate_action(contract: dict[str, Any], action: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(action, dict):
        return None, {"reason": "proposal_not_object", "proposal": p3.safe_json(action)}
    operations = _operation_map(contract)
    operation_id = str(action.get("operation") or action.get("op") or "").strip()
    if operation_id not in operations:
        return None, {"reason": "unsupported_operation", "operation": operation_id, "proposal": p3.safe_json(action)}
    args = action.get("args") or {}
    schema = operations[operation_id]["input_schema"]
    errors = [item.message for item in Draft202012Validator(schema).iter_errors(args)]
    if errors:
        return None, {"reason": "schema_invalid", "operation": operation_id, "schema_errors": errors, "proposal": p3.safe_json(action)}
    unsafe_paths = [
        name
        for name in sorted(_declared_path_arguments(operations[operation_id]))
        if name in args and not _safe_declared_path_value(args[name])
    ]
    if unsafe_paths:
        return None, {
            "reason": "unsafe_path_argument",
            "operation": operation_id,
            "arguments": unsafe_paths,
            "proposal": p3.safe_json(action),
        }
    return {
        "operation": operation_id,
        "args": p3.safe_json(args),
        "hypothesis": str(action.get("hypothesis") or "")[:800],
        "business_value": str(action.get("business_value") or "")[:800],
        "source": str(action.get("source") or "semantic"),
    }, None


def _execute(project: pathlib.Path, contract: dict[str, Any], action: dict[str, Any], index: int) -> dict[str, Any]:
    operation = _operation_map(contract)[action["operation"]]
    args = action["args"]
    argv = [_render_arg(token, args) for token in operation["argv"]]
    first = argv[0].lower()
    if first in {"python", "python3", "py"}:
        argv[0] = sys.executable
    tracked = list(dict.fromkeys([*operation["oracle"].get("state_paths", []), *operation["oracle"].get("required_artifacts", [])]))
    before = _snapshot(project, tracked)
    result = v1.run_process(argv, cwd=_safe_relative(project, contract["adapter"]["working_directory"]), env=_safe_env(project), timeout=int(contract["execution_limits"]["timeout_seconds"]))
    after = _snapshot(project, tracked)
    parsed = None
    if operation["oracle"]["stdout_format"] == "json":
        try:
            parsed = json.loads(str(result.get("stdout") or ""))
        except ValueError:
            parsed = None
    row = {
        "observation_id": f"obs-{index:03d}",
        "operation": action["operation"],
        "args": args,
        "argv": ["<python>" if pos == 0 and first in {"python", "python3", "py"} else token for pos, token in enumerate(argv)],
        "returncode": int(result["returncode"]),
        "stdout": str(result.get("stdout") or ""),
        "stderr": str(result.get("stderr") or ""),
        "result": p3.safe_json(parsed),
        "before": before,
        "after": after,
        "duration_seconds": float(result.get("duration_seconds") or 0),
        "hypothesis": action.get("hypothesis", ""),
        "business_value": action.get("business_value", ""),
        "source": action.get("source", ""),
    }
    row["independent_issues"] = operation_oracle(operation, row)
    return row


def _issue(code: str, summary: str, operation: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_type": code,
        "summary": summary,
        "oracle_kind": "deterministic",
        "details": {"operation": row["operation"], "args": row["args"], "returncode": row["returncode"], "stderr": row["stderr"], "before": row["before"], "after": row["after"]},
        "observation_id": row["observation_id"],
        "affected_files": list(operation.get("affected_files", [])),
    }


def operation_oracle(operation: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    oracle = operation["oracle"]
    if row["returncode"] not in operation["expected_exit_codes"]:
        issues.append(_issue("unexpected_exit_code", "The public operation returned an exit code outside its contract.", operation, row))
    if oracle["stdout_format"] == "json":
        if row["result"] is None:
            issues.append(_issue("invalid_json_output", "The operation did not produce the contracted JSON output.", operation, row))
        elif oracle.get("stdout_schema"):
            errors = [item.message for item in Draft202012Validator(oracle["stdout_schema"]).iter_errors(row["result"])]
            if errors:
                issues.append(_issue("stdout_schema_mismatch", "The JSON output violates the public output contract: " + "; ".join(errors), operation, row))
    changed = any(row["before"].get(path, {}).get("sha256") != row["after"].get(path, {}).get("sha256") for path in oracle.get("state_paths", []))
    if oracle["state_change"] == "must_change" and not changed:
        issues.append(_issue("state_not_changed", "The operation succeeded without the required persisted state change.", operation, row))
    if oracle["state_change"] == "must_not_change" and changed:
        issues.append(_issue("unexpected_state_change", "The operation changed persisted state that must remain unchanged.", operation, row))
    for relative in oracle.get("required_artifacts", []):
        if not row["after"].get(relative, {}).get("exists"):
            issues.append(_issue("required_artifact_missing", f"The required final artifact {relative} was not created.", operation, row))
    return issues


def _json_pointer(value: Any, pointer: str) -> Any:
    current = value
    if pointer in {"", "/"}:
        return current
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def scenario_oracle(project: pathlib.Path, scenario: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, condition in enumerate(scenario["success_conditions"]):
        path = _safe_relative(project, condition["path"])
        passed = False
        observed: Any = None
        try:
            if condition["kind"] == "file_exists":
                passed, observed = path.is_file(), path.is_file()
            elif condition["kind"] == "text_contains":
                observed = path.read_text(encoding="utf-8", errors="replace")
                passed = str(condition.get("contains", "")) in observed
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
                observed = _json_pointer(value, str(condition.get("pointer", "")))
                expected = condition.get("expected")
                if condition["kind"] == "json_pointer_number_equals":
                    passed = abs(float(observed) - float(expected)) < 1e-9
                else:
                    passed = observed == expected
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            passed = False
        if not passed:
            issues.append({
                "issue_type": "scenario_success_condition_failed",
                "summary": f"User task {scenario['id']} did not satisfy {condition['kind']} for {condition['path']}.",
                "oracle_kind": "deterministic",
                "details": {"scenario_id": scenario["id"], "condition_index": index, "condition": condition, "observed": p3.safe_json(observed)},
                "observation_id": f"scenario-{scenario['id']}",
                "affected_files": [condition["path"]],
            })
    return issues


def deterministic_actions(contract: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for scenario in contract["scenarios"]:
        for step in scenario["steps"]:
            actions.append({"operation": step["operation"], "args": step["args"], "hypothesis": scenario["user_task"], "business_value": scenario["user_task"], "source": "deterministic"})
    return actions


def semantic_prompt(contract: dict[str, Any], public_goal: str, observations: list[dict[str, Any]]) -> str:
    operations = {item["id"]: {"description": item["description"], "input_schema": item["input_schema"]} for item in contract["operations"]}
    return "\n".join([
        "Propose a one-shot set of black-box user tasks for a real generated project.",
        "Use only operation names and arguments allowed by OPERATIONS. Do not claim success or a defect.",
        "Do not use tests, hidden answers, evaluator code, or internal implementation details.",
        f"Return JSON only with an actions array of at most {SEMANTIC_ACTION_LIMIT} items. Each item has operation, args, hypothesis, business_value.",
        f"PUBLIC_GOAL={public_goal[:6000]}",
        f"OPERATIONS={json.dumps(operations, ensure_ascii=False)}",
        f"PRIOR_PUBLIC_OBSERVATIONS={json.dumps(observations[-6:], ensure_ascii=False)}",
    ])


def semantic_actions(contract: dict[str, Any], public_goal: str, model_client: p3.ModelClient) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    response = model_client.call(semantic_prompt(contract, public_goal, []), project_id="generated_project", group="semantic", round_index=1)
    raw = response["document"].get("actions")
    if not isinstance(raw, list):
        raise AcceptanceError("semantic model response lacks an actions array")
    actions: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for index, proposal in enumerate(raw[:SEMANTIC_ACTION_LIMIT]):
        action, rejected = validate_action(contract, proposal)
        if rejected:
            unsupported.append({"proposal_index": index, **rejected, "executed": False, "auto_mapped": False})
        elif action:
            actions.append(action)
    return actions, unsupported, response["receipt"]


def _execute_sequence(
    project: pathlib.Path,
    contract: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    start_index: int = 1,
    evaluate_scenarios: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [
        _execute(project, contract, action, index)
        for index, action in enumerate(actions, start=start_index)
    ]
    scenario_issues = (
        [issue for scenario in contract["scenarios"] for issue in scenario_oracle(project, scenario)]
        if evaluate_scenarios
        else []
    )
    return rows, scenario_issues


def _finding_rows(rows: list[dict[str, Any]], scenario_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, issue in [(index, issue) for index, row in enumerate(rows) for issue in row["independent_issues"]] + [(len(rows) - 1, issue) for issue in scenario_issues]:
        key = f"{issue['issue_type']}:{_hash(issue.get('details', {}))[:12]}"
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "finding_id": "FINDING-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12].upper(),
            "finding_key": key,
            "issue_type": issue["issue_type"],
            "summary": issue["summary"],
            "details": issue["details"],
            "oracle_kind": issue["oracle_kind"],
            "action_index": max(index, 0),
            "affected_files": issue.get("affected_files", []),
            "independently_confirmed": False,
            "false_positive": False,
        })
    return result


def _reproduce(source: pathlib.Path, contract: dict[str, Any], actions: list[dict[str, Any]], finding: dict[str, Any], run_dir: pathlib.Path) -> None:
    reproduction = run_dir / "reproduction" / finding["finding_id"]
    evidence_project = _copy_project(source, reproduction / "project")
    short_root: pathlib.Path | None = None
    project = evidence_project
    if _windows_execution_path_too_long(evidence_project):
        short_root = pathlib.Path(tempfile.mkdtemp(prefix="cgkn-aa-repro-"))
        project = _copy_project(source, short_root / "project")
    prefix = actions[: finding["action_index"] + 1]
    try:
        rows, scenario_issues = _execute_sequence(project, contract, prefix)
        if short_root is not None:
            shutil.rmtree(evidence_project)
            _copy_project(project, evidence_project)
    finally:
        if short_root is not None:
            shutil.rmtree(short_root, ignore_errors=True)
    reproduced_types = {issue["issue_type"] for row in rows for issue in row["independent_issues"]} | {issue["issue_type"] for issue in scenario_issues}
    reproduced = finding["issue_type"] in reproduced_types
    finding.update({"independently_confirmed": reproduced, "false_positive": not reproduced, "reproduction_ref": str(reproduction / "execution.json"), "reproduction_actions": len(prefix)})
    _write(reproduction / "execution.json", {"actions": prefix, "observations": rows, "scenario_issues": scenario_issues})


def _blocked_report(project: pathlib.Path, run_dir: pathlib.Path, reason: str, details: list[str]) -> dict[str, Any]:
    report = {
        "kind": KIND, "schema_version": SCHEMA_VERSION, "created_at": p3.now(),
        "recommendation_status": "BLOCKED", "formal_evidence_status": FORMAL_STATUS,
        "release_authority": False, "project_dir": str(project), "candidate_source_hash": p3.tree_hash(project),
        "testability_contract_ref": str(project / CONTRACT_FILE), "adapter_assessment": adapter_assessment(project),
        "reason": reason, "blockers": details, "actions": [], "observations": [], "findings": [],
        "model_calls": [], "invalid_proposals": 0, "invalid_executions": 0,
        "all_findings_reproduced": False, "repair_evidence_ref": "", "known_limits": [],
    }
    report["report_sha256"] = _hash(report)
    _write(run_dir / REPORT_FILE, report)
    return report


def run_acceptance(
    project_dir: str | pathlib.Path,
    run_dir: str | pathlib.Path,
    *,
    public_goal: str,
    model: str = p3.DEFAULT_MODEL,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
) -> dict[str, Any]:
    source = pathlib.Path(project_dir).resolve()
    root = pathlib.Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    contract_path = source / CONTRACT_FILE
    if not contract_path.is_file():
        return _blocked_report(source, root, "testability_contract_missing", ["No verified Testability Contract is available; the project cannot be accepted from interface absence."])
    contract = _read(contract_path)
    errors = validate_contract(contract, source)
    if errors:
        return _blocked_report(source, root, "testability_contract_invalid", errors)
    source_copy = _copy_project(source, root / "candidate-source")
    evidence_execution_project = _copy_project(source, root / "execution" / "project")
    short_execution_root: pathlib.Path | None = None
    execution_project = evidence_execution_project
    if _windows_execution_path_too_long(evidence_execution_project):
        short_execution_root = pathlib.Path(tempfile.mkdtemp(prefix="cgkn-aa-"))
        execution_project = _copy_project(source, short_execution_root / "project")
    deterministic = deterministic_actions(contract)
    if len(deterministic) > int(contract["execution_limits"]["max_operations"]):
        return _blocked_report(source, root, "deterministic_operation_budget_exceeded", [f"{len(deterministic)} operations exceed the contract budget"])
    client = p3.ModelClient(model=model, timeout=min(90, int(contract["execution_limits"]["timeout_seconds"])), input_price_per_million=input_price_per_million, output_price_per_million=output_price_per_million)
    try:
        semantic, unsupported, _receipt = semantic_actions(contract, public_goal, client)
    except Exception as exc:
        return _blocked_report(source, root, "semantic_explorer_unavailable", [f"{type(exc).__name__}: {exc}"])
    actions = deterministic + semantic
    maximum = int(contract["execution_limits"]["max_operations"])
    actions = actions[:maximum]
    try:
        deterministic_rows, scenario_issues = _execute_sequence(
            execution_project, contract, deterministic
        )
        semantic_project = _copy_project(
            source,
            (
                short_execution_root / "semantic-project"
                if short_execution_root is not None
                else root / "execution-semantic" / "project"
            ),
        )
        semantic_rows, _ = _execute_sequence(
            semantic_project,
            contract,
            semantic,
            start_index=len(deterministic_rows) + 1,
            evaluate_scenarios=False,
        )
        rows = deterministic_rows + semantic_rows
        if short_execution_root is not None:
            shutil.rmtree(evidence_execution_project)
            _copy_project(execution_project, evidence_execution_project)
            _copy_project(semantic_project, root / "execution-semantic" / "project")
            execution_project = evidence_execution_project
    finally:
        if short_execution_root is not None:
            shutil.rmtree(short_execution_root, ignore_errors=True)
    _write(root / "raw_execution.json", {"actions": actions, "observations": rows, "scenario_issues": scenario_issues})
    compressed = [adaptive.compress_observation({"observation_id": row["observation_id"], "op": row["operation"], **row}, str(root / "raw_execution.json")) for row in rows]
    compression = adaptive.compression_audit([{"observation_id": row["observation_id"], "op": row["operation"], **row} for row in rows], compressed)
    findings = _finding_rows(rows, scenario_issues)
    for finding in findings:
        _reproduce(source, contract, actions, finding, root)
    valid = [item for item in findings if item["independently_confirmed"]]
    status = "REPAIR_REQUIRED" if valid else "ACCEPTED"
    if any(not item["independently_confirmed"] for item in findings) or compression["status"] != "PASS":
        status = "BLOCKED"
    evidence = {}
    repair_ref = ""
    if status == "REPAIR_REQUIRED":
        failures = [
                {
                    "criterion_id": item["finding_id"], "status": "FAIL",
                    "failure_category": item["issue_type"], "observed_behavior": item["summary"],
                    "details": item["details"], "failure_stack": "",
                    "affected_files": item["affected_files"], "affected_work_nodes": [],
                    "reproduction_ref": item["reproduction_ref"],
                }
                for item in valid
            ]
        evidence = repair_evidence_contract.build(
            run_id=root.name,
            project_id=source.name,
            user_goal=public_goal,
            candidate_dir=source_copy,
            candidate_sha256=plain_tree_hash(source_copy),
            repair_round=1,
            failure_category=str(valid[0].get("issue_type", "TEST")) if valid else "TEST",
            failures=failures,
            repair_eligible=True,
            blocking_reason="",
            constraints={
                "maximum_total_rounds": 2,
                "manual_candidate_edits_forbidden": True,
                "provider_scope": "affected_jobs_only",
            },
        )
        repair_path = _write(root / "observed_project_failure.json", evidence)
        repair_ref = str(repair_path)
    report = {
        "kind": KIND, "schema_version": SCHEMA_VERSION, "created_at": p3.now(),
        "recommendation_status": status, "formal_evidence_status": FORMAL_STATUS,
        "release_authority": False, "project_dir": str(source), "candidate_source_hash": p3.tree_hash(source),
        "testability_contract_ref": str(contract_path), "testability_contract_sha256": v1.file_hash(contract_path),
        "adapter_assessment": adapter_assessment(source), "reason": "validation_complete",
        "blockers": [] if status == "ACCEPTED" else [item["summary"] for item in valid],
        "actions": actions, "observations": compressed, "raw_execution_ref": str(root / "raw_execution.json"),
        "findings": findings, "model_calls": client.calls, "invalid_proposals": len(unsupported),
        "unsupported_proposals": unsupported, "invalid_executions": 0,
        "all_findings_reproduced": all(item["independently_confirmed"] for item in findings),
        "compression_audit": compression, "repair_evidence_ref": repair_ref,
        "known_limits": ["CLI/File minimum integration only; GUI and HTTP are not inferred.", "Recommendation status cannot replace formal CGKN evidence or delivery gates."],
    }
    report["report_sha256"] = _hash(report)
    _write(root / REPORT_FILE, report)
    return report


def acceptance_audit(report: dict[str, Any]) -> dict[str, Any]:
    status = str(report.get("recommendation_status", "NOT_EVALUATED"))
    if status == "ACCEPTED":
        return {"action": "resume", "scope": "none", "audit_status": "autonomous_acceptance_complete"}
    return {
        "action": "rework_project" if status == "REPAIR_REQUIRED" else "halt",
        "scope": "project" if status == "REPAIR_REQUIRED" else "safety",
        "audit_status": "autonomous_acceptance_rejected",
        "summary": f"Autonomous project acceptance recommendation is {status}.",
        "diagnosis": list(report.get("blockers", [])),
        "guidance": ["Use the existing ProviderJob repair route, then rerun the exact failed and previously passing scenarios."],
        "acceptance_checks": [str(item.get("finding_id", "")) for item in report.get("findings", [])],
        "repair_targets": list(dict.fromkeys(path for item in report.get("findings", []) for path in item.get("affected_files", []))),
        "report_ref": str(report.get("report_ref", "")),
    }
