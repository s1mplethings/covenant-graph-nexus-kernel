from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_CTCP_CANDIDATE_INVALID,
    CGNK_CTCP_MODULE_INVENTORY_INVALID,
    CGNK_CTCP_NO_REUSABLE_MODULES_FOUND,
    CGNK_CTCP_ROOT_MISSING,
    CGNK_CTCP_SCAN_FAILED,
    CGNK_CTCP_TRANSFER_PLAN_INVALID,
    Diagnostic,
)
from cgnk_core.schema_loader import SchemaLoader

SCAN_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml"}
SKIP_PARTS = {
    ".git",
    "__pycache__",
    "final_output",
    "project_output",
    "generated",
    ".venv",
    "venv",
}


@dataclass(frozen=True)
class CapabilityRule:
    key: str
    keywords: tuple[str, ...]
    category: str
    module_ref: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    migration_value: str = "high"
    strategy: str = "recreate_from_contract"


CAPABILITY_RULES = [
    CapabilityRule("project_snapshot", ("snapshot",), "project_analysis", "module.project.snapshot@1", ("artifact.goal@1",), ("artifact.project_snapshot@1",)),
    CapabilityRule("file_index", ("file_index", "file index", "index_files"), "project_analysis", "module.project.file_index@1", ("artifact.project_snapshot@1",), ("artifact.project_graph@1",), "medium"),
    CapabilityRule("project_graph", ("project_graph", "project graph", "graph"), "project_analysis", "module.project.build_graph@1", ("artifact.project_snapshot@1",), ("artifact.project_graph@1",)),
    CapabilityRule("requirement_extraction", ("requirement", "requirements"), "input_understanding", "module.requirements.extract.contract_only@1", ("artifact.goal@1",), ("artifact.requirements@1",), "medium"),
    CapabilityRule("planning", ("plan", "planning"), "planning", "module.plan.generate.contract_only@1", ("artifact.goal@1", "artifact.project_graph@1"), ("artifact.implementation_plan@1",)),
    CapabilityRule("patch_manifest_generation", ("patch_manifest", "patch manifest", "manifest"), "patch_manifest", "module.patch.emit@1", ("artifact.implementation_plan@1", "artifact.project_snapshot@1"), ("artifact.patch_manifest@1",)),
    CapabilityRule("patch_validation", ("validate_patch", "patch validation", "patch_validate"), "validation", "module.patch.validate@1", ("artifact.patch_manifest@1", "artifact.project_snapshot@1"), ("artifact.validation_report@1",)),
    CapabilityRule("schema_validation", ("schema", "schema validation", "validate_schema"), "validation", "module.patch.validate@1", ("artifact.patch_manifest@1",), ("artifact.validation_report@1",), "medium"),
    CapabilityRule("benchmark_summary_parsing", ("benchmark_summary", "summary_json", "benchmark summary"), "benchmark", "module.benchmark.summary@1", ("artifact.benchmark_report@1",), ("artifact.benchmark_report@1",), "medium"),
    CapabilityRule("benchmark_report_generation", ("benchmark_report", "benchmark report", "report"), "reporting", "module.benchmark.summary@1", ("artifact.benchmark_report@1",), ("artifact.benchmark_report@1",), "medium"),
    CapabilityRule("provider_call_guard", ("provider", "provider_call", "provider guard"), "provider_boundary", "module.provider_call.guard@1", ("artifact.goal@1",), ("artifact.provider_guard_report@1",), "medium", "recreate_from_contract"),
    CapabilityRule("convergence_guard", ("convergence", "converge"), "guard", "module.convergence.guard@1", ("artifact.validation_report@1",), ("artifact.convergence_report@1",), "medium"),
    CapabilityRule("timeout_guard", ("timeout", "timeout_guard"), "guard", "module.timeout.guard@1", ("artifact.validation_report@1",), ("artifact.timeout_budget_report@1",), "medium"),
    CapabilityRule("trace_summary", ("trace", "trace_summary"), "diagnostics", "module.diagnostics.summary@1", ("artifact.validation_report@1",), ("artifact.diagnostics_summary@1",), "medium"),
    CapabilityRule("diagnostics_summary", ("diagnostics", "diagnostic_summary"), "diagnostics", "module.diagnostics.summary@1", ("artifact.validation_report@1",), ("artifact.diagnostics_summary@1",), "medium"),
    CapabilityRule("migration_proof", ("migration", "proof", "migration_proof"), "migration", "module.migration.proof@1", ("artifact.validation_report@1",), ("artifact.benchmark_report@1",), "high"),
    CapabilityRule("contract_validation", ("contract", "contract validation"), "contract", "module.patch.validate@1", ("artifact.patch_manifest@1",), ("artifact.validation_report@1",), "medium"),
    CapabilityRule("repair_planning", ("repair", "repair_plan", "repair planning"), "planning", "module.repair.plan@1", ("artifact.validation_report@1",), ("artifact.patch_manifest@1",), "high"),
]

LEGACY_GLUE_KEYWORDS = {
    "orchestrator",
    "runner",
    "cli",
    "telegram",
    "bot",
    "support",
    "progress",
    "fallback",
    "zip",
    "output",
    "final_output",
    "project_output",
    "db",
    "sqlite",
}


def discover_module_inventory(ctcp_root: pathlib.Path, schema_loader: SchemaLoader | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    diagnostics: list[Diagnostic] = []
    if not ctcp_root.exists() or not ctcp_root.is_dir():
        diagnostics.append(
            Diagnostic(
                CGNK_CTCP_ROOT_MISSING,
                "error",
                "$.ctcp_root",
                "CTCP root is missing",
                expected="existing directory",
                actual=str(ctcp_root),
                involved_ref=str(ctcp_root),
                source={"ctcp_root": str(ctcp_root)},
                repair_hints=[{"action": "pass --ctcp-root pointing at a legacy CTCP checkout"}],
            )
        )
        inventory = _inventory_doc(ctcp_root, [], diagnostics)
        return inventory, build_transfer_plan(inventory, schema_loader)

    scan_items: list[dict[str, Any]] = []
    try:
        for path in sorted(ctcp_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            rel = path.relative_to(ctcp_root).as_posix()
            if any(part in SKIP_PARTS for part in pathlib.PurePosixPath(rel).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            scan_items.append({"rel": rel, "text": text, "symbols": _symbols_for(path, text)})
    except OSError as exc:
        diagnostics.append(Diagnostic(CGNK_CTCP_SCAN_FAILED, "error", "$.scan", "CTCP scan failed", actual=str(exc), involved_ref=str(ctcp_root), source={"ctcp_root": str(ctcp_root)}))

    candidates = _discover_candidates(scan_items)
    if not any(c["classification"]["role"] == "reusable_middle_capability" for c in candidates):
        diagnostics.append(
            Diagnostic(
                CGNK_CTCP_NO_REUSABLE_MODULES_FOUND,
                "warning",
                "$.candidates",
                "No reusable middle capability modules were detected",
                expected="at least one reusable_middle_capability",
                actual=len(candidates),
                involved_ref=str(ctcp_root),
            )
        )

    inventory = _inventory_doc(ctcp_root, candidates, diagnostics)
    if schema_loader is not None:
        schema_diags = schema_loader.validate(inventory, "ctcp_module_inventory.schema.json", "$.inventory")
        inventory["diagnostics"].extend(
            Diagnostic(CGNK_CTCP_MODULE_INVENTORY_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual).as_dict()
            for d in schema_diags
        )
        inventory["ok"] = not any(d["severity"] == "error" for d in inventory["diagnostics"])
    transfer_plan = build_transfer_plan(inventory, schema_loader)
    return inventory, transfer_plan


def build_transfer_plan(inventory: dict[str, Any], schema_loader: SchemaLoader | None = None) -> dict[str, Any]:
    modules = []
    for candidate in inventory.get("candidates", []):
        value = candidate["classification"]["migration_value"]
        role = candidate["classification"]["role"]
        strategy = candidate["transfer"]["strategy"]
        if value == "reject" or role in {"fixed_pipeline_glue", "legacy_only"}:
            priority = "reject"
            action = "discard" if strategy == "discard" else "keep_reference"
        else:
            priority = {"high": "P0", "medium": "P1", "low": "P2"}.get(value, "P2")
            action = "keep_reference" if strategy == "keep_as_legacy_reference" else strategy
        modules.append(
            {
                "candidate": candidate["id"],
                "target_module": candidate["contract_guess"]["module_ref"],
                "priority": priority,
                "action": action,
                "copy_old_code": False,
                "notes": [
                    "Discovery output only; recreate behavior from ModuleContract and tests before migration.",
                    *candidate["transfer"].get("notes", []),
                ],
            }
        )
    plan = {
        "kind": "CTCPTransferPlan",
        "version": "1",
        "id": "ctcp_transfer_plan.discovered",
        "ok": True,
        "diagnostics": [],
        "modules": sorted(modules, key=lambda row: (row["priority"], row["candidate"])),
    }
    if schema_loader is not None:
        schema_diags = schema_loader.validate(plan, "ctcp_transfer_plan.schema.json", "$.transfer_plan")
        plan["diagnostics"].extend(
            Diagnostic(CGNK_CTCP_TRANSFER_PLAN_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual).as_dict()
            for d in schema_diags
        )
        plan["ok"] = not any(d["severity"] == "error" for d in plan["diagnostics"])
    return plan


def _discover_candidates(scan_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for rule in CAPABILITY_RULES:
        matches = _matches_for_rule(scan_items, rule.keywords)
        if matches:
            candidates.append(_candidate_from_rule(rule, matches))
    glue_matches = _matches_for_rule(scan_items, tuple(sorted(LEGACY_GLUE_KEYWORDS)))
    if glue_matches:
        candidates.append(_legacy_glue_candidate(glue_matches))
    return sorted(candidates, key=lambda row: row["id"])


def _matches_for_rule(scan_items: list[dict[str, Any]], keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    matches = []
    for item in scan_items:
        haystack = f"{item['rel']}\n{item['text']}\n{' '.join(item['symbols'])}".lower()
        evidence = sorted({kw for kw in keywords if kw in haystack})
        if evidence:
            matches.append({"rel": item["rel"], "symbols": _matching_symbols(item["symbols"], keywords), "evidence": evidence})
    return matches


def _candidate_from_rule(rule: CapabilityRule, matches: list[dict[str, Any]]) -> dict[str, Any]:
    files = sorted({m["rel"] for m in matches})
    symbols = sorted({sym for m in matches for sym in m["symbols"]})
    evidence = sorted({ev for m in matches for ev in m["evidence"]})
    role = "external_boundary" if rule.category in {"provider_boundary", "runtime_boundary"} else "reusable_middle_capability"
    strategy = rule.strategy
    recommended = role == "reusable_middle_capability" and rule.migration_value != "reject"
    return {
        "id": f"candidate.{rule.key}",
        "source": {"files": files, "symbols": symbols, "evidence": evidence},
        "classification": {"category": rule.category, "role": role, "migration_value": rule.migration_value},
        "contract_guess": {"module_ref": rule.module_ref, "inputs": list(rule.inputs), "outputs": list(rule.outputs)},
        "effects": _effects_from_evidence(files, symbols, evidence),
        "transfer": {
            "recommended": recommended,
            "strategy": strategy,
            "notes": ["Detected from path/symbol/keyword evidence; no CTCP code was executed or copied."],
        },
    }


def _legacy_glue_candidate(matches: list[dict[str, Any]]) -> dict[str, Any]:
    files = sorted({m["rel"] for m in matches})
    symbols = sorted({sym for m in matches for sym in m["symbols"]})
    evidence = sorted({ev for m in matches for ev in m["evidence"]})
    role = "legacy_only" if any(ev in {"telegram", "bot", "support", "progress", "fallback", "zip", "final_output", "project_output", "db", "sqlite"} for ev in evidence) else "fixed_pipeline_glue"
    return {
        "id": "candidate.legacy_glue",
        "source": {"files": files, "symbols": symbols, "evidence": evidence},
        "classification": {"category": "legacy_glue", "role": role, "migration_value": "reject"},
        "contract_guess": {"module_ref": "module.legacy.glue@1", "inputs": ["artifact.goal@1"], "outputs": ["artifact.validation_report@1"]},
        "effects": _effects_from_evidence(files, symbols, evidence),
        "transfer": {
            "recommended": False,
            "strategy": "discard",
            "notes": ["Fixed orchestration or legacy glue is not a reusable middle capability."],
        },
    }


def _effects_from_evidence(files: list[str], symbols: list[str], evidence: list[str]) -> dict[str, bool]:
    joined = " ".join([*files, *symbols, *evidence]).lower()
    fs_write = any(token in joined for token in ("patch", "manifest", "write", "output", "final_output", "project_output", "zip", "db", "sqlite"))
    return {
        "fs_read": any(token in joined for token in ("snapshot", "file", "index", "read", "schema", "contract", "benchmark")),
        "fs_write": fs_write,
        "network": any(token in joined for token in ("network", "http", "request", "provider")),
        "provider_call": any(token in joined for token in ("provider", "provider_call")),
    }


def _symbols_for(path: pathlib.Path, text: str) -> list[str]:
    if path.suffix.lower() != ".py":
        return _text_symbols(text)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _text_symbols(text)
    symbols: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.append(node.target.id)
    return sorted(set(symbols))


def _text_symbols(text: str) -> list[str]:
    return sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text)))[:100]


def _matching_symbols(symbols: list[str], keywords: tuple[str, ...]) -> list[str]:
    lowered = [(sym, sym.lower()) for sym in symbols]
    return sorted({sym for sym, lower in lowered if any(kw.replace(" ", "_") in lower or kw in lower for kw in keywords)})


def _inventory_doc(ctcp_root: pathlib.Path, candidates: list[dict[str, Any]], diagnostics: list[Diagnostic]) -> dict[str, Any]:
    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    return {
        "kind": "CTCPModuleInventorySpec",
        "version": "1",
        "id": "ctcp_module_inventory.discovered",
        "source_ctcp_root_hint": str(ctcp_root),
        "ok": not any(d["severity"] == "error" for d in diagnostic_dicts),
        "diagnostics": diagnostic_dicts,
        "candidates": candidates,
    }
