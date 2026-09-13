#!/usr/bin/env python3
"""Deterministic evaluator-failure to ProviderJob issue mapping.

This module owns no scheduling or candidate mutation.  It converts observed
product failures into the smallest existing ProviderJob-owned issue records so
the production post-build repair lane can decide whether to call the Provider.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Mapping
from typing import Any


FAILURE_STATUSES = {"FAIL", "NEEDS_REWORK", "BLOCKED"}


def _normalized_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def _record_text(record: Mapping[str, Any]) -> str:
    values = [
        record.get("criterion_id"),
        record.get("failed_requirement"),
        record.get("user_action"),
        record.get("expected_behavior"),
        record.get("observed_behavior"),
        record.get("reason"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _owned_existing(paths: list[str], ownership: Mapping[str, str]) -> list[str]:
    return list(dict.fromkeys(path for path in paths if path in ownership))


def infer_failure_target_files(
    record: Mapping[str, Any],
    ownership: Mapping[str, str],
) -> list[str]:
    """Infer at most two exact owned files from behavior evidence.

    Explicit evaluator paths always win.  Semantic inference is deliberately
    narrow and never expands to an entire component or directory.
    """
    explicit = _owned_existing(
        [_normalized_path(path) for path in record.get("affected_files", [])],
        ownership,
    )
    if explicit:
        return explicit[:2]

    text = _record_text(record)
    candidates: list[str] = []
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("static root", "startup", "root route", "404"), ("app/main.py", "main.py", "server.py")),
        (("dom", "element id", "selector", "alignment"), ("frontend/index.html", "frontend/app.js", "index.html", "app.js")),
        (("upload", "import csv", "csv import"), ("app/main.py", "frontend/app.js", "src/csv_import.py")),
        (("clean", "preview"), ("app/main.py", "frontend/app.js", "src/cleaning_engine.py", "src/result_preview.py")),
        (("export", "download"), ("app/main.py", "frontend/app.js", "src/csv_export.py")),
        (("create", "edit", "delete", "crud"), ("frontend/app.js", "app/main.py")),
        (("move", "status"), ("frontend/app.js", "src/move_task_status.py", "app/main.py")),
        (("persist", "storage", "reload"), ("frontend/app.js", "src/persist_board_state.py", "app/main.py")),
    ]
    for tokens, paths in rules:
        if any(token in text for token in tokens):
            candidates.extend(paths)
    return _owned_existing(candidates, ownership)[:2]


def evaluator_failure_identity(record: Mapping[str, Any]) -> str:
    return str(
        record.get("evaluator_failure_id")
        or record.get("criterion_id")
        or record.get("failed_requirement")
        or record.get("id")
        or "evaluator_failure"
    ).strip()


def failure_record_is_actionable(record: Mapping[str, Any]) -> bool:
    status = str(record.get("status") or "FAIL").strip().upper()
    return status in FAILURE_STATUSES


def bind_issue_to_tree_ownership(
    issue: Mapping[str, Any],
    tree: Mapping[str, Any],
    ownership: Mapping[str, str],
) -> dict[str, Any]:
    """Narrow a mapped issue to an exact file owned by its tree capability."""
    result = dict(issue)
    node_id = str(result.get("tree_node_id", ""))
    node = next(
        (
            item
            for item in tree.get("nodes", [])
            if isinstance(item, Mapping) and str(item.get("node_id", "")) == node_id
        ),
        {},
    )
    node_targets = [
        _normalized_path(item)
        for item in node.get("target_files", [])
        if _normalized_path(item) in ownership
    ]
    current = [
        _normalized_path(item)
        for item in result.get("affected_files", [])
        if _normalized_path(item) in node_targets
    ]
    exact = current or node_targets
    if not exact:
        return result
    preferred = exact[0]
    if node_id in {"capability.static_web_entry", "semantic_contract.main_entry"}:
        preferred = next(
            (path for path in exact if path in {"app/main.py", "main.py", "server.py"}),
            preferred,
        )
    job_id = str(ownership.get(preferred, ""))
    owner = job_id.split(".", 1)[0] if job_id else "unassigned"
    if owner == "tests":
        owner = "integration"
    result.update(
        {
            "affected_files": [preferred],
            "affected_provider_job": job_id,
            "owner": owner,
            "repairable": bool(job_id and result.get("repair_route", "provider") == "provider"),
        }
    )
    evidence = dict(result.get("evidence", {}))
    evidence["paths"] = [preferred]
    result["evidence"] = evidence
    return result


def issues_from_evaluator_failure(
    record: Mapping[str, Any],
    ownership: Mapping[str, str],
    decomposition_tree_doc: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Create one issue per exact existing ProviderJob ownership unit."""
    if not failure_record_is_actionable(record):
        return []
    failure_id = evaluator_failure_identity(record)
    paths = infer_failure_target_files(record, ownership)
    expected = str(record.get("expected_behavior") or "").strip()
    observed = str(record.get("observed_behavior") or record.get("reason") or "").strip()
    user_action = str(record.get("user_action") or "").strip()
    repair_route = str(record.get("repair_route") or "provider").strip().lower()
    if not paths:
        seed = json.dumps(dict(record), ensure_ascii=False, sort_keys=True, default=str)
        issues = [
            {
                "issue_id": f"ISSUE-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}",
                "requirement": failure_id,
                "failed_requirement": failure_id,
                "symptom": observed or failure_id,
                "user_action": user_action,
                "expected_behavior": expected,
                "observed_behavior": observed,
                "evidence": {"paths": [], "evaluator": [dict(record)]},
                "severity": "RELEASE_HARD",
                "owner": "unassigned",
                "affected_provider_job": "",
                "affected_files": [],
                "root_cause_key": str(record.get("root_cause_key") or failure_id),
                "repair_route": "halt",
                "repairable": False,
                "evidence_priority": "runtime_browser_evaluator",
                "external_evidence": [dict(record)],
                "evidence_disposition": "OBSERVED_PRODUCT_FAILURE_UNMAPPED",
            }
        ]
        if decomposition_tree_doc:
            try:
                from decomposition_tree import bind_issues_to_tree
            except ModuleNotFoundError:  # pragma: no cover - package import path
                from scripts.decomposition_tree import bind_issues_to_tree
            _, issues = bind_issues_to_tree(decomposition_tree_doc, issues)
        return issues

    issues: list[dict[str, Any]] = []
    for path in paths:
        job_id = str(ownership.get(path) or "")
        seed = f"{failure_id}|{job_id}|{path}|{expected}|{observed}"
        owner = job_id.split(".", 1)[0] if job_id else "unassigned"
        if owner == "tests":
            owner = "integration"
        issues.append(
            {
                "issue_id": f"ISSUE-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}",
                "requirement": failure_id,
                "failed_requirement": failure_id,
                "symptom": observed or failure_id,
                "user_action": user_action,
                "expected_behavior": expected,
                "observed_behavior": observed,
                "evidence": {"paths": [path], "evaluator": [dict(record)]},
                "severity": "RELEASE_HARD",
                "owner": owner,
                "affected_provider_job": job_id,
                "affected_files": [path],
                "root_cause_key": str(record.get("root_cause_key") or failure_id),
                "repair_route": repair_route,
                "repairable": bool(job_id and repair_route == "provider"),
                "evidence_priority": "runtime_browser_evaluator",
                "external_evidence": [dict(record)],
                "evidence_disposition": "OBSERVED_PRODUCT_FAILURE",
            }
        )
    if decomposition_tree_doc:
        try:
            from decomposition_tree import bind_issues_to_tree
        except ModuleNotFoundError:  # pragma: no cover - package import path
            from scripts.decomposition_tree import bind_issues_to_tree
        _, issues = bind_issues_to_tree(decomposition_tree_doc, issues)
    return issues
