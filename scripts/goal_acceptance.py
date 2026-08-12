#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
from typing import Any


KIND = "CGKNGoalAcceptance"
FILE_NAME = "goal_acceptance.json"


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _has_runtime_value(node: ast.AST) -> bool:
    return any(
        isinstance(child, (ast.Name, ast.Attribute, ast.Call, ast.Subscript))
        for child in ast.walk(node)
    )


def _substantive_test(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    behavior_calls: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assert) and _has_runtime_value(node.test):
            evidence.append("assert")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                call_name = node.func.id
            else:
                call_name = ""
            if call_name.startswith("assert") and any(_has_runtime_value(arg) for arg in node.args):
                evidence.append(call_name)
            elif call_name != "raises":
                behavior_calls.append(call_name or "call")
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                expression = item.context_expr
                if (
                    isinstance(expression, ast.Call)
                    and isinstance(expression.func, ast.Attribute)
                    and expression.func.attr == "raises"
                ):
                    evidence.append("pytest.raises")
    if behavior_calls:
        evidence.append("behavior_call")
    return bool(evidence) and bool(behavior_calls), list(dict.fromkeys(evidence))


def _python_test_catalog(project_dir: pathlib.Path) -> dict[str, list[dict[str, Any]]]:
    project = pathlib.Path(project_dir).resolve()
    tests_dir = project / "tests"
    catalog: dict[str, list[dict[str, Any]]] = {}
    if not tests_dir.is_dir():
        return catalog
    for path in sorted(tests_dir.rglob("test_*.py")):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(project)
            if not resolved.is_file() or resolved.stat().st_size > 1_000_000:
                continue
            source = resolved.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            continue
        relative = resolved.relative_to(project).as_posix()
        collected_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                collected_nodes.append(node)
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                collected_nodes.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test_")
                )
        for node in collected_nodes:
            substantive, assertion_kinds = _substantive_test(node)
            catalog.setdefault(node.name, []).append(
                {
                    "path": relative,
                    "line": int(getattr(node, "lineno", 0) or 0),
                    "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    "substantive": substantive,
                    "assertion_kinds": assertion_kinds,
                }
            )
    return catalog


def evaluate_goal_acceptance(
    *,
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    test_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the canonical goal plan to inspected executable tests and their real run."""
    project = pathlib.Path(project_dir)
    run = pathlib.Path(run_dir)
    requirement_dir = run / "requirement_decision"
    goal_spec_path = requirement_dir / "goal_spec.json"
    project_plan_path = requirement_dir / "project_plan.json"
    applicable = goal_spec_path.exists() or project_plan_path.exists()
    if not applicable:
        receipt = {
            "kind": KIND,
            "schema_version": 1,
            "status": "NOT_EVALUATED",
            "applicable": False,
            "reason": "goal_plan_artifacts_not_present",
            "formal_delivery_authority": False,
            "blockers": [],
            "mapped_tests": [],
        }
        receipt["receipt_sha256"] = _canonical_hash(receipt)
        return receipt

    goal_spec = _read_json(goal_spec_path)
    project_plan = _read_json(project_plan_path)
    behaviors = [
        str(item).strip()
        for item in goal_spec.get("acceptance_behaviors", [])
        if str(item).strip()
    ] if isinstance(goal_spec.get("acceptance_behaviors", []), list) else []
    test_intents = [
        str(item).strip()
        for item in project_plan.get("test_intents", [])
        if str(item).strip()
    ] if isinstance(project_plan.get("test_intents", []), list) else []
    goal_tests = [
        {
            "intent": str(item.get("intent", "")).strip(),
            "test_symbol": str(item.get("test_symbol", "")).strip(),
        }
        for item in project_plan.get("goal_acceptance_tests", [])
        if isinstance(item, dict)
        and str(item.get("intent", "")).strip()
        and str(item.get("test_symbol", "")).strip()
    ] if isinstance(project_plan.get("goal_acceptance_tests", []), list) else []

    blockers: list[str] = []
    if goal_spec.get("kind") != "GoalSpec" or goal_spec.get("status") != "PASS":
        blockers.append("goal_spec_not_pass")
    if project_plan.get("kind") != "GoalDrivenProjectPlan" or project_plan.get("status") != "PASS":
        blockers.append("project_plan_not_pass")
    if not behaviors:
        blockers.append("acceptance_behaviors_missing")
    if behaviors != test_intents:
        blockers.append("goal_behaviors_and_test_intents_mismatch")
    if str(goal_spec.get("goal", "")) != str(project_plan.get("goal", "")):
        blockers.append("goal_identity_mismatch")
    if str(goal_spec.get("domain", "")) != str(project_plan.get("domain", "")):
        blockers.append("goal_domain_mismatch")
    if [item["intent"] for item in goal_tests] != test_intents:
        blockers.append("goal_test_contract_intents_mismatch")
    if len({item["test_symbol"] for item in goal_tests}) != len(goal_tests):
        blockers.append("goal_test_symbols_not_unique")

    catalog = _python_test_catalog(project)
    mapped_tests: list[dict[str, Any]] = []
    for item in goal_tests:
        matches = catalog.get(item["test_symbol"], [])
        substantive = [match for match in matches if match.get("substantive")]
        if len(matches) != 1:
            blockers.append(f"goal_test_symbol_count:{item['test_symbol']}:{len(matches)}")
        elif not substantive:
            blockers.append(f"goal_test_not_substantive:{item['test_symbol']}")
        mapped_tests.append(
            {
                **item,
                "matches": matches,
                "accepted": len(matches) == 1 and bool(substantive),
            }
        )

    execution = test_result if isinstance(test_result, dict) else {}
    execution_argv = execution.get("argv", []) if isinstance(execution.get("argv", []), list) else []
    pytest_executed = "pytest" in " ".join(str(item).lower() for item in execution_argv)
    execution_passed = (
        str(execution.get("status", "")).lower() == "pass"
        and execution.get("returncode") == 0
        and bool(execution_argv)
        and pytest_executed
        and not bool(execution.get("skipped"))
    )
    if not execution_passed:
        blockers.append("real_test_execution_not_passed")

    status = "PASS" if not blockers else (
        "BLOCKED_ENVIRONMENT"
        if str(execution.get("status", "")).lower() == "environment_failure"
        else "NEEDS_REWORK"
    )
    receipt = {
        "kind": KIND,
        "schema_version": 1,
        "status": status,
        "applicable": True,
        "formal_delivery_authority": False,
        "goal": str(goal_spec.get("goal", "")),
        "domain": str(goal_spec.get("domain", "")),
        "goal_spec_ref": str(goal_spec_path.resolve()),
        "goal_spec_sha256": _canonical_hash(goal_spec) if goal_spec else "",
        "project_plan_ref": str(project_plan_path.resolve()),
        "project_plan_sha256": _canonical_hash(project_plan) if project_plan else "",
        "acceptance_behaviors": behaviors,
        "test_intents": test_intents,
        "required_test_symbols": [item["test_symbol"] for item in goal_tests],
        "mapped_tests": mapped_tests,
        "test_execution": {
            "status": str(execution.get("status", "")),
            "argv": execution_argv,
            "returncode": execution.get("returncode"),
            "pytest_executed": pytest_executed,
            "passed": execution_passed,
        },
        "blockers": list(dict.fromkeys(blockers)),
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    return receipt


def inspect_goal_acceptance(
    receipt_ref: str | pathlib.Path | None,
    *,
    project_dir: str | pathlib.Path | None,
    run_dir: str | pathlib.Path | None,
    canonical_test_evidence_ref: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Independently recheck a veto-only goal-acceptance support receipt."""
    project = pathlib.Path(project_dir).resolve() if project_dir else pathlib.Path()
    run = pathlib.Path(run_dir).resolve() if run_dir else pathlib.Path()
    requirement_dir = run / "requirement_decision" if run_dir else pathlib.Path()
    applicable = bool(
        run_dir
        and (
            (requirement_dir / "goal_spec.json").is_file()
            or (requirement_dir / "project_plan.json").is_file()
        )
    )
    if not applicable:
        return {
            "status": "PASS",
            "applicable": False,
            "failures": [],
            "reason": "goal_plan_artifacts_not_present",
        }

    expected_path = run / "artifacts" / FILE_NAME
    path = pathlib.Path(receipt_ref).resolve() if receipt_ref else expected_path
    failures: list[str] = []
    if path != expected_path:
        failures.append("goal_acceptance_ref_mismatch")
    if not path.is_file() or path.is_symlink():
        return {
            "status": "NEEDS_REWORK",
            "applicable": True,
            "failures": sorted(set(failures + ["goal_acceptance_receipt_missing"])),
            "receipt_ref": str(path),
        }
    receipt = _read_json(path)
    if receipt.get("kind") != KIND or receipt.get("schema_version") != 1:
        failures.append("goal_acceptance_contract")
    if receipt.get("applicable") is not True:
        failures.append("goal_acceptance_applicability_mismatch")
    if receipt.get("formal_delivery_authority") is not False:
        failures.append("goal_acceptance_claims_formal_authority")
    claimed_hash = str(receipt.get("receipt_sha256", ""))
    unhashed = dict(receipt)
    unhashed.pop("receipt_sha256", None)
    if claimed_hash != _canonical_hash(unhashed):
        failures.append("goal_acceptance_receipt_hash_mismatch")

    execution = receipt.get("test_execution", {}) if isinstance(receipt.get("test_execution"), dict) else {}
    canonical_test_evidence: dict[str, Any] = {}
    canonical_test_path = (
        pathlib.Path(canonical_test_evidence_ref).resolve()
        if canonical_test_evidence_ref
        else None
    )
    if canonical_test_path is not None:
        expected_test_path = project / "test_execution.json"
        if canonical_test_path != expected_test_path:
            failures.append("canonical_test_evidence_ref_mismatch")
        if not canonical_test_path.is_file() or canonical_test_path.is_symlink():
            failures.append("canonical_test_evidence_missing")
        else:
            canonical_test_evidence = _read_json(canonical_test_path)
            if (
                canonical_test_evidence.get("kind") != "CGKNTestExecutionEvidence"
                or canonical_test_evidence.get("producer") != "scripts/real_test_execution.py"
                or canonical_test_evidence.get("status") != "PASS"
            ):
                failures.append("canonical_test_evidence_contract")
            execution = {
                "status": "pass" if canonical_test_evidence.get("status") == "PASS" else "fail",
                "argv": canonical_test_evidence.get("argv", []),
                "returncode": canonical_test_evidence.get("exit_code"),
                "skipped": bool(canonical_test_evidence.get("skipped", 0)),
            }
    recomputed = evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run,
        test_result={
            "status": execution.get("status"),
            "argv": execution.get("argv", []),
            "returncode": execution.get("returncode"),
            "skipped": execution.get("skipped", not bool(execution.get("passed"))),
        },
    )
    for field in (
        "kind",
        "schema_version",
        "status",
        "applicable",
        "formal_delivery_authority",
        "goal",
        "domain",
        "goal_spec_ref",
        "goal_spec_sha256",
        "project_plan_ref",
        "project_plan_sha256",
        "acceptance_behaviors",
        "test_intents",
        "required_test_symbols",
        "mapped_tests",
        "test_execution",
        "blockers",
    ):
        if receipt.get(field) != recomputed.get(field):
            failures.append(f"goal_acceptance_recomputed_mismatch:{field}")
    if receipt.get("status") != "PASS" or recomputed.get("status") != "PASS":
        failures.append("goal_acceptance_not_pass")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "applicable": True,
        "failures": sorted(set(failures)),
        "receipt_ref": str(path),
        "receipt_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "canonical_test_evidence_ref": str(canonical_test_path) if canonical_test_path else "",
        "canonical_test_evidence_hash": (
            hashlib.sha256(canonical_test_path.read_bytes()).hexdigest()
            if canonical_test_path and canonical_test_path.is_file() and not canonical_test_path.is_symlink()
            else ""
        ),
        "receipt": receipt,
    }


def produce_from_canonical_test_evidence(
    *,
    project_dir: str | pathlib.Path,
    run_dir: str | pathlib.Path,
    test_evidence: dict[str, Any],
) -> tuple[dict[str, Any], pathlib.Path]:
    """Write support truth beside the production run after canonical tests."""
    run = pathlib.Path(run_dir)
    receipt = evaluate_goal_acceptance(
        project_dir=pathlib.Path(project_dir),
        run_dir=run,
        test_result={
            "status": "pass" if test_evidence.get("status") == "PASS" else "fail",
            "argv": test_evidence.get("argv", []),
            "returncode": test_evidence.get("exit_code"),
            "skipped": bool(test_evidence.get("skipped", 0)),
        },
    )
    path = run / "artifacts" / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt, path.resolve()
