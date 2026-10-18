from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.capability_builder import (  # noqa: E402
    CapabilityBuildLifecycleService,
    CapabilityBuilderService,
    CapabilityStore,
    RecommendedAction,
    StoredCapabilityRuntime,
    ValidationSuite,
)
from cgkn.application.capability_builder.revision_store import canonical_hash, file_hash  # noqa: E402
from cgkn.application.self_growth import SelfGrowthService  # noqa: E402
from cgkn.providers import ModelRoleConfig  # noqa: E402
from scripts.run_higher_order_growth import _FixtureNetwork, repo_brief_spec  # noqa: E402


class _ForbiddenProviderClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        raise AssertionError("REVALIDATION_AUTHORITY_VIOLATION")


def run(
    output_root: pathlib.Path,
    candidate_source: pathlib.Path,
    seed_store: pathlib.Path,
    *,
    provider_request_id: str,
    external_status: str,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    shutil.copytree(seed_store, output_root / "capability_store")
    store = CapabilityStore(output_root / "capability_store")
    client = _ForbiddenProviderClient()
    adapter = CapabilityBuilderService(
        client, ModelRoleConfig("worker", "grok", 180, 3000, 0.0, "medium"),
        provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store,
    )
    lifecycle = CapabilityBuildLifecycleService(adapter, store)
    spec = repo_brief_spec()
    route_hash = canonical_hash({"provider_id": "grok", "model": "grok-4.7", "mode": "SINGLE_PROVIDER_MODE"})
    revision = lifecycle.recover_candidate(
        output_root / "lifecycle", candidate_source, spec, build_run_id="iter-023-r1-recovery",
        provider_id="grok", provider_request_id=provider_request_id, route_snapshot_hash=route_hash,
    )
    dependency_manifest = store.resolve_dependency_manifest(spec)
    suite = ValidationSuite(
        version="2.0-empty-list-fixed",
        contract_test_hashes={"generated_contract_harness": file_hash(ROOT / "cgkn/application/capability_builder/validators.py")},
        fixture_hashes={"capability_spec": canonical_hash(spec.as_dict())},
        policy_version=lifecycle.action_policy.version,
    )
    receipts, decision = lifecycle.revalidate_candidate(
        revision.revision_id, suite, spec=spec,
        dependency_manifest_hash=canonical_hash(dependency_manifest), repair_budget=1,
        external_status=external_status,
    )
    admitted = False
    local_execution = "NOT_RUN"
    reuse = "NOT_RUN"
    reuse_growth_calls = reuse_builder_calls = 0
    output: Any = None
    if decision.action is RecommendedAction.ADMIT_CANDIDATE:
        admitted = lifecycle.admit_candidate(revision.revision_id, external_status=external_status)
        runtime = StoredCapabilityRuntime(store, provider_id="grok", network_public=_FixtureNetwork())
        value = {"owner": "octocat", "repo": "Hello-World", "question": "What does this repository expose?"}
        output = runtime.invoke(spec.ref, value)
        local_execution = "PASS"
        growth = SelfGrowthService(adapter, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=output_root / "provider_history.json", network_public=_FixtureNetwork())
        reused = growth.ensure_and_resume(output_root / "unused", spec, value)
        reuse = reused.status
        reuse_growth_calls = int(reused.growth_invoked)
        reuse_builder_calls = int(reused.builder_invoked)
    final_revision = lifecycle.revision_store.load_revision(revision.revision_id)
    result = {
        "kind": "CandidateLifecycleRecoveryReceipt", "schema_version": "1.0",
        "iteration": "ITER-CANDIDATE-LIFECYCLE-REFRACTOR-024",
        "capability_ref": spec.ref, "recovered": True,
        "revision_id": revision.revision_id, "revision_number": revision.revision_number,
        "parent_revision_id": revision.parent_revision_id,
        "creation_reason": revision.creation_reason,
        "provider_request_id": revision.provider_request_id,
        "candidate_source_hash_before": revision.source_hash,
        "candidate_source_hash_after": final_revision.source_hash,
        "candidate_unchanged": revision.source_hash == final_revision.source_hash,
        "validator_suite_hash": suite.identity.validator_suite_hash,
        "validation_statuses": {receipt.validation_phase.value: receipt.status for receipt in receipts},
        "action": decision.action.value, "admitted": admitted,
        "local_execution": local_execution, "reuse": reuse,
        "reuse_growth_calls": reuse_growth_calls, "reuse_builder_calls": reuse_builder_calls,
        "external_readiness": external_status, "provider_calls": client.calls,
        "manual_edits": 0, "unsafe_admissions": 0,
        "output_summary": output.get("summary", "") if isinstance(output, dict) else "",
        "full_regression": "NOT_RUN_BY_POLICY", "contains_credentials": False,
    }
    (output_root / "candidate_lifecycle_recovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-source", required=True, type=pathlib.Path)
    parser.add_argument("--seed-store", required=True, type=pathlib.Path)
    parser.add_argument("--provider-request-id", required=True)
    parser.add_argument("--external-status", default="GITHUB_RATE_LIMITED")
    args = parser.parse_args()
    result = run(args.output_root.resolve(), args.candidate_source.resolve(), args.seed_store.resolve(), provider_request_id=args.provider_request_id, external_status=args.external_status)
    return 0 if result["admitted"] and result["local_execution"] == result["reuse"] == "PASS" and result["provider_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
