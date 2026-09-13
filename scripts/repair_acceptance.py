#!/usr/bin/env python3
"""Issue-level acceptance for existing ProviderJob repair deltas.

This module is deliberately a pure contract/helper.  It does not schedule work,
call a Provider, mutate candidates, or authorize release.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any


_SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3, "blocker": 3}
_FORBIDDEN_OUTPUT_NAMES = {
    "delivery_manifest.json",
    "provider_manifest.json",
    "final_project_bundle.zip",
    "test_report.json",
}


def normalize_path(value: Any) -> str:
    rel = str(value or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def path_is_safe_owned_target(path: str, owned_paths: set[str]) -> bool:
    rel = normalize_path(path)
    parts = pathlib.PurePosixPath(rel).parts
    return bool(rel and rel in owned_paths and ".." not in parts and not pathlib.PurePosixPath(rel).is_absolute())


def forbidden_generated_output(path: str) -> bool:
    rel = normalize_path(path).lower()
    name = pathlib.PurePosixPath(rel).name
    return bool(
        name in _FORBIDDEN_OUTPUT_NAMES
        or rel.endswith(".zip")
        or rel.startswith("artifacts/")
        or "/evidence/" in f"/{rel}/"
        or "fake_evidence" in rel
    )


def mock_only_or_deleted_source(content: str) -> bool:
    source = str(content or "").strip()
    if not source:
        return True
    meaningful = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//", "/*", "*"))
    ]
    if not meaningful:
        return True
    compact = " ".join(meaningful).lower()
    placeholders = {
        "pass",
        "todo",
        "return null;",
        "return undefined;",
        "throw new error('not implemented');",
        'throw new error("not implemented");',
    }
    return compact in placeholders or bool(
        re.fullmatch(r"(?:const|let|var)\s+mock\w*\s*=\s*(?:true|false|null|\{\}|\[\]);?", compact)
    )


def _issue_path(issue: dict[str, Any]) -> str:
    return normalize_path(issue.get("path", ""))


def _issue_identity(issue: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(issue.get("kind", "")).strip(),
        _issue_path(issue),
        str(issue.get("expected_behavior", "")).strip(),
    )


def _severity(issue: dict[str, Any]) -> int:
    return _SEVERITY.get(str(issue.get("severity", "error")).strip().lower(), 2)


def _failure_magnitude(issue: dict[str, Any]) -> int:
    """Return a conservative cardinality for known multi-failure issue records."""
    kind = str(issue.get("kind", ""))
    observed = str(issue.get("observed_behavior", ""))
    if kind == "dom_id_contract_mismatch":
        match = re.search(r"missing\s+dom\s+ids?\s*:\s*(.*)", observed, flags=re.I)
        if match:
            return max(1, len([item for item in match.group(1).split(",") if item.strip()]))
    return 1


def _coherence_evidence(fact: dict[str, Any], target_file: str) -> list[dict[str, Any]]:
    evidence = fact.get("evidence", [])
    rows = evidence if isinstance(evidence, list) else [evidence]
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("authority", "")) == "deterministic_build_coherence"
        and _issue_path(row) == target_file
    ]


def _matching_issues(
    issues: list[dict[str, Any]],
    *,
    kind: str,
    path: str,
    expected_behavior: str,
) -> list[dict[str, Any]]:
    matches = [
        issue
        for issue in issues
        if str(issue.get("kind", "")) == kind and _issue_path(issue) == path
    ]
    if expected_behavior:
        exact = [
            issue
            for issue in matches
            if str(issue.get("expected_behavior", "")).strip() == expected_behavior
        ]
        return exact
    return matches


def assess_provider_job_partial_acceptance(
    *,
    target_file: str,
    before_content: str,
    after_content: str,
    coherence_before: list[dict[str, Any]],
    coherence_after: list[dict[str, Any]],
    evidence_facts: list[dict[str, Any]] | None,
    owned_paths: set[str],
    syntax_safe: bool,
    behavior_checks_before: list[dict[str, Any]] | None = None,
    behavior_checks_after: list[dict[str, Any]] | None = None,
    tree_node_id: str = "",
) -> dict[str, Any]:
    """Accept a bounded leaf delta only when at least one owned issue improves."""
    target = normalize_path(target_file)
    before_rows = [dict(item) for item in coherence_before if isinstance(item, dict)]
    after_rows = [dict(item) for item in coherence_after if isinstance(item, dict)]
    facts = [dict(item) for item in (evidence_facts or []) if isinstance(item, dict)]

    issue_inputs: list[dict[str, Any]] = []
    for fact in facts:
        for evidence in _coherence_evidence(fact, target):
            issue_inputs.append(
                {
                    "issue_id": str(fact.get("issue_id", "")),
                    "issue_type": str(evidence.get("kind", fact.get("failed_requirement", ""))),
                    "expected_behavior": str(fact.get("expected_behavior", evidence.get("expected_behavior", ""))).strip(),
                    "observed_behavior": str(fact.get("observed_behavior", evidence.get("observed_behavior", ""))).strip(),
                }
            )
    if not issue_inputs:
        for index, issue in enumerate(before_rows):
            if _issue_path(issue) == target:
                issue_inputs.append(
                    {
                        "issue_id": f"coherence:{index}:{issue.get('kind', '')}",
                        "issue_type": str(issue.get("kind", "")),
                        "expected_behavior": str(issue.get("expected_behavior", "")).strip(),
                        "observed_behavior": str(issue.get("observed_behavior", "")).strip(),
                    }
                )

    before_identities = {_issue_identity(issue) for issue in before_rows}
    new_blockers = [
        issue
        for issue in after_rows
        if _issue_identity(issue) not in before_identities and _severity(issue) >= 2
    ]
    checks_before = list(behavior_checks_before or [])
    checks_after = list(behavior_checks_after or [])
    passed_before = {
        str(item.get("check_id", item.get("name", "")))
        for item in checks_before
        if str(item.get("status", "")).upper() == "PASS"
    }
    regressed_checks = [
        item
        for item in checks_after
        if str(item.get("check_id", item.get("name", ""))) in passed_before
        and str(item.get("status", "")).upper() != "PASS"
    ]

    records: list[dict[str, Any]] = []
    for item in issue_inputs:
        kind = item["issue_type"]
        expected = item["expected_behavior"]
        matching_before = _matching_issues(
            before_rows, kind=kind, path=target, expected_behavior=expected
        )
        matching_after = _matching_issues(
            after_rows, kind=kind, path=target, expected_behavior=expected
        )
        before_magnitude = sum(_failure_magnitude(issue) for issue in matching_before)
        after_magnitude = sum(_failure_magnitude(issue) for issue in matching_after)
        fixed_by_delta = bool(before_magnitude > after_magnitude)
        records.append(
            {
                "issue_id": item["issue_id"],
                "tree_node_id": tree_node_id,
                "issue_type": kind,
                "target_files": [target],
                "expected_behavior": expected,
                "observed_behavior": item["observed_behavior"],
                "coherence_checks_before": matching_before,
                "coherence_checks_after": matching_after,
                "behavior_checks_before": checks_before,
                "behavior_checks_after": checks_after,
                "fixed_by_delta": fixed_by_delta,
                "introduced_new_blockers": bool(new_blockers),
                "new_blocker_details": new_blockers,
                "safe_to_accept_partial": False,
            }
        )

    target_improvements = sum(1 for record in records if record["fixed_by_delta"])
    changed = str(before_content) != str(after_content)
    owned = path_is_safe_owned_target(target, {normalize_path(path) for path in owned_paths})
    forbidden = forbidden_generated_output(target)
    mock_or_delete = mock_only_or_deleted_source(after_content)
    safe = bool(
        changed
        and owned
        and syntax_safe
        and not forbidden
        and not mock_or_delete
        and target_improvements > 0
        and not new_blockers
        and not regressed_checks
    )
    for record in records:
        record["safe_to_accept_partial"] = bool(safe and record["fixed_by_delta"])

    if not changed:
        reason = "NO_ACTUAL_CHANGE"
    elif not owned:
        reason = "OWNERSHIP_OR_PATH_REJECT"
    elif forbidden:
        reason = "FORBIDDEN_GENERATED_OUTPUT"
    elif mock_or_delete:
        reason = "CORE_DELETION_OR_MOCK_ONLY_REJECT"
    elif not syntax_safe:
        reason = "SYNTAX_VALIDATION_FAILED"
    elif new_blockers:
        reason = "NEW_EQUAL_OR_HIGHER_BLOCKER"
    elif regressed_checks:
        reason = "PASSING_EVIDENCE_REGRESSION"
    elif target_improvements == 0:
        reason = "NO_TARGET_ISSUE_IMPROVEMENT"
    else:
        reason = ""
    evidence_tree_updates = [
        {
            "tree_node_id": tree_node_id,
            "status": "pass",
            "evidence": {
                "authority": "provider_job_issue_level_acceptance",
                "target_file": target,
                "issue_ids": [record["issue_id"] for record in records if record["fixed_by_delta"]],
                "case_score_required": False,
            },
        }
    ] if safe and tree_node_id else []
    return {
        "status": "accepted" if safe else "rejected",
        "reason": reason,
        "target_file": target,
        "issue_acceptance": records,
        "issues_fixed_by_partial_acceptance": target_improvements if safe else 0,
        "issues_rejected_after_partial_validation": 0 if safe else max(1, len(records)),
        "accepted_partial_deltas": 1 if safe else 0,
        "accepted_without_target_issue_improvement": 0,
        "introduced_new_blockers": new_blockers,
        "regressed_behavior_checks": regressed_checks,
        "safe_to_accept_partial": safe,
        "evidence_tree_updates": evidence_tree_updates,
    }
