from __future__ import annotations

import ast
import importlib
import json
import pathlib
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from cgnk_core import ContractRegistry
from cgnk_core.diagnostics import (
    CGNK_MODULE_API_MISSING,
    CGNK_MODULE_CONTRACT_CONFORMANCE_FAILED,
    CGNK_MODULE_FORBIDDEN_EFFECT,
    CGNK_MODULE_FORBIDDEN_IMPORT,
    CGNK_MODULE_OUTPUT_SHAPE_INVALID,
    CGNK_MODULE_PACKAGE_MISSING,
    Diagnostic,
)

P0_MODULES = [
    {
        "module_ref": "module.project.snapshot@1",
        "package": "cgnk_modules.project_snapshot",
        "api": "collect_project_snapshot",
        "output_key": "snapshot",
        "contract_file": "examples/modules/project_snapshot.module.json",
    },
    {
        "module_ref": "module.project.build_graph@1",
        "package": "cgnk_modules.project_build_graph",
        "api": "build_project_graph",
        "output_key": "graph",
        "contract_file": "examples/modules/project_build_graph.module.json",
    },
    {
        "module_ref": "module.requirements.extract.contract_only@1",
        "package": "cgnk_modules.requirements_extract_contract_only",
        "api": "extract_requirements_contract_only",
        "output_key": "requirements",
        "contract_file": "examples/modules/requirements_extract_contract_only.module.json",
    },
    {
        "module_ref": "module.plan.generate.contract_only@1",
        "package": "cgnk_modules.plan_generate_contract_only",
        "api": "generate_contract_plan",
        "output_key": "plan",
        "contract_file": "examples/modules/plan_generate_contract_only.module.json",
    },
    {
        "module_ref": "module.patch.emit@1",
        "package": "cgnk_modules.patch_emit",
        "api": "emit_patch_manifest",
        "output_key": None,
        "contract_file": "examples/modules/patch_emit.module.json",
    },
    {
        "module_ref": "module.patch.validate@1",
        "package": "cgnk_modules.patch_validate",
        "api": "validate_patch_manifest",
        "output_key": "validation_report",
        "contract_file": "examples/modules/patch_validate.module.json",
    },
    {
        "module_ref": "module.repair.plan@1",
        "package": "cgnk_modules.repair_plan",
        "api": "build_repair_plan",
        "output_key": None,
        "contract_file": "examples/modules/repair_plan.module.json",
    },
    {
        "module_ref": "module.migration.proof@1",
        "package": "cgnk_modules.migration_proof",
        "api": "build_migration_proof",
        "output_key": None,
        "contract_file": "examples/modules/migration_proof.module.json",
    },
    {
        "module_ref": "module.diagnostics.summary@1",
        "package": "cgnk_modules.diagnostics_summary",
        "api": "summarize_diagnostics",
        "output_key": "summary",
        "contract_file": "examples/modules/diagnostics_summary.module.json",
    },
    {
        "module_ref": "module.benchmark.summary@1",
        "package": "cgnk_modules.benchmark_summary",
        "api": "summarize_benchmark_report",
        "output_key": "summary",
        "contract_file": "examples/modules/benchmark_summary.module.json",
    },
    {
        "module_ref": "module.convergence.guard@1",
        "package": "cgnk_modules.convergence_guard",
        "api": "evaluate_convergence",
        "output_key": "report",
        "contract_file": "examples/modules/convergence_guard.module.json",
    },
    {
        "module_ref": "module.timeout.guard@1",
        "package": "cgnk_modules.timeout_guard",
        "api": "evaluate_timeout_budget",
        "output_key": "budget_summary",
        "contract_file": "examples/modules/timeout_guard.module.json",
    },
    {
        "module_ref": "module.provider_call.guard@1",
        "package": "cgnk_modules.provider_call_guard",
        "api": "evaluate_provider_call_request",
        "output_key": "report",
        "contract_file": "examples/modules/provider_call_guard.module.json",
    },
]

ALL_MODULES = P0_MODULES

FORBIDDEN_IMPORT_ROOTS = {
    "ctcp",
    "openai",
    "requests",
    "httpx",
    "socket",
    "subprocess",
    "sqlite3",
    "zipfile",
    "runpy",
}
FORBIDDEN_WRITE_PATTERNS = (".write_text(", ".write_bytes(", "open(", ".open(")


@dataclass(frozen=True)
class ModuleCheckContext:
    root: pathlib.Path
    fixture_root: pathlib.Path
    snapshot: dict[str, Any]
    graph: dict[str, Any]


def check_p0_modules(root: pathlib.Path | None = None, module_specs: list[dict[str, Any]] | None = None, kind: str = "P0ModuleRegistryReport") -> dict[str, Any]:
    root = pathlib.Path(root or pathlib.Path(__file__).resolve().parents[2])
    diagnostics: list[dict[str, Any]] = []
    checked_modules: list[dict[str, Any]] = []
    registry = ContractRegistry(root, validate_schema=True)
    specs = module_specs or P0_MODULES
    with tempfile.TemporaryDirectory() as td:
        context = _build_context(pathlib.Path(td))
        for spec in specs:
            module_report, module_diagnostics = _check_module(root, registry, spec, context)
            checked_modules.append(module_report)
            diagnostics.extend(module_diagnostics)
    ok = not any(row["severity"] == "error" for row in diagnostics)
    return {
        "kind": kind,
        "schema_version": "1",
        "ok": ok,
        "modules": checked_modules,
        "diagnostics": diagnostics,
    }


def check_all_modules(root: pathlib.Path | None = None) -> dict[str, Any]:
    return check_p0_modules(root, module_specs=ALL_MODULES, kind="AllModuleRegistryReport")


def _check_module(root: pathlib.Path, registry: ContractRegistry, spec: dict[str, Any], context: ModuleCheckContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diagnostics: list[Diagnostic] = []
    module_ref = spec["module_ref"]
    package_name = spec["package"]
    api_name = spec["api"]
    module_obj = None
    output: Any = None
    deterministic = False
    output_shape_ok = False
    json_serializable = False
    try:
        module_obj = importlib.import_module(package_name)
    except Exception as exc:
        diagnostics.append(Diagnostic(CGNK_MODULE_PACKAGE_MISSING, "error", "$.modules", "P0 module package could not be imported", expected=package_name, actual=str(exc), involved_ref=module_ref))

    if module_obj is not None:
        if not hasattr(module_obj, api_name):
            diagnostics.append(Diagnostic(CGNK_MODULE_API_MISSING, "error", "$.modules.api", "P0 module public API is missing", expected=api_name, actual=sorted(dir(module_obj)), involved_ref=module_ref))
        if not hasattr(module_obj, "check_contract_conformance"):
            diagnostics.append(Diagnostic(CGNK_MODULE_API_MISSING, "error", "$.modules.check_contract_conformance", "P0 module check_contract_conformance is missing", expected="check_contract_conformance", actual=sorted(dir(module_obj)), involved_ref=module_ref))
        contract = registry.resolve_module(module_ref)
        if contract is None:
            diagnostics.append(Diagnostic(CGNK_MODULE_CONTRACT_CONFORMANCE_FAILED, "error", "$.modules.contract", "ModuleContract is missing", expected=module_ref, actual=None, involved_ref=module_ref))
        elif hasattr(module_obj, "check_contract_conformance"):
            conformance = module_obj.check_contract_conformance(contract)
            conformance_diags = _normalize_conformance(conformance)
            if conformance_diags:
                diagnostics.append(Diagnostic(CGNK_MODULE_CONTRACT_CONFORMANCE_FAILED, "error", "$.modules.contract", "ModuleContract conformance failed", expected="no diagnostics", actual=conformance_diags, involved_ref=module_ref))
        _check_effects(contract, module_ref, diagnostics)
        if hasattr(module_obj, api_name):
            output, repeated = _call_sample(module_obj, api_name, context)
            output_shape_ok = _validate_output_shape(output, spec, diagnostics)
            deterministic = output == repeated
            if not deterministic:
                diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output", "Module output is not deterministic for repeated identical input", expected="equal outputs", actual={"first": output, "second": repeated}, involved_ref=module_ref))
            try:
                json.dumps(output, sort_keys=True)
                json_serializable = True
            except TypeError as exc:
                diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output", "Module output is not JSON serializable", expected="JSON-serializable dict", actual=str(exc), involved_ref=module_ref))
    _check_source_boundaries(root, spec, diagnostics)
    report = {
        "module_ref": module_ref,
        "package": package_name,
        "api": api_name,
        "imports": module_obj is not None,
        "contract_conformant": not any(d.code == CGNK_MODULE_CONTRACT_CONFORMANCE_FAILED for d in diagnostics),
        "plain_dict_output": output_shape_ok,
        "deterministic_output": deterministic,
        "json_serializable_output": json_serializable,
    }
    return report, [d.as_dict() for d in diagnostics]


def _build_context(temp_root: pathlib.Path) -> ModuleCheckContext:
    fixture_root = temp_root / "project"
    (fixture_root / "src").mkdir(parents=True)
    (fixture_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (fixture_root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    from cgnk_modules.project_snapshot import collect_project_snapshot
    from cgnk_modules.project_build_graph import build_project_graph

    snapshot_result = collect_project_snapshot(fixture_root)
    graph_result = build_project_graph(snapshot_result["snapshot"])
    return ModuleCheckContext(temp_root, fixture_root, snapshot_result["snapshot"], graph_result["graph"])


def _call_sample(module_obj: Any, api_name: str, context: ModuleCheckContext) -> tuple[Any, Any]:
    calls: dict[str, Callable[[], Any]] = {
        "collect_project_snapshot": lambda: module_obj.collect_project_snapshot(context.fixture_root),
        "build_project_graph": lambda: module_obj.build_project_graph(context.snapshot),
        "extract_requirements_contract_only": lambda: module_obj.extract_requirements_contract_only("update README without provider calls", context={"snapshot": context.snapshot, "constraints": ["no provider calls"]}),
        "generate_contract_plan": lambda: module_obj.generate_contract_plan("update README", snapshot=context.snapshot, graph=context.graph, constraints={"proposed_changes": [{"action": "modify", "path": "README.md", "reason": "smoke"}]}),
        "emit_patch_manifest": lambda: module_obj.emit_patch_manifest({"proposed_changes": [{"action": "modify", "path": "README.md", "reason": "smoke"}]}, snapshot=context.snapshot, graph=context.graph),
        "validate_patch_manifest": lambda: module_obj.validate_patch_manifest({"file_changes": [{"action": "modify", "path": "README.md"}]}, snapshot=context.snapshot, graph=context.graph),
        "build_repair_plan": lambda: module_obj.build_repair_plan([], compiled_flow={"flow_ref": "flow.project_refactor@1"}),
        "build_migration_proof": lambda: module_obj.build_migration_proof(_sample_migration_spec(context)),
        "summarize_diagnostics": lambda: module_obj.summarize_diagnostics([{"code": "CGNK_SAMPLE", "severity": "warning", "path": "$.sample", "message": "sample"}]),
        "summarize_benchmark_report": lambda: module_obj.summarize_benchmark_report({"kind": "BenchmarkReport", "ok": True, "metrics": {"duration_seconds": 1.0}, "warnings": []}),
        "evaluate_convergence": lambda: module_obj.evaluate_convergence([{"ok": False, "hash": "a"}, {"ok": True, "hash": "b"}]),
        "evaluate_timeout_budget": lambda: module_obj.evaluate_timeout_budget({"total_seconds": 1.0}, {"max_total_seconds": 5.0}),
        "evaluate_provider_call_request": lambda: module_obj.evaluate_provider_call_request({"provider": "example", "max_tokens": 10}, policy={"allow_provider_call": False}, budget={"max_tokens": 100, "max_calls": 1}),
    }
    call = calls[api_name]
    return call(), call()


def _sample_migration_spec(context: ModuleCheckContext) -> dict[str, Any]:
    return {
        "kind": "MigrationSpec",
        "id": "migration.project_generation",
        "version": "1",
        "legacy": {"files": [], "public_entrypoints": []},
        "target": {"flow": "flow.project_refactor@1", "modules": ["module.project.snapshot@1"], "artifacts": ["artifact.project_snapshot@1"]},
        "preserve": {"cli_args": True, "summary_json_schema": True, "benchmark_report_format": True, "provider_call_semantics": True},
        "proof": {"required_tests": ["unit"], "required_artifacts": ["artifact.project_snapshot@1"], "required_schemas": ["summary_json_schema"]},
    }


def _normalize_conformance(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return list(value.get("diagnostics", []))
    if isinstance(value, list):
        return [row.as_dict() if hasattr(row, "as_dict") else row for row in value]
    return [{"code": CGNK_MODULE_CONTRACT_CONFORMANCE_FAILED, "severity": "error", "path": "$.contract", "message": "Unexpected conformance result", "actual": type(value).__name__}]


def _validate_output_shape(output: Any, spec: dict[str, Any], diagnostics: list[Diagnostic]) -> bool:
    module_ref = spec["module_ref"]
    if type(output) is not dict:
        diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output", "P0 module output must be a plain dictionary", expected="dict", actual=type(output).__name__, involved_ref=module_ref))
        return False
    if "diagnostics" not in output or not isinstance(output.get("diagnostics"), list):
        diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output.diagnostics", "P0 module output diagnostics must always be a list", expected="list", actual=type(output.get("diagnostics")).__name__, involved_ref=module_ref))
        return False
    if "ok" not in output and "kind" not in output:
        diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output", "P0 module output must expose deterministic ok or kind status", expected="ok or kind", actual=sorted(output.keys()), involved_ref=module_ref))
        return False
    output_key = spec.get("output_key")
    artifact = output.get(output_key) if output_key else output
    if isinstance(artifact, dict) and "kind" not in artifact:
        diagnostics.append(Diagnostic(CGNK_MODULE_OUTPUT_SHAPE_INVALID, "error", "$.modules.output.kind", "P0 artifact output should include kind", expected="kind", actual=sorted(artifact.keys()), involved_ref=module_ref))
        return False
    return True


def _check_effects(contract: dict[str, Any] | None, module_ref: str, diagnostics: list[Diagnostic]) -> None:
    effects = (contract or {}).get("effects", {})
    if effects.get("provider_call") is not False or effects.get("network") is not False or effects.get("fs_write") != []:
        diagnostics.append(Diagnostic(CGNK_MODULE_FORBIDDEN_EFFECT, "error", "$.effects", "P0 module contract must be provider-free, network-free, and workspace-write-free", expected={"provider_call": False, "network": False, "fs_write": []}, actual=effects, involved_ref=module_ref))


def _check_source_boundaries(root: pathlib.Path, spec: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    module_ref = spec["module_ref"]
    package_path = root / "src" / pathlib.Path(spec["package"].replace(".", "/"))
    if "cgnk_core" in package_path.parts:
        diagnostics.append(Diagnostic(CGNK_MODULE_FORBIDDEN_IMPORT, "error", "$.package", "P0 module implementation must not live under cgnk_core", expected="src/cgnk_modules", actual=package_path.as_posix(), involved_ref=module_ref))
    if not package_path.is_dir():
        return
    for path in sorted(package_path.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for imported in _imports(path, text):
            if imported.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                diagnostics.append(Diagnostic(CGNK_MODULE_FORBIDDEN_IMPORT, "error", rel, "P0 module imports forbidden runtime, provider, database, archive, or legacy dependency", expected="contract-only imports", actual=imported, involved_ref=module_ref, source={"path": rel}))
        if _has_write_pattern(text):
            diagnostics.append(Diagnostic(CGNK_MODULE_FORBIDDEN_EFFECT, "error", rel, "P0 module source contains workspace write pattern", expected="no write APIs", actual="write pattern", involved_ref=module_ref, source={"path": rel}))


def _imports(path: pathlib.Path, text: str) -> list[str]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _has_write_pattern(text: str) -> bool:
    for pattern in FORBIDDEN_WRITE_PATTERNS:
        if pattern in text:
            if pattern in {".open(", "open("} and ("\"rb\"" in text or "'rb'" in text or "\"r\"" in text or "'r'" in text):
                continue
            return True
    return False
