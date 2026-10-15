#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_DOCS = [
    "README.md",
    "PRODUCT_GOAL.md",
    "docs/00_product_studio_contract.md",
    "docs/01_virtual_team_contract.md",
    "docs/02_product_story_contract.md",
    "docs/03_execution_flow.md",
    "docs/04_acceptance_and_evidence.md",
    "docs/05_agent_operating_contract.md",
    "docs/06_agent_led_layered_architecture.md",
]

README_PHRASES = [
    "AI agile engineering kernel",
    "capability/interface DAGs",
    "canonical evidence",
    "delivery_manifest",
]

PRODUCT_GOAL_PHRASES = [
    "agent 主控",
    "契约护航",
    "虚拟团队",
    "测试证据",
    "交付包",
]

ARCHITECTURE_PHRASES = [
    "CGKN is agent-led and contract-guarded",
    "The Lead Agent controls the project run",
    "Layers do not control the run",
    "Modules are capabilities selected by agents",
    "Artifacts are work records and handoff objects produced by agents",
    "The contract compiler validates the run",
]

MAINLINE_ARTIFACTS = [
    "customer_intent",
    "output_contract",
    "virtual_team_roster",
    "product_story",
    "mvp_scope",
    "technical_plan",
    "build_plan",
    "generated_project",
    "test_evidence",
    "delivery_manifest",
]

PASS_CONDITION_ITEMS = [
    "runnable_project",
    "test_data",
    "test_report",
    "visual_evidence",
    "delivery_manifest",
]

PRODUCT_STUDIO_RUN_ARTIFACTS = [
    "customer_intent",
    "output_contract",
    "virtual_team_roster",
    "product_story",
    "mvp_scope",
    "technical_plan",
    "build_plan",
    "test_evidence",
    "delivery_bundle",
]

PRODUCT_STUDIO_RUN_SCHEMA = "schemas/product_studio_run.schema.json"
PRODUCT_STUDIO_RUN_EXAMPLE = "examples/product_studio/minimal_gui_tool/product_studio_run.json"

DELIVERY_REQUIRED_FILES = [
    "delivery_bundle.json",
    "delivery_bundle.zip",
    "test_report.json",
    "visual_evidence/visual_evidence.json",
    "known_limits.md",
    "revision_entry.json",
]


@dataclass
class ContractIssue:
    type: str
    path: str
    item: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "path": self.path,
            "item": self.item,
            "message": self.message,
        }


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json_file(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_issue(issues: list[ContractIssue], type_: str, path: str, item: str, message: str) -> None:
    issues.append(ContractIssue(type_, path, item, message))


def add_missing_file_issues(issues: list[ContractIssue], root: pathlib.Path, rel_paths: list[str]) -> None:
    for rel_path in rel_paths:
        if not (root / rel_path).exists():
            add_issue(
                issues,
                "missing_file",
                rel_path,
                rel_path,
                f"Required Product Studio contract file is missing: {rel_path}",
            )


def add_missing_phrase_issues(
    issues: list[ContractIssue],
    root: pathlib.Path,
    rel_path: str,
    phrases: list[str],
) -> None:
    path = root / rel_path
    if not path.exists():
        return
    text = read_text(path)
    for phrase in phrases:
        if phrase not in text:
            add_issue(
                issues,
                "missing_phrase",
                rel_path,
                phrase,
                f"{rel_path} must contain phrase: {phrase}",
            )


def add_missing_contract_item_issues(
    issues: list[ContractIssue],
    corpus: str,
    items: list[str],
    group: str,
) -> None:
    for item in items:
        if item not in corpus:
            add_issue(
                issues,
                "missing_contract_item",
                group,
                item,
                f"Product Studio contract must preserve {group}: {item}",
            )


def load_contract_corpus(root: pathlib.Path) -> str:
    parts: list[str] = []
    for rel_path in REQUIRED_DOCS:
        path = root / rel_path
        if path.exists():
            parts.append(read_text(path))
    return "\n".join(parts)


def has_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def contains_any(values: Any, candidates: set[str]) -> bool:
    if isinstance(values, list):
        haystack = " ".join(str(value) for value in values)
    else:
        haystack = str(values)
    haystack = haystack.lower()
    return any(candidate.lower() in haystack for candidate in candidates)


def display_path(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def validate_product_studio_run_schema(
    issues: list[ContractIssue],
    root: pathlib.Path,
    run_doc: Any,
    run_file_label: str,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "available": False,
        "status": "skipped_schema_validation",
        "validated": False,
    }
    schema_path = root / PRODUCT_STUDIO_RUN_SCHEMA
    if not schema_path.exists() or run_doc is None:
        return status

    try:
        import jsonschema  # type: ignore
    except ImportError:
        return status

    try:
        jsonschema.validate(run_doc, load_json_file(schema_path))
    except Exception as exc:
        add_issue(
            issues,
            "missing_contract_item",
            run_file_label,
            "schema_validation",
            f"{run_file_label} does not satisfy {PRODUCT_STUDIO_RUN_SCHEMA}: {exc}",
        )
        return {"available": True, "status": "fail", "validated": False}

    return {"available": True, "status": "pass", "validated": True}


def add_product_studio_run_checks(
    issues: list[ContractIssue],
    run_doc: Any,
    run_file_label: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": ok, "message": message})
        if not ok:
            add_issue(issues, "missing_contract_item", run_file_label, name, message)

    if not isinstance(run_doc, dict):
        record("product_studio_run_is_object", False, "product_studio_run.json must be a JSON object.")
        return checks

    for artifact in PRODUCT_STUDIO_RUN_ARTIFACTS:
        record(
            f"has_{artifact}",
            artifact in run_doc,
            f"product_studio_run.json must contain top-level artifact: {artifact}.",
        )

    output_contract = run_doc.get("output_contract", {})
    required_outputs = output_contract.get("required_outputs", []) if isinstance(output_contract, dict) else []
    record(
        "required_outputs_include_test_report",
        contains_any(required_outputs, {"test_report"}),
        "output_contract.required_outputs must include test_report.",
    )
    record(
        "required_outputs_include_visual_evidence_or_screenshots",
        contains_any(required_outputs, {"visual_evidence", "screenshots"}),
        "output_contract.required_outputs must include visual_evidence or screenshots.",
    )

    product_story = run_doc.get("product_story", {})
    record(
        "product_story_acceptance_implications_non_empty",
        isinstance(product_story, dict) and has_non_empty(product_story.get("acceptance_implications")),
        "product_story.acceptance_implications must be non-empty.",
    )

    virtual_team_roster = run_doc.get("virtual_team_roster", {})
    team_text = json.dumps(virtual_team_roster, ensure_ascii=False).lower()
    record(
        "virtual_team_has_lead_agent",
        "lead agent" in team_text,
        "virtual_team_roster must contain Lead Agent.",
    )
    record(
        "virtual_team_has_qa_engineer",
        "qa engineer" in team_text,
        "virtual_team_roster must contain QA Engineer.",
    )

    test_evidence = run_doc.get("test_evidence", {})
    record(
        "test_evidence_status_exists",
        isinstance(test_evidence, dict) and has_non_empty(test_evidence.get("status")),
        "test_evidence.status must exist.",
    )

    delivery_bundle = run_doc.get("delivery_bundle", {})
    record(
        "delivery_bundle_status_exists",
        isinstance(delivery_bundle, dict) and has_non_empty(delivery_bundle.get("status")),
        "delivery_bundle.status must exist.",
    )
    record(
        "delivery_bundle_included_evidence_non_empty",
        isinstance(delivery_bundle, dict) and has_non_empty(delivery_bundle.get("included_evidence")),
        "delivery_bundle.included_evidence must be non-empty.",
    )

    return checks


def load_product_studio_run(issues: list[ContractIssue], path: pathlib.Path, label: str) -> Any:
    if not path.exists():
        return None
    try:
        return load_json_file(path)
    except json.JSONDecodeError as exc:
        add_issue(
            issues,
            "missing_contract_item",
            label,
            "valid_json",
            f"{label} must be valid JSON: {exc}",
        )
        return None


def check_delivery_artifacts(
    issues: list[ContractIssue],
    run_path: pathlib.Path,
    root: pathlib.Path,
) -> dict[str, Any]:
    delivery_dir = run_path.parent
    delivery_bundle_path = delivery_dir / "delivery_bundle.json"
    delivery_detected = delivery_bundle_path.exists()
    checked: list[dict[str, Any]] = []

    def record(rel_path: str, ok: bool) -> None:
        checked.append({"path": rel_path, "ok": ok})
        if not ok:
            add_issue(
                issues,
                "missing_file",
                display_path(delivery_dir / rel_path, root),
                rel_path,
                f"Detected delivery bundle is missing required delivery artifact: {rel_path}",
            )

    if delivery_detected:
        for rel_path in DELIVERY_REQUIRED_FILES:
            record(rel_path, (delivery_dir / rel_path).exists())

    return {
        "delivery_detected": delivery_detected,
        "delivery_bundle_checked": delivery_detected and (delivery_dir / "delivery_bundle.json").exists(),
        "delivery_zip_checked": delivery_detected and (delivery_dir / "delivery_bundle.zip").exists(),
        "visual_evidence_checked": delivery_detected
        and (delivery_dir / "visual_evidence" / "visual_evidence.json").exists(),
        "delivery_dir": display_path(delivery_dir, root),
        "checked_files": checked,
    }


def check_root(root: pathlib.Path, run_file: pathlib.Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    issues: list[ContractIssue] = []

    add_missing_file_issues(issues, root, REQUIRED_DOCS)
    if run_file is None:
        add_missing_file_issues(issues, root, [PRODUCT_STUDIO_RUN_SCHEMA, PRODUCT_STUDIO_RUN_EXAMPLE])
        run_path = root / PRODUCT_STUDIO_RUN_EXAMPLE
        run_label = PRODUCT_STUDIO_RUN_EXAMPLE
    else:
        add_missing_file_issues(issues, root, [PRODUCT_STUDIO_RUN_SCHEMA])
        run_path = run_file if run_file.is_absolute() else root / run_file
        run_label = display_path(run_path, root)
        if not run_path.exists():
            add_issue(issues, "missing_file", run_label, run_label, f"Product Studio run file is missing: {run_label}")

    add_missing_phrase_issues(issues, root, "README.md", README_PHRASES)
    add_missing_phrase_issues(issues, root, "PRODUCT_GOAL.md", PRODUCT_GOAL_PHRASES)
    add_missing_phrase_issues(
        issues,
        root,
        "docs/06_agent_led_layered_architecture.md",
        ARCHITECTURE_PHRASES,
    )

    corpus = load_contract_corpus(root)
    add_missing_contract_item_issues(issues, corpus, MAINLINE_ARTIFACTS, "mainline_artifact")
    add_missing_contract_item_issues(issues, corpus, PASS_CONDITION_ITEMS, "pass_condition")

    run_doc = load_product_studio_run(issues, run_path, run_label)
    schema_validation_status = validate_product_studio_run_schema(issues, root, run_doc, run_label)
    product_studio_cross_checks = add_product_studio_run_checks(issues, run_doc, run_label)
    delivery_status = check_delivery_artifacts(issues, run_path, root)

    return {
        "ok": not issues,
        "root": str(root),
        "checked_files": REQUIRED_DOCS,
        "product_studio_schema_checked": PRODUCT_STUDIO_RUN_SCHEMA,
        "product_studio_example_checked": run_label,
        "schema_validation_status": schema_validation_status,
        "product_studio_cross_checks": product_studio_cross_checks,
        "delivery_detected": delivery_status["delivery_detected"],
        "delivery_bundle_checked": delivery_status["delivery_bundle_checked"],
        "delivery_zip_checked": delivery_status["delivery_zip_checked"],
        "visual_evidence_checked": delivery_status["visual_evidence_checked"],
        "delivery_status": delivery_status,
        "checks": {
            "readme_phrases": README_PHRASES,
            "product_goal_phrases": PRODUCT_GOAL_PHRASES,
            "architecture_phrases": ARCHITECTURE_PHRASES,
            "mainline_artifacts": MAINLINE_ARTIFACTS,
            "pass_condition_items": PASS_CONDITION_ITEMS,
            "product_studio_run_artifacts": PRODUCT_STUDIO_RUN_ARTIFACTS,
        },
        "issues": [issue.as_dict() for issue in issues],
    }


def print_human_report(result: dict[str, Any]) -> None:
    status = "PASS" if result["ok"] else "FAIL"
    print(f"Product Studio contract check: {status}")
    print(f"Root: {result['root']}")
    print(f"Required docs checked: {len(result['checked_files'])}")
    print(f"Product Studio schema checked: {result['product_studio_schema_checked']}")
    print(f"Product Studio example checked: {result['product_studio_example_checked']}")
    print(f"Schema validation: {result['schema_validation_status']['status']}")
    print(f"Delivery detected: {result['delivery_detected']}")
    if result["delivery_detected"]:
        print(f"Delivery bundle checked: {result['delivery_bundle_checked']}")
        print(f"Delivery zip checked: {result['delivery_zip_checked']}")
        print(f"Visual evidence checked: {result['visual_evidence_checked']}")
    print("Contract groups checked:")
    print("  - README positioning phrases")
    print("  - PRODUCT_GOAL Chinese positioning phrases")
    print("  - agent-led layered architecture phrases")
    print("  - Product Studio mainline artifacts")
    print("  - PASS delivery condition items")
    print("  - compact product_studio_run structure")
    print("  - compact product_studio_run cross-checks")
    if result["ok"]:
        print("Issues: 0")
        return

    print(f"Issues: {len(result['issues'])}")
    for issue in result["issues"]:
        print(f"- {issue['type']}: {issue['path']} :: {issue['item']}")
        print(f"  {issue['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Product Studio Markdown and compact run invariants.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="Repository root to check.")
    parser.add_argument("--run-file", type=pathlib.Path, help="Product Studio run JSON file to check instead of the default example.")
    args = parser.parse_args(argv)

    result = check_root(args.root, args.run_file)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_report(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
