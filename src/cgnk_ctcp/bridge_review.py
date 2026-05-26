from __future__ import annotations

import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_CTCP_BRIDGE_DEFAULT_BEHAVIOR_RISK,
    CGNK_CTCP_BRIDGE_FORBIDDEN_EFFECT,
    CGNK_CTCP_BRIDGE_FORBIDDEN_FILE,
    CGNK_CTCP_BRIDGE_PROVIDER_SEMANTICS_RISK,
    CGNK_CTCP_BRIDGE_REVIEW_INVALID,
    CGNK_CTCP_BRIDGE_ROLLBACK_MISSING,
    CGNK_CTCP_BRIDGE_TESTS_MISSING,
    Diagnostic,
)
from cgnk_core.schema_loader import SchemaLoader

ALLOWED_TARGET_REPO = "CTCP"
ALLOWED_FILE_PREFIXES = ("tools/", "tests/")
ALLOWED_FILE_KEYWORDS = ("project_generation", "cgnk_project_generation", "bridge", "adapter", "adaptor")
FORBIDDEN_FILE_TOKENS = (
    ".db",
    ".sqlite",
    ".zip",
    "final_output",
    "project_output",
    "telegram",
    "support_bot",
    "support-bot",
    "support/bot",
    "bot/",
    "orchestrator",
    "runner_chain",
)


def review_ctcp_bridge(
    proposal: dict[str, Any],
    patch_manifest: dict[str, Any],
    *,
    schema_loader: SchemaLoader | None = None,
) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    if schema_loader is not None:
        diagnostics.extend(
            Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
            for d in schema_loader.validate(proposal, "ctcp_bridge_proposal.schema.json", "$.proposal")
        )
        diagnostics.extend(
            Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
            for d in schema_loader.validate(patch_manifest, "ctcp_patch_manifest.schema.json", "$.patch_manifest")
        )

    target_feature = _target_feature(proposal, patch_manifest)
    proposed_files = _proposed_files(proposal, patch_manifest)
    preserved_entrypoints = _string_list(proposal.get("public_entrypoints_to_preserve"))
    required_tests = _string_list(proposal.get("required_tests"))

    _check_target_repo(proposal, patch_manifest, diagnostics)
    _check_feature_match(proposal, patch_manifest, diagnostics)
    _check_default_and_opt_in(proposal, proposed_files, diagnostics)
    _check_provider_semantics(proposal, diagnostics)
    _check_forbidden_effects(proposal, patch_manifest, diagnostics)
    _check_entrypoints_and_tests(preserved_entrypoints, required_tests, diagnostics)
    _check_rollback(proposal, diagnostics)
    _check_files(proposed_files, diagnostics)
    _check_patch_matches_proposal(proposal, patch_manifest, diagnostics)
    _check_structured_diagnostics(proposal, "$.proposal.diagnostics", diagnostics)
    _check_structured_diagnostics(patch_manifest, "$.patch_manifest.diagnostics", diagnostics)

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    violations = [row for row in diagnostic_dicts if row["severity"] == "error"]
    warnings = [row for row in diagnostic_dicts if row["severity"] == "warning"]
    risk_summary = {
        "target_repo_external": proposal.get("target_repo") == ALLOWED_TARGET_REPO and patch_manifest.get("target_repo") == ALLOWED_TARGET_REPO,
        "read_only_review": proposal.get("patch_apply") is False and proposal.get("workspace_write") is False and patch_manifest.get("patch_apply") is False and patch_manifest.get("workspace_write") is False,
        "default_behavior_unchanged": proposal.get("default_behavior_unchanged") is True,
        "opt_in_only": _opt_in_only(proposal, proposed_files),
        "provider_semantics_unchanged": proposal.get("provider_semantics_unchanged") is True,
        "patch_apply": bool(proposal.get("patch_apply") or patch_manifest.get("patch_apply")),
        "workspace_write": bool(proposal.get("workspace_write") or patch_manifest.get("workspace_write")),
        "forbidden_file_count": sum(1 for row in diagnostic_dicts if row["code"] == CGNK_CTCP_BRIDGE_FORBIDDEN_FILE),
        "forbidden_effect_count": sum(1 for row in diagnostic_dicts if row["code"] == CGNK_CTCP_BRIDGE_FORBIDDEN_EFFECT),
    }
    approval_status = "blocked" if violations else ("review_required" if warnings else "approvable")
    return {
        "kind": "CTCPBridgeReview",
        "version": "1",
        "ok": not violations,
        "approval_status": approval_status,
        "target_feature": target_feature,
        "proposed_files": proposed_files,
        "preserved_entrypoints": preserved_entrypoints,
        "risk_summary": risk_summary,
        "required_tests": required_tests,
        "violations": violations,
        "warnings": warnings,
        "diagnostics": diagnostic_dicts,
    }


def _target_feature(proposal: dict[str, Any], patch_manifest: dict[str, Any]) -> str:
    value = proposal.get("target_feature") or patch_manifest.get("target_feature")
    return value if isinstance(value, str) else ""


def _proposed_files(proposal: dict[str, Any], patch_manifest: dict[str, Any]) -> list[str]:
    files: set[str] = set()
    for row in proposal.get("proposed_files", []):
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            files.add(_normalize_path(row["path"]))
    for row in patch_manifest.get("file_changes", []):
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            files.add(_normalize_path(row["path"]))
    return sorted(files)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if str(item).strip())


def _check_target_repo(proposal: dict[str, Any], patch_manifest: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    for label, doc in (("proposal", proposal), ("patch_manifest", patch_manifest)):
        if doc.get("target_repo") != ALLOWED_TARGET_REPO:
            diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", f"$.{label}.target_repo", "Bridge review must target CTCP as an external repository", expected=ALLOWED_TARGET_REPO, actual=doc.get("target_repo")))


def _check_feature_match(proposal: dict[str, Any], patch_manifest: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    if proposal.get("target_feature") != patch_manifest.get("target_feature"):
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", "$.target_feature", "Proposal and patch manifest must target the same CTCP feature", expected=proposal.get("target_feature"), actual=patch_manifest.get("target_feature")))


def _check_default_and_opt_in(proposal: dict[str, Any], proposed_files: list[str], diagnostics: list[Diagnostic]) -> None:
    if proposal.get("default_behavior_unchanged") is not True:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_DEFAULT_BEHAVIOR_RISK, "error", "$.proposal.default_behavior_unchanged", "Bridge proposal must preserve default CTCP behavior", expected=True, actual=proposal.get("default_behavior_unchanged")))
    if not _opt_in_only(proposal, proposed_files):
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_DEFAULT_BEHAVIOR_RISK, "error", "$.proposal.optional_new_entrypoints", "Bridge must be opt-in only through explicit bridge or adapter entrypoints", expected="optional bridge/adaptor entrypoint", actual=proposal.get("optional_new_entrypoints")))


def _check_provider_semantics(proposal: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    if proposal.get("provider_semantics_unchanged") is not True:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_PROVIDER_SEMANTICS_RISK, "error", "$.proposal.provider_semantics_unchanged", "Bridge proposal must preserve provider semantics", expected=True, actual=proposal.get("provider_semantics_unchanged")))


def _check_forbidden_effects(proposal: dict[str, Any], patch_manifest: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    for label, doc in (("proposal", proposal), ("patch_manifest", patch_manifest)):
        if doc.get("patch_apply") is not False:
            diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_FORBIDDEN_EFFECT, "error", f"$.{label}.patch_apply", "Bridge review artifacts must not apply patches", expected=False, actual=doc.get("patch_apply")))
        if doc.get("workspace_write") is not False:
            diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_FORBIDDEN_EFFECT, "error", f"$.{label}.workspace_write", "Bridge review artifacts must not write workspaces", expected=False, actual=doc.get("workspace_write")))


def _check_entrypoints_and_tests(preserved_entrypoints: list[str], required_tests: list[str], diagnostics: list[Diagnostic]) -> None:
    if not preserved_entrypoints:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_DEFAULT_BEHAVIOR_RISK, "error", "$.proposal.public_entrypoints_to_preserve", "Public CTCP entrypoints to preserve must be listed", expected="non-empty list", actual=preserved_entrypoints))
    if not required_tests:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_TESTS_MISSING, "error", "$.proposal.required_tests", "Bridge proposal must list required regression tests", expected="non-empty list", actual=required_tests))


def _check_rollback(proposal: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    rollback = proposal.get("rollback_plan")
    if not isinstance(rollback, str) or not rollback.strip():
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_ROLLBACK_MISSING, "error", "$.proposal.rollback_plan", "Bridge proposal must include rollback plan", expected="non-empty string", actual=rollback))


def _check_files(proposed_files: list[str], diagnostics: list[Diagnostic]) -> None:
    if not proposed_files:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_FORBIDDEN_FILE, "error", "$.proposed_files", "Bridge proposal must declare proposed CTCP files", expected="project_generation bridge/adaptor/test paths", actual=[]))
        return
    for path in proposed_files:
        lowered = path.lower()
        allowed_prefix = lowered.startswith(ALLOWED_FILE_PREFIXES)
        allowed_keyword = "project_generation" in lowered and any(keyword in lowered for keyword in ("bridge", "adapter", "adaptor"))
        if not allowed_prefix or not allowed_keyword:
            diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_FORBIDDEN_FILE, "error", "$.proposed_files", "Proposed files must be limited to project_generation bridge/adaptor/test paths", expected="tools/tests project_generation bridge/adaptor path", actual=path, source={"path": path}))
        for token in FORBIDDEN_FILE_TOKENS:
            if token in lowered:
                diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_FORBIDDEN_FILE, "error", "$.proposed_files", "Bridge proposal must not introduce DB/sqlite, zip, generated output, bot, or orchestrator paths", expected="clean bridge/adaptor/test path", actual=path, source={"path": path, "forbidden_token": token}))


def _check_patch_matches_proposal(proposal: dict[str, Any], patch_manifest: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    proposal_paths = {row.get("path") for row in proposal.get("proposed_files", []) if isinstance(row, dict)}
    patch_paths = {row.get("path") for row in patch_manifest.get("file_changes", []) if isinstance(row, dict)}
    if proposal_paths != patch_paths:
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", "$.patch_manifest.file_changes", "Patch manifest file paths must match bridge proposal proposed files", expected=sorted(proposal_paths), actual=sorted(patch_paths)))


def _check_structured_diagnostics(doc: dict[str, Any], path: str, diagnostics: list[Diagnostic]) -> None:
    value = doc.get("diagnostics")
    if not isinstance(value, list):
        diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", path, "Diagnostics must be a list", expected="list", actual=type(value).__name__))
        return
    for index, row in enumerate(value):
        if not isinstance(row, dict) or not {"code", "severity", "path", "message"}.issubset(row):
            diagnostics.append(Diagnostic(CGNK_CTCP_BRIDGE_REVIEW_INVALID, "error", f"{path}[{index}]", "Diagnostics entries must be structured", expected=["code", "severity", "path", "message"], actual=row))


def _opt_in_only(proposal: dict[str, Any], proposed_files: list[str]) -> bool:
    optional = _string_list(proposal.get("optional_new_entrypoints"))
    if not optional:
        return False
    optional_paths = {_normalize_path(path).lower() for path in optional}
    proposed = {path.lower() for path in proposed_files}
    has_bridge_entrypoint = bool(optional_paths & proposed) or any("bridge" in path or "adapter" in path or "adaptor" in path for path in optional_paths)
    return has_bridge_entrypoint and proposal.get("default_behavior_unchanged") is True


def _normalize_path(path: str) -> str:
    return pathlib.PurePosixPath(path.replace("\\", "/")).as_posix()
