from __future__ import annotations

import json
import pathlib
from typing import Any

from cgnk_core.diagnostics import CGNK_MIGRATION_PROOF_MISSING, Diagnostic
from cgnk_core.registry import ContractRegistry
from cgnk_core.refs import ref_of

from .feature_map import SELECTED_FEATURES, rejected_features, selected_features

REQUIRED_PRESERVE = {
    "cli_args",
    "summary_json_schema",
    "benchmark_report_format",
    "provider_call_semantics",
    "timeout_guard_semantics",
    "file_hash_cache_evidence",
    "support decision flow",
    "repo hygiene guard",
}


def check_migration_spec(spec: dict[str, Any], registry: ContractRegistry, ctcp_root: pathlib.Path | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    legacy_files = spec.get("legacy", {}).get("files", [])
    if ctcp_root is not None:
        for rel in legacy_files:
            if not (ctcp_root / rel).exists():
                diagnostics.append(Diagnostic(CGNK_MIGRATION_PROOF_MISSING, "error", f"legacy.files.{rel}", "Legacy entrypoint/proof file is missing", actual=rel))
    target = spec.get("target", {})
    for module_ref in target.get("modules", []):
        if registry.resolve_module(module_ref) is None:
            diagnostics.append(Diagnostic(CGNK_MIGRATION_PROOF_MISSING, "error", "target.modules", "Target module cannot be resolved", actual=module_ref))
    flow_ref = target.get("flow")
    if flow_ref and registry.resolve_flow(flow_ref) is None:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_PROOF_MISSING, "error", "target.flow", "Target flow cannot be resolved", actual=flow_ref))
    preserve = set(k for k, v in spec.get("preserve", {}).items() if v)
    missing_preserve = sorted(REQUIRED_PRESERVE - preserve)
    for key in missing_preserve:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_PROOF_MISSING, "warning", f"preserve.{key}", "Recommended external behavior preserve proof is missing", actual=key))
    return {
        "kind": "MigrationReport",
        "migration_ref": ref_of(spec),
        "ok": not any(d.severity == "error" for d in diagnostics),
        "diagnostics": [d.as_dict() for d in diagnostics],
        "selected": selected_features(),
        "rejected": rejected_features(),
        "deferred": {k: v for k, v in SELECTED_FEATURES.items() if v.get("status") == "deferred"},
    }


def write_reports(report: dict[str, Any], output_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "migration_report.json"
    md_path = output_dir / "migration_report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [f"# Migration Report: {report['migration_ref']}", "", f"OK: {report['ok']}", "", "## Selected"]
    lines.extend(f"- {name}: {', '.join(row.get('maps_to', []))}" for name, row in report["selected"].items())
    lines.extend(["", "## Rejected"])
    lines.extend(f"- {name}: {row.get('reason', '')}" for name, row in report["rejected"].items())
    lines.extend(["", "## Diagnostics"])
    lines.extend(f"- {d['severity']} {d['code']} {d['path']}: {d['message']}" for d in report["diagnostics"])
    return "\n".join(lines) + "\n"
