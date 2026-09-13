#!/usr/bin/env python3
"""Deterministic project decomposition tree for the production mainline.

The tree is an index over planning, issue and evidence records.  It owns no
Provider calls, scheduling, candidate mutation, evaluation or release authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable, Mapping


NODE_TYPES = {"capability", "stage", "component", "file", "issue", "evidence"}
NODE_STATUSES = {"unknown", "pass", "fail", "repairable_fail", "fatal_fail"}
TREE_KIND = "CGKNProjectDecompositionTree"


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return text or "unknown"


def _normalize_path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw.startswith("/") or ".." in pathlib.PurePosixPath(raw).parts:
        return ""
    return pathlib.PurePosixPath(raw).as_posix()


def file_node_id(path: Any) -> str:
    return f"file.{_slug(_normalize_path(path))}"


def _node(
    node_id: str,
    node_type: str,
    parent_id: str,
    title: str,
    *,
    expected_behavior: str = "",
    target_files: Iterable[str] = (),
    required_evidence: Iterable[str] = (),
) -> dict[str, Any]:
    if node_type not in NODE_TYPES:
        raise ValueError(f"invalid decomposition node type: {node_type}")
    return {
        "node_id": node_id,
        "node_type": node_type,
        "parent_id": parent_id,
        "title": title,
        "expected_behavior": expected_behavior,
        "target_files": list(dict.fromkeys(filter(None, (_normalize_path(item) for item in target_files)))),
        "required_evidence": list(dict.fromkeys(str(item) for item in required_evidence if str(item).strip())),
        "status": "unknown",
        "current_evidence": [],
        "mapped_issues": [],
    }


def _plan_paths(project_plan: Mapping[str, Any] | None) -> list[str]:
    plan = project_plan or {}
    values: list[Any] = []
    values.extend(plan.get("expected_project_structure", []) if isinstance(plan.get("expected_project_structure"), list) else [])
    for workstream in plan.get("workstreams", []):
        if not isinstance(workstream, Mapping):
            continue
        for key in ("paths", "files", "target_files", "owns"):
            raw = workstream.get(key, [])
            values.extend(raw if isinstance(raw, list) else [])
    return list(dict.fromkeys(path for path in (_normalize_path(item) for item in values) if path))


def _component_rows(component_pipeline: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    raw = (component_pipeline or {}).get("components", [])
    return [item for item in raw if isinstance(item, Mapping)]


def _component_paths(component: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("paths", "files", "owns", "target_files", "required_paths"):
        raw = component.get(key, [])
        values.extend(raw if isinstance(raw, list) else [])
    graph = component.get("leaf_work_graph", {})
    if isinstance(graph, Mapping):
        for leaf in graph.get("leaves", []):
            if not isinstance(leaf, Mapping):
                continue
            raw = leaf.get("paths", leaf.get("owns", []))
            if not raw and str(leaf.get("path", "")).strip():
                raw = [leaf.get("path")]
            values.extend(raw if isinstance(raw, list) else [])
    return list(dict.fromkeys(path for path in (_normalize_path(item) for item in values) if path))


def _capability_templates(domain: str, capabilities: Iterable[Any], paths: list[str]) -> list[dict[str, Any]]:
    tokens = {_slug(item) for item in capabilities}
    domain_token = _slug(domain)
    case01 = "csv" in domain_token or any("csv" in item for item in tokens)
    case03 = any(item in domain_token for item in ("task_board", "project_board", "kanban")) or {
        "create_task", "move_task_status", "persist_board_state"
    }.intersection(tokens)
    frontend = [path for path in paths if path.endswith((".html", ".js", ".mjs", ".css"))]
    backend = [path for path in paths if path.endswith(".py") and not path.startswith("tests/")]
    tests = [path for path in paths if path.startswith("tests/")]
    static_entry = [path for path in paths if pathlib.PurePosixPath(path).name in {"main.py", "app.py", "server.py", "index.html"}]
    nodes: list[dict[str, Any]] = []

    def add(node_id: str, title: str, expected: str, targets: list[str], evidence: list[str]) -> None:
        nodes.append(_node(node_id, "capability", "stage.product", title, expected_behavior=expected, target_files=targets, required_evidence=evidence))

    static_targets = (
        ["app/main.py", "frontend/index.html"]
        if case01 or case03
        else static_entry[:3] or (backend[:1] + frontend[:1])
    )
    add("capability.static_web_entry", "Static web entry", "GET / returns 200 and serves the frontend entry.", static_targets, ["probe_static_root"])
    if case01:
        add("capability.csv_upload", "CSV upload", "A sample CSV can be uploaded through the expected endpoint.", ["app/main.py", "frontend/app.js"], ["probe_csv_upload"])
        add("capability.clean_preview", "Clean and preview", "Clean/process returns preview rows and count.", ["app/main.py", "frontend/app.js"], ["probe_clean_preview"])
        add("capability.export_csv", "Export CSV", "The export endpoint returns downloadable CSV with cleaned rows.", ["app/main.py", "frontend/app.js"], ["probe_export_csv"])
        add("capability.delivery_evidence", "Delivery evidence", "TEST_REPORT and DELIVERY_NOTES reflect real executed checks.", ["TEST_REPORT.md", "DELIVERY_NOTES.md"], ["delivery_probe"])
    if case03:
        add("semantic_contract.main_entry", "Canonical main entry", "app/main.py exposes the expected main/start entry.", ["app/main.py"], ["semantic_review"])
        add("test_contract.canonical_verifier", "Canonical verifier", "Generated tests do not import a Selenium/browser branch unless explicitly allowed.", tests or ["tests/"], ["semantic_review"])
        add("capability.dom_alignment", "DOM alignment", "JavaScript ids match HTML ids.", ["frontend/index.html", "frontend/app.js"], ["dom_contract_probe"])
        add("capability.crud", "Task CRUD", "Create, edit and delete behavior works.", ["frontend/app.js", "app/main.py"], ["crud_probe"])
        add("capability.move_status", "Move and status", "Task status and move behavior works.", ["frontend/app.js", "app/main.py"], ["move_status_probe"])
        add("capability.persistence", "Persistence", "Saved data persists across reload and restart.", ["app/main.py", "storage/", "frontend/app.js"], ["persistence_probe"])
        add("capability.export", "Export", "Export produces downloadable project data.", ["app/main.py", "frontend/app.js"], ["export_probe"])
    if not case01 and not case03:
        for capability in sorted(tokens):
            add(f"capability.{capability}", str(capability).replace("_", " ").title(), f"The project satisfies capability {capability}.", paths[:4], ["canonical_evaluator"])
    return nodes


def build_project_decomposition_tree(
    *,
    user_goal: str,
    goal_spec: Mapping[str, Any] | None,
    project_plan: Mapping[str, Any] | None,
    component_pipeline: Mapping[str, Any] | None,
    project_id: str = "",
) -> dict[str, Any]:
    """Build the required deterministic mainline index before Provider generation."""
    spec = goal_spec or {}
    domain = str(spec.get("domain") or spec.get("project_type") or "")
    capabilities = spec.get("capabilities", [])
    if isinstance(capabilities, Mapping):
        capabilities = list(capabilities)
    if not isinstance(capabilities, list):
        capabilities = []
    components = _component_rows(component_pipeline)
    paths = _plan_paths(project_plan)
    for component in components:
        paths.extend(_component_paths(component))
    paths = list(dict.fromkeys(paths))
    nodes = [
        _node("stage.project_goal", "stage", "", "User goal", expected_behavior=str(user_goal), required_evidence=["project_spec"]),
        _node("stage.product", "stage", "stage.project_goal", "Product capabilities", expected_behavior="All required user-visible capabilities are independently evidenced.", required_evidence=["canonical_evaluator"]),
        _node("stage.release", "stage", "stage.project_goal", "Release", expected_behavior="Only the unchanged final gate and local_packager may authorize delivery.", required_evidence=["final_gate", "package", "delivery_identity"]),
    ]
    nodes.extend(_capability_templates(domain, capabilities, paths))
    for component in components:
        component_id = str(component.get("id") or component.get("component_id") or "component").strip()
        nodes.append(_node(f"component.{_slug(component_id)}", "component", "stage.product", component_id, expected_behavior=str(component.get("purpose") or component.get("goal") or "Component fulfills its declared contract."), target_files=_component_paths(component), required_evidence=["provider_validation", "integration"] ))
    parent_by_path: dict[str, str] = {}
    for component in components:
        component_id = str(component.get("id") or component.get("component_id") or "component").strip()
        for path in _component_paths(component):
            parent_by_path.setdefault(path, f"component.{_slug(component_id)}")
    for path in paths:
        nodes.append(_node(file_node_id(path), "file", parent_by_path.get(path, "stage.product"), path, expected_behavior="The file satisfies its declared ProviderJob contract and integrated behavior.", target_files=[path], required_evidence=["provider_validation", "affected_behavior"] ))
    unique_nodes = {item["node_id"]: item for item in nodes}
    project_identity = project_id or hashlib.sha256(str(user_goal).encode("utf-8")).hexdigest()[:16]
    document = {
        "kind": TREE_KIND,
        "schema_version": "1.0",
        "project_id": project_identity,
        "goal": str(user_goal),
        "user_goal": str(user_goal),
        "required_for_generation": True,
        "nodes": list(unique_nodes.values()),
        "plan_tree": {"root_node_id": "stage.project_goal", "node_ids": list(unique_nodes)},
        "issue_tree": {"node_ids": list(unique_nodes), "mappings": []},
        "evidence_tree": {"node_ids": list(unique_nodes), "updates": []},
        "release_authority": False,
    }
    return with_tree_hash(document)


def build_case01_tree(**kwargs: Any) -> dict[str, Any]:
    spec = dict(kwargs.pop("goal_spec", {}) or {})
    spec.update({"domain": "csv_cleaning_tool", "capabilities": ["import_csv", "clean_preview", "export_csv"]})
    return build_project_decomposition_tree(goal_spec=spec, **kwargs)


def build_case03_tree(**kwargs: Any) -> dict[str, Any]:
    spec = dict(kwargs.pop("goal_spec", {}) or {})
    spec.update({"domain": "local_task_board", "capabilities": ["create_task", "move_task_status", "persist_board_state"]})
    return build_project_decomposition_tree(goal_spec=spec, **kwargs)


def with_tree_hash(tree: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(tree))
    result.pop("tree_sha256", None)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    result["tree_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return result


def validate_tree(tree: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if tree.get("kind") != TREE_KIND or not tree.get("required_for_generation"):
        errors.append("project_decomposition_tree.required")
    nodes = [item for item in tree.get("nodes", []) if isinstance(item, Mapping)]
    ids = {str(item.get("node_id", "")) for item in nodes}
    if len(ids) != len(nodes) or "" in ids:
        errors.append("project_decomposition_tree.unique_node_ids")
    required_fields = {"node_id", "node_type", "parent_id", "title", "expected_behavior", "target_files", "required_evidence", "status", "current_evidence", "mapped_issues"}
    for item in nodes:
        node_id = str(item.get("node_id", ""))
        if not required_fields.issubset(item):
            errors.append(f"project_decomposition_tree.node_fields:{node_id}")
        if item.get("node_type") not in NODE_TYPES:
            errors.append(f"project_decomposition_tree.node_type:{node_id}")
        if item.get("status") not in NODE_STATUSES:
            errors.append(f"project_decomposition_tree.node_status:{node_id}")
        parent = str(item.get("parent_id", ""))
        if parent and parent not in ids:
            errors.append(f"project_decomposition_tree.parent:{node_id}:{parent}")
    return sorted(set(errors))


def _failure_text(issue: Mapping[str, Any]) -> str:
    keys = ("requirement", "failed_requirement", "symptom", "expected_behavior", "observed_behavior", "user_action", "root_cause_key")
    return " ".join(str(issue.get(key, "")) for key in keys).lower()


def infer_tree_node_id(issue: Mapping[str, Any], tree: Mapping[str, Any]) -> str:
    requested = str(issue.get("tree_node_id", "")).strip()
    nodes = {str(item.get("node_id", "")): item for item in tree.get("nodes", []) if isinstance(item, Mapping)}
    if requested in nodes:
        return requested
    text = _failure_text(issue)
    rules = [
        (("selenium", "canonical verifier", "forbidden import"), "test_contract.canonical_verifier"),
        (("missing expected symbol", "expected symbols: main", "missing symbol main"), "semantic_contract.main_entry"),
        (("static root", "root route", "http 404", "startup", "404"), "capability.static_web_entry"),
        (("upload", "import csv", "csv import"), "capability.csv_upload"),
        (("clean", "preview"), "capability.clean_preview"),
        (("export csv", "download csv"), "capability.export_csv"),
        (("delivery", "clean unpack", "package identity"), "capability.delivery_evidence"),
        (("dom", "selector", "element id"), "capability.dom_alignment"),
        (("create", "edit", "delete", "crud"), "capability.crud"),
        (("move", "status"), "capability.move_status"),
        (("persist", "reload", "localstorage"), "capability.persistence"),
        (("export", "download"), "capability.export"),
    ]
    for tokens, node_id in rules:
        if node_id in nodes and any(token in text for token in tokens):
            return node_id
    paths = [
        _normalize_path(item)
        for item in issue.get("affected_files", [])
        if _normalize_path(item)
    ]
    for path in paths:
        matching_capabilities = [
            node_id for node_id, node in nodes.items()
            if node.get("node_type") == "capability" and path in node.get("target_files", [])
        ]
        if len(matching_capabilities) == 1:
            return matching_capabilities[0]
        candidate = file_node_id(path)
        if candidate in nodes:
            return candidate
    return ""


def bind_issues_to_tree(tree: Mapping[str, Any], issues: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated_tree = copy.deepcopy(dict(tree))
    nodes = {str(item.get("node_id", "")): item for item in updated_tree.get("nodes", []) if isinstance(item, dict)}
    bound: list[dict[str, Any]] = []
    mappings: list[dict[str, str]] = []
    for raw in issues:
        issue = copy.deepcopy(dict(raw))
        node_id = infer_tree_node_id(issue, updated_tree)
        issue_id = str(issue.get("issue_id", ""))
        if not node_id:
            issue.update({
                "tree_node_id": "",
                "issue_type": "unmapped_failure",
                "repairable": False,
                "repair_route": "halt",
                "evidence_disposition": "OBSERVED_PRODUCT_FAILURE_UNMAPPED_TREE_NODE",
            })
        else:
            issue["tree_node_id"] = node_id
            node = nodes[node_id]
            if issue_id and issue_id not in node["mapped_issues"]:
                node["mapped_issues"].append(issue_id)
            fatal = str(issue.get("issue_type", "")) in {"unsafe_path", "fake_artifact", "malformed_provider"} or str(issue.get("severity", "")).upper() == "FATAL"
            node["status"] = "fatal_fail" if fatal else ("repairable_fail" if issue.get("repairable") else "fail")
            mappings.append({"issue_id": issue_id, "tree_node_id": node_id})
        bound.append(issue)
    issue_tree = dict(updated_tree.get("issue_tree", {}))
    issue_tree["mappings"] = mappings
    issue_tree["node_ids"] = list(nodes)
    updated_tree["issue_tree"] = issue_tree
    return with_tree_hash(updated_tree), bound


def update_evidence(tree: Mapping[str, Any], *, node_id: str, evidence: Mapping[str, Any], status: str) -> dict[str, Any]:
    if status not in NODE_STATUSES:
        raise ValueError(f"invalid decomposition evidence status: {status}")
    updated = copy.deepcopy(dict(tree))
    node = next((item for item in updated.get("nodes", []) if isinstance(item, dict) and item.get("node_id") == node_id), None)
    if node is None:
        raise KeyError(f"unknown decomposition tree node: {node_id}")
    record = dict(evidence)
    node["current_evidence"].append(record)
    node["status"] = status
    evidence_tree = dict(updated.get("evidence_tree", {}))
    updates = list(evidence_tree.get("updates", []))
    updates.append({"tree_node_id": node_id, "status": status, "evidence": record})
    evidence_tree["updates"] = updates
    updated["evidence_tree"] = evidence_tree
    return with_tree_hash(updated)


def apply_evidence_updates(tree: Mapping[str, Any], updates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(dict(tree))
    for row in updates:
        if not isinstance(row, Mapping) or not str(row.get("tree_node_id", "")).strip():
            continue
        result = update_evidence(
            result,
            node_id=str(row["tree_node_id"]),
            status=str(row.get("status", "pass")),
            evidence=row.get("evidence", {}) if isinstance(row.get("evidence"), Mapping) else {},
        )
    return result


def write_tree(path: pathlib.Path, tree: Mapping[str, Any]) -> None:
    errors = validate_tree(tree)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(with_tree_hash(tree), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def semantic_failure_is_repairable(message: Any) -> bool:
    text = str(message or "").lower()
    fatal = any(token in text for token in ("unsafe path", "path traversal", "fake artifact", "fake zip", "malformed provider", "no files returned", "missing files[]"))
    repairable = any(token in text for token in ("missing expected symbol", "expected symbols: main", "selenium", "canonical verifier"))
    return bool(repairable and not fatal)


def semantic_failure_evidence(classifications: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize repairable semantic findings for the unified issue ledger."""
    records: list[dict[str, Any]] = []
    for raw in classifications.get("repairable_fact_blocker", []):
        text = str(raw.get("message", raw.get("raw", raw)) if isinstance(raw, Mapping) else raw)
        lowered = text.lower()
        if not semantic_failure_is_repairable(text):
            continue
        if "selenium" in lowered or "canonical verifier" in lowered:
            path_match = re.search(r"(?:^|\s)((?:tests?/)[A-Za-z0-9_./-]+\.py)\b", text)
            path = _normalize_path(path_match.group(1)) if path_match else ""
            node_id = "test_contract.canonical_verifier"
            expected = "Generated tests use the canonical verifier and no test-local Selenium lane."
        else:
            path = "app/main.py"
            node_id = "semantic_contract.main_entry"
            expected = "app/main.py exposes the expected main/start entry."
        records.append(
            {
                "evaluator_failure_id": f"semantic:{node_id}",
                "criterion_id": node_id,
                "status": "FAIL",
                "expected_behavior": expected,
                "observed_behavior": text,
                "affected_files": [path] if path else [],
                "tree_node_id": node_id,
                "repair_route": "provider",
                "authority": "provider_semantic_review",
            }
        )
    return records


def attach_semantic_issue_evidence(
    finalize_result: Mapping[str, Any],
    classifications: Mapping[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(finalize_result))
    records = semantic_failure_evidence(classifications)
    if records:
        result["semantic_issue_evidence"] = records
        result["status"] = "needs_rework"
        result["candidate_review_ready"] = False
    return result
