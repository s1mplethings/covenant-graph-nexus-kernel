from __future__ import annotations

import json
from pathlib import Path

import pytest

from cgkn.application.capability_builder import CandidateRevision, CandidateRevisionStatus, CandidateRevisionStore
from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.software_project.greenfield import (
    AssemblyReceipt, BundleInterfaceContract, BundleKind, BundleSpec, CampaignBudgetAllocator,
    GenerationManifest, GenerationManifestCompiler, GreenfieldBundleProductionService, HELP_CONTRACT,
    ProjectAssembler,
)
from cgkn.providers import ModelRoleConfig, ProviderCompletion, ProviderConnectionError


PROJECT = {
    "project_id": "sample_cli", "public_goal": "Echo deterministic values.",
    "interface_contract": {"entrypoint": "python -m sample", "commands": ["VALUE", "VALUE --json"]},
    "behavior_contract": {"echo": "return the exact value"},
}
OBLIGATIONS = {"interface": "exact", "errors": "nonzero stderr", "deterministic": True}
TARGETS = ("sample/__init__.py", "sample/__main__.py", "sample/core.py")


def manifest(project_type: str = "GREENFIELD_CLI", *, contract=None, targets=TARGETS) -> GenerationManifest:
    return GenerationManifestCompiler().compile(
        project_id="sample_cli", project_type=project_type, package_name="sample",
        project_contract=contract or PROJECT, obligations=OBLIGATIONS,
        interface_contract=PROJECT["interface_contract"], target_paths=targets,
    )


def test_manifest_is_deterministic():
    assert manifest().manifest_hash == manifest().manifest_hash


def test_manifest_round_trip():
    value = manifest()
    assert GenerationManifest.from_dict(value.as_dict()).as_dict() == value.as_dict()


def test_bundle_round_trip():
    value = manifest().bundle_specs[0]
    assert BundleSpec.from_dict(value.as_dict()).as_dict() == value.as_dict()


def test_interface_round_trip():
    value = manifest().bundle_specs[1].interface_contract
    assert BundleInterfaceContract.from_dict(value.as_dict()).as_dict() == value.as_dict()


def test_normal_cli_has_domain_and_cli_bundles():
    assert [item.bundle_kind for item in manifest().bundle_specs] == [BundleKind.DOMAIN, BundleKind.CLI]


def test_normal_cli_never_splits_per_file():
    assert manifest().bundle_specs[0].target_paths == ("sample/__init__.py", "sample/core.py")
    assert manifest().bundle_specs[1].target_paths == ("sample/__main__.py",)


def test_persistent_project_uses_domain_store():
    assert manifest("PERSISTENT_CRUD").bundle_specs[0].bundle_kind == BundleKind.DOMAIN_STORE


def test_library_project_uses_library_api():
    contract = {**PROJECT, "behavior_contract": {"public_api": "sample.summarize(lines)"}}
    value = manifest("LIBRARY", contract=contract)
    assert value.bundle_specs[0].bundle_kind == BundleKind.LIBRARY_API
    assert "summarize" in value.bundle_specs[0].interface_contract.exports


def test_domain_and_cli_have_bounded_provider_configs():
    domain, cli = manifest().bundle_specs
    assert (domain.max_output_tokens, domain.max_output_bytes, domain.reasoning_effort) == (2800, 65536, "low")
    assert (cli.max_output_tokens, cli.max_output_bytes, cli.reasoning_effort) == (1500, 32768, "low")


def test_cli_help_contract_is_explicit():
    help_contract = manifest().bundle_specs[1].interface_contract.help_contract
    assert help_contract == HELP_CONTRACT
    assert help_contract["exit_code"] == 0 and help_contract["business_file_side_effects"] == "FORBIDDEN"
    assert "exact exit code 2" in manifest().bundle_specs[1].interface_contract.stderr_contract


def test_bundle_graph_is_acyclic_and_cli_depends_on_domain():
    value = manifest(); domain, cli = value.bundle_specs
    assert value.bundle_graph[domain.bundle_id] == ()
    assert value.bundle_graph[cli.bundle_id] == (domain.bundle_id,)


def test_overlapping_bundle_targets_are_rejected():
    value = manifest(); domain, cli = value.bundle_specs
    duplicate = BundleSpec.from_dict({**cli.as_dict(), "target_paths": [domain.target_paths[0]], "bundle_hash": ""})
    with pytest.raises(ValueError, match="OVERLAPPING"):
        GenerationManifest(value.project_id, value.project_type, value.package_name, value.project_contract_hash, value.obligation_hash, value.interface_contract_hash, (domain, duplicate), {domain.bundle_id: (), duplicate.bundle_id: (domain.bundle_id,)}, (), {}, {})


def test_bundle_graph_cycle_is_rejected():
    value = manifest(); domain, cli = value.bundle_specs
    with pytest.raises(ValueError, match="CYCLE"):
        GenerationManifest(value.project_id, value.project_type, value.package_name, value.project_contract_hash, value.obligation_hash, value.interface_contract_hash, (domain, cli), {domain.bundle_id: (cli.bundle_id,), cli.bundle_id: (domain.bundle_id,)}, (), {}, {})


def test_bundle_hash_tampering_is_rejected():
    value = manifest().bundle_specs[0].as_dict(); value["bundle_hash"] = "sha256:bad"
    with pytest.raises(ValueError, match="hash mismatch"):
        BundleSpec.from_dict(value)


def test_bundle_size_file_limit_is_enforced():
    with pytest.raises(ValueError, match="FILE_LIMIT"):
        manifest(targets=("sample/__init__.py", "sample/__main__.py", "sample/core.py", "sample/a.py", "sample/b.py"))


def test_contract_size_guard_is_enforced():
    oversized = {**PROJECT, "public_goal": "x" * 25000}
    with pytest.raises(ValueError, match="CONTRACT_LIMIT"):
        manifest(contract=oversized)


def test_candidate_revision_old_documents_default_to_capability():
    value = CandidateRevision("r", "cap@1", "run", 1, None, "s", "route", "grok", "", "", "GENERATION", (), "h", "p", "now", "test", CandidateRevisionStatus.CREATED)
    document = value.as_dict(); document.pop("subject_kind"); document.pop("subject_ref")
    loaded = CandidateRevision.from_dict(document)
    assert loaded.subject_kind == "CAPABILITY" and loaded.subject_ref == "cap@1"


def test_candidate_store_persists_project_bundle_subject(tmp_path):
    source = tmp_path / "source"; (source / "sample").mkdir(parents=True); (source / "sample/core.py").write_text("def execute(operation, parameters): return parameters\n")
    store = CandidateRevisionStore(tmp_path / "store")
    revision = store.create_revision(source, capability_ref="project.x.bundle.domain@1", build_run_id="run", spec_hash="s", route_snapshot_hash="r", provider_id="grok", subject_kind="PROJECT_BUNDLE", subject_ref="project.x.bundle.domain@1")
    assert store.load_revision(revision.revision_id).subject_kind == "PROJECT_BUNDLE"


def test_budget_allocator_preserves_partition_limits():
    budget = CampaignBudgetAllocator(); budget.consume("TARGETED_REAL_4", "p", calls=12)
    with pytest.raises(RuntimeError, match="TARGETED_REAL_4"):
        budget.consume("TARGETED_REAL_4", "p")
    assert budget.snapshot()["partitions"]["HOLDOUT"]["remaining"] == 6


def test_budget_allocator_protects_holdout_from_calibration():
    budget = CampaignBudgetAllocator(); budget.consume("CALIBRATION_GENERALIZATION", "d", calls=16)
    assert budget.snapshot()["partitions"]["HOLDOUT"] == {"limit": 6, "used": 0, "remaining": 6}


def test_bundle_dag_has_canonical_nodes():
    tree = GreenfieldBundleProductionService.build_tree(manifest())
    ids = {node.id for node in tree.nodes}
    assert {"generation-manifest", "bundle-domain-generate", "bundle-domain-persist", "bundle-domain-validate", "bundle-cli-generate", "bundle-cli-persist", "bundle-cli-validate", "project-assemble"} <= ids


def test_bundle_dag_cli_generation_depends_on_domain_validation():
    tree = GreenfieldBundleProductionService.build_tree(manifest())
    cli = next(node for node in tree.nodes if node.id == "bundle-cli-generate")
    assert "bundle-domain-validate" in cli.depends_on


class FakeBundleProvider:
    def __init__(self, *, cli_transport_once=False, bad_cli_once=False):
        self.calls: list[str] = []; self.cli_transport_once = cli_transport_once; self.bad_cli_once = bad_cli_once

    def complete(self, **kwargs):
        prompt = json.loads(kwargs["user"]); bundle = prompt["bundle"]; bundle_id = bundle["bundle_id"]
        kind = bundle["bundle_kind"]; self.calls.append(kind)
        if kind == "CLI" and self.cli_transport_once:
            self.cli_transport_once = False
            raise ProviderConnectionError("PROVIDER_TRANSPORT_FAILURE", "closed", outcome_unknown=False)
        if kind == "CLI":
            if self.bad_cli_once:
                self.bad_cli_once = False
                main = "def main(argv=None): return 0\n"
            else:
                main = "import argparse\nfrom .core import execute\ndef build_parser():\n p=argparse.ArgumentParser(); p.add_argument('value',nargs='?'); return p\ndef main(argv=None):\n a=build_parser().parse_args(argv); print(execute('echo',{'value':a.value})); return 0\nif __name__=='__main__': raise SystemExit(main())\n"
            actions = [{"action": "write_file", "path": "sample/__main__.py", "content": main}]
        else:
            actions = [
                {"action": "write_file", "path": "sample/__init__.py", "content": "from .core import ProjectError, execute\n"},
                {"action": "write_file", "path": "sample/core.py", "content": "class ProjectError(ValueError): pass\ndef execute(operation, parameters):\n if operation!='echo': raise ProjectError(operation)\n return parameters.get('value','')\n"},
            ]
        body = {"schema_version": "1.0", "node_id": bundle_id, "summary": "fake", "actions": actions, "expected_outputs": ["PASS"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(body), "grok", f"request-{len(self.calls)}", {"input_tokens": 10, "output_tokens": 20}, 1)


def service(tmp_path: Path, provider: FakeBundleProvider) -> GreenfieldBundleProductionService:
    store = FileLessonStore(tmp_path / "lessons")
    generation = ProductionGenerationClient(provider, StoreLessonReader(store), store=store, max_provider_calls=20)
    return GreenfieldBundleProductionService(generation, ModelRoleConfig("worker", "grok", 180, 7000, 0.0, "medium"), tmp_path / "artifacts")


def test_fake_bundle_e2e_domain_cli_assemble_and_help(tmp_path):
    provider = FakeBundleProvider(); svc = service(tmp_path, provider); workspace = tmp_path / "workspace"
    result = svc.run_initial(manifest(), PROJECT, workspace)
    assert result["status"] == "SUCCEEDED" and provider.calls == ["DOMAIN", "CLI"]
    before = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if "__pycache__" not in path.parts)
    import os, subprocess, sys
    env = os.environ.copy(); env["PYTHONPATH"] = str(workspace)
    completed = subprocess.run([sys.executable, "-m", "sample", "--help"], cwd=workspace, capture_output=True, text=True, env=env)
    after = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if "__pycache__" not in path.parts)
    assert completed.returncode == 0 and "usage" in completed.stdout.lower() and "traceback" not in completed.stderr.lower()
    assert before == after


def test_cli_transport_retry_does_not_rerun_domain(tmp_path):
    provider = FakeBundleProvider(cli_transport_once=True); svc = service(tmp_path, provider)
    result = svc.run_initial(manifest(), PROJECT, tmp_path / "workspace")
    assert result["status"] == "SUCCEEDED"
    assert provider.calls == ["DOMAIN", "CLI", "CLI"]
    assert sum(call == "DOMAIN" for call in provider.calls) == 1
    assert sum(bool(item["revision_id"]) for item in result["attempts"]) == 2


def test_transport_failure_creates_no_revision_for_failed_attempt(tmp_path):
    provider = FakeBundleProvider(cli_transport_once=True); svc = service(tmp_path, provider)
    result = svc.run_initial(manifest(), PROJECT, tmp_path / "workspace")
    blocked = next(item for item in result["attempts"] if item["status"] == "PROVIDER_BLOCKED")
    assert blocked["revision_id"] == ""


def test_candidate_defect_creates_child_revision_on_repair(tmp_path):
    provider = FakeBundleProvider(bad_cli_once=True); svc = service(tmp_path, provider); value = manifest()
    first = svc.run_initial(value, PROJECT, tmp_path / "workspace", retry_transport=False, repair_candidate=False)
    assert first["status"] != "SUCCEEDED" and provider.calls == ["DOMAIN", "CLI"]
    cli = value.bundle_specs[1]; parent = svc.current_revisions[cli.bundle_id]
    repaired = svc.repair_bundle(value, cli, PROJECT, first["run_id"], {"failure_class": "CLI_HELP"})
    assert repaired.parent_revision_id == parent
    assert svc.revisions.load_revision(repaired.revision_id).revision_number == 2
    assert provider.calls == ["DOMAIN", "CLI", "CLI"]


def test_revalidation_uses_existing_revision_without_provider_call(tmp_path):
    provider = FakeBundleProvider(); svc = service(tmp_path, provider); value = manifest()
    result = svc.run_initial(value, PROJECT, tmp_path / "workspace"); calls = len(provider.calls)
    for spec in value.bundle_specs:
        assert svc.validate_bundle(spec, result["revision_ids"][spec.bundle_id])["status"] == "PASS"
    assert len(provider.calls) == calls


def test_assembly_receipt_round_trip_and_stable_hash(tmp_path):
    provider = FakeBundleProvider(); svc = service(tmp_path, provider); value = manifest()
    result = svc.run_initial(value, PROJECT, tmp_path / "workspace")
    receipt = AssemblyReceipt.from_dict(result["assembly"])
    assert receipt.assembly_hash.startswith("sha256:")
    second = ProjectAssembler(svc.revisions).assemble(value, result["revision_ids"], tmp_path / "workspace-2")
    assert second.assembly_hash == receipt.assembly_hash


def test_assembly_rejects_missing_bundle_without_polluting_workspace(tmp_path):
    provider = FakeBundleProvider(); svc = service(tmp_path, provider); value = manifest()
    result = svc.run_initial(value, PROJECT, tmp_path / "workspace")
    target = tmp_path / "safe"; target.mkdir(); (target / "sentinel.txt").write_text("keep")
    only_domain = {value.bundle_specs[0].bundle_id: result["revision_ids"][value.bundle_specs[0].bundle_id]}
    with pytest.raises(ValueError, match="one validated revision"):
        ProjectAssembler(svc.revisions).assemble(value, only_domain, target)
    assert (target / "sentinel.txt").read_text() == "keep"
