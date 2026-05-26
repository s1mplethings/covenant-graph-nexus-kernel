from __future__ import annotations

import importlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_modules.readiness import build_module_chain_readiness
from cgnk_modules.registry import P0_MODULES, check_p0_modules
from tests.helpers import ROOT, codes


class P0ModuleReadinessTest(unittest.TestCase):
    def test_registry_checks_all_p0_modules(self) -> None:
        report = check_p0_modules(ROOT)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual({row["module_ref"] for row in P0_MODULES}, {row["module_ref"] for row in report["modules"]})
        for module in report["modules"]:
            self.assertTrue(module["imports"], module)
            self.assertTrue(module["contract_conformant"], module)
            self.assertTrue(module["plain_dict_output"], module)
            self.assertTrue(module["deterministic_output"], module)
            self.assertTrue(module["json_serializable_output"], module)

    def test_chain_readiness_report_schema(self) -> None:
        report = build_module_chain_readiness("p0", ROOT)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual("ready_for_refactor", report["readiness_status"])
        self.assertEqual([], report["missing_modules"])
        self.assertEqual([], report["contract_failures"])
        self.assertEqual([], report["deterministic_failures"])
        self.assertEqual([], report["forbidden_dependency_failures"])
        self.assertEqual([], SchemaLoader(ROOT).validate(report, "module_chain_readiness.schema.json"))

    def test_p0_public_outputs_are_plain_deterministic_json_dicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            context = _context(pathlib.Path(td))
            for spec in P0_MODULES:
                with self.subTest(module_ref=spec["module_ref"]):
                    module = importlib.import_module(spec["package"])
                    first = _call(spec["api"], module, context)
                    second = _call(spec["api"], module, context)
                    self.assertIs(type(first), dict)
                    self.assertEqual(first, second)
                    self.assertIsInstance(first.get("diagnostics"), list)
                    self.assertTrue("ok" in first or "kind" in first)
                    artifact = first.get(spec.get("output_key")) if spec.get("output_key") else first
                    if isinstance(artifact, dict):
                        self.assertIn("kind", artifact)
                        self.assertTrue("schema_version" in artifact or "version" in artifact)
                    json.dumps(first, sort_keys=True)

    def test_contracts_do_not_declare_forbidden_p0_effects(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=True)
        for spec in P0_MODULES:
            contract = registry.resolve_module(spec["module_ref"])
            self.assertIsNotNone(contract)
            effects = contract["effects"]
            self.assertIs(effects["network"], False)
            self.assertIs(effects["provider_call"], False)
            self.assertEqual([], effects["fs_write"])

    def test_checker_cli_and_readiness_cli(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = pathlib.Path(td) / "p0_chain_readiness.json"
            check_run = subprocess.run([sys.executable, "scripts/cgnk_check_modules.py", "--p0"], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, check_run.returncode, check_run.stdout + check_run.stderr)
            readiness_run = subprocess.run([sys.executable, "scripts/cgnk_module_chain_readiness.py", "--chain", "p0", "--output", str(output)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, readiness_run.returncode, readiness_run.stdout + readiness_run.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(report["ok"], report["diagnostics"])

    def test_unsupported_chain_is_blocked_with_stable_diagnostic(self) -> None:
        report = build_module_chain_readiness("p1", ROOT)
        self.assertFalse(report["ok"])
        self.assertEqual("blocked", report["readiness_status"])
        self.assertIn("CGNK_MODULE_CHAIN_NOT_READY", codes(report["diagnostics"]))


def _context(root: pathlib.Path) -> dict:
    project = root / "project"
    (project / "src").mkdir(parents=True)
    (project / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (project / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    from cgnk_modules.project_snapshot import collect_project_snapshot
    from cgnk_modules.project_build_graph import build_project_graph

    snapshot = collect_project_snapshot(project)["snapshot"]
    graph = build_project_graph(snapshot)["graph"]
    return {"project": project, "snapshot": snapshot, "graph": graph}


def _call(api_name: str, module, context: dict):
    if api_name == "collect_project_snapshot":
        return module.collect_project_snapshot(context["project"])
    if api_name == "build_project_graph":
        return module.build_project_graph(context["snapshot"])
    if api_name == "extract_requirements_contract_only":
        return module.extract_requirements_contract_only("update README without provider calls", context={"snapshot": context["snapshot"], "constraints": ["no provider calls"]})
    if api_name == "generate_contract_plan":
        return module.generate_contract_plan("update README", snapshot=context["snapshot"], graph=context["graph"], constraints={"proposed_changes": [{"action": "modify", "path": "README.md", "reason": "smoke"}]})
    if api_name == "emit_patch_manifest":
        return module.emit_patch_manifest({"proposed_changes": [{"action": "modify", "path": "README.md", "reason": "smoke"}]}, snapshot=context["snapshot"], graph=context["graph"])
    if api_name == "validate_patch_manifest":
        return module.validate_patch_manifest({"file_changes": [{"action": "modify", "path": "README.md"}]}, snapshot=context["snapshot"], graph=context["graph"])
    if api_name == "build_repair_plan":
        return module.build_repair_plan([], compiled_flow={"flow_ref": "flow.project_refactor@1"})
    if api_name == "build_migration_proof":
        return module.build_migration_proof(
            {
                "kind": "MigrationSpec",
                "id": "migration.project_generation",
                "version": "1",
                "legacy": {"files": [], "public_entrypoints": []},
                "target": {"flow": "flow.project_refactor@1", "modules": ["module.project.snapshot@1"], "artifacts": ["artifact.project_snapshot@1"]},
                "preserve": {"cli_args": True, "summary_json_schema": True, "benchmark_report_format": True, "provider_call_semantics": True},
                "proof": {"required_tests": ["unit"], "required_artifacts": ["artifact.project_snapshot@1"], "required_schemas": ["summary_json_schema"]},
            }
        )
    if api_name == "summarize_diagnostics":
        return module.summarize_diagnostics([{"code": "CGNK_SAMPLE", "severity": "warning", "path": "$.sample", "message": "sample"}])
    if api_name == "summarize_benchmark_report":
        return module.summarize_benchmark_report({"kind": "BenchmarkReport", "ok": True, "metrics": {"duration_seconds": 1.0}, "warnings": []})
    if api_name == "evaluate_convergence":
        return module.evaluate_convergence([{"ok": False, "hash": "a"}, {"ok": True, "hash": "b"}])
    if api_name == "evaluate_timeout_budget":
        return module.evaluate_timeout_budget({"total_seconds": 1.0}, {"max_total_seconds": 5.0})
    if api_name == "evaluate_provider_call_request":
        return module.evaluate_provider_call_request({"provider": "example", "max_tokens": 10}, policy={"allow_provider_call": False}, budget={"max_tokens": 100, "max_calls": 1})
    raise AssertionError(f"Unhandled API: {api_name}")


if __name__ == "__main__":
    unittest.main()
