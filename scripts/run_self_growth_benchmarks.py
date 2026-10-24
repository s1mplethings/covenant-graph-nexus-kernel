from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import uuid
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.self_growth import GrowthGroup, canonical_hash, policy_hashes  # noqa: E402
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment  # noqa: E402
from experiments.self_growth_v1.cases import ordered_task_stream, stream_hashes  # noqa: E402
from experiments.self_growth_v1.providers import ProviderCandidateBackend, ProviderStrongDecider  # noqa: E402
from experiments.self_growth_v1.runner import GrowthBenchmarkRunner, StaticCandidateBackend, StaticStrongDecider  # noqa: E402


PROFILES = {
    "growth-g0": GrowthGroup.G0,
    "growth-g1": GrowthGroup.G1,
    "growth-g2": GrowthGroup.G2,
    "growth-g3": GrowthGroup.G3,
}
PRICING_PATH = ROOT / "benchmarks" / "self_growth_v1" / "fixtures" / "pricing_snapshot.json"
ROUTING_PATH = ROOT / "config" / "provider_profiles" / "gateway_model_routing.json"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True, encoding="utf-8",
    )
    return result.stdout.strip()


def _source_identity(*, expected_commit: str | None, require_clean: bool) -> tuple[str, str]:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    if expected_commit and commit != expected_commit:
        raise RuntimeError(f"source closure mismatch: expected {expected_commit}, got {commit}")
    if require_clean and _git("status", "--short"):
        raise RuntimeError("formal growth evidence requires a clean frozen source worktree")
    return commit, tree


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _formal_group(profile: str, output_root: pathlib.Path, expected_commit: str) -> dict[str, Any]:
    group = PROFILES[profile]
    commit, tree = _source_identity(expected_commit=expected_commit, require_clean=True)
    pricing = _load_json(PRICING_PATH)
    destination = output_root / f"{profile}-{uuid.uuid4().hex[:10]}"
    if group is GrowthGroup.G0:
        backend = StaticCandidateBackend()
        strong = StaticStrongDecider()
    else:
        base = completion_client_from_environment()
        if not isinstance(base, GatewayCompletionClient):
            raise RuntimeError("reviewed local Provider gateway is required for formal growth groups")
        routing = CGKNModelRouting.load(ROUTING_PATH)
        bound = base.bind_run(destination.name, profile, budget_purpose="BENCHMARK")
        worker = ModelRoleConfig(
            "worker", routing.worker.model, timeout_seconds=routing.worker.timeout_seconds,
            max_output_tokens=min(3000, routing.worker.max_output_tokens), temperature=0.0,
            reasoning_effort="none", task_class="capability.build", operation="GENERATION",
            outer_deadline_seconds=routing.worker.timeout_seconds + 30, deadline_reserve_seconds=30,
            thinking_mode="disabled",
        )
        agent = ModelRoleConfig(
            "agent", routing.agent.model, timeout_seconds=routing.agent.timeout_seconds,
            max_output_tokens=min(900, routing.agent.max_output_tokens), temperature=0.0,
            reasoning_effort="none", task_class="capability.growth.decision", operation="ABSTRACTION_DECISION",
            outer_deadline_seconds=routing.agent.timeout_seconds + 30, deadline_reserve_seconds=30,
            thinking_mode="disabled",
        )
        backend = ProviderCandidateBackend(bound, worker, destination / "capability_store")
        strong = ProviderStrongDecider(bound, agent) if group is GrowthGroup.G3 else StaticStrongDecider()
    receipt = GrowthBenchmarkRunner(
        group, backend, destination, strong_decider=strong, pricing=pricing,
        source_commit=commit, source_tree=tree,
    ).run()
    receipt["freeze"] = {
        **stream_hashes(), **policy_hashes(),
        "base_registry_hash": receipt["production_registry_authority_hash"],
        "model_config_hash": canonical_hash(_load_json(ROUTING_PATH)),
        "pricing_hash": canonical_hash(pricing),
    }
    receipt["receipt_hash"] = canonical_hash({key: value for key, value in receipt.items() if key != "receipt_hash"})
    path = destination / "group_receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt | {"receipt_path": str(path)}


def _discovery(output_root: pathlib.Path, count: int) -> dict[str, Any]:
    commit, tree = _source_identity(expected_commit=None, require_clean=False)
    destination = output_root / f"growth-discovery-{uuid.uuid4().hex[:10]}"
    receipt = GrowthBenchmarkRunner(
        GrowthGroup.G3, StaticCandidateBackend(), destination,
        source_commit=commit, source_tree=tree,
    ).run(ordered_task_stream()[:count])
    path = destination / "discovery_receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt | {"receipt_path": str(path)}


def _final(output_root: pathlib.Path, paths: list[pathlib.Path], expected_commit: str) -> dict[str, Any]:
    commit, tree = _source_identity(expected_commit=expected_commit, require_clean=True)
    receipts = [_load_json(path.resolve()) for path in paths]
    by_group = {str(item["group"]): item for item in receipts}
    missing = [group.value for group in GrowthGroup if group.value not in by_group]
    if missing:
        raise ValueError(f"missing formal group receipts: {missing}")
    if any(item.get("source_commit") != commit or item.get("source_tree") != tree for item in receipts):
        raise ValueError("formal group source identities differ")
    stream_ids = {item["benchmark_hashes"]["task_stream_hash"] for item in receipts}
    if len(stream_ids) != 1:
        raise ValueError("formal groups did not use the same frozen task stream")
    required_freeze_keys = {
        "base_registry_hash", "task_stream_hash", "expected_class_hash",
        "qualification_set_hash", "growth_policy_hash", "composition_policy_hash",
        "admission_policy_hash", "model_config_hash", "pricing_hash", "rubric_hash",
    }
    for key in sorted(required_freeze_keys):
        values = {str(item.get("freeze", {}).get(key, "")) for item in receipts}
        if "" in values or len(values) != 1:
            raise ValueError(f"formal group freeze mismatch: {key}")
    comparison = {
        group: {
            key: receipt["metrics"].get(key)
            for key in (
                "success_rate", "true_gap_precision", "true_gap_recall", "new_capabilities_admitted",
                "capability_internalization_rate", "zero_reuse_capability_rate", "strong_calls",
                "cheap_calls", "known_total_tokens", "known_cost_cny", "total_latency_ms",
            )
        }
        for group, receipt in by_group.items()
    }
    g2 = by_group[GrowthGroup.G2.value]["metrics"]
    g3 = by_group[GrowthGroup.G3.value]["metrics"]
    strong_benefit = (
        "PROVEN_DIRECTIONALLY"
        if g3["success_rate"] > g2["success_rate"] or g3["zero_reuse_capability_rate"] < g2["zero_reuse_capability_rate"]
        else "NEUTRAL" if g3["success_rate"] >= g2["success_rate"] - 0.05 else "HARMFUL"
    )
    status = "PROVEN_DIRECTIONALLY" if (
        g3["true_gap_precision"] >= 0.95
        and g3["true_gap_recall"] >= 0.95
        and g3["capability_internalization_rate"] >= 0.9
        and g3["critical_stop_correctness"] == 1.0
        and g3["success_rate"] >= g2["success_rate"] - 0.05
    ) else "NOT_READY"
    body = {
        "kind": "CGKNSelfGrowthV1FinalReceipt",
        "schema_version": "1.0",
        "source_commit": commit,
        "source_tree": tree,
        "task_stream_hash": next(iter(stream_ids)),
        "groups": comparison,
        "strong_growth_decision_benefit": strong_benefit,
        "self_growth_status": status,
        "production_adoption_readiness": "READY_FOR_PRODUCTIONIZATION" if status == "PROVEN_DIRECTIONALLY" else "NOT_READY",
        "production_registry_modified": False,
        "formal_group_receipts": [str(path.resolve()) for path in paths],
        "contains_credentials": False,
    }
    result = body | {"receipt_hash": canonical_hash(body)}
    destination = output_root / f"growth-final-{uuid.uuid4().hex[:10]}"
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "final_receipt.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result | {"receipt_path": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Self-Growth V1 evaluation profiles.")
    parser.add_argument("--profile", required=True, choices=["growth-discovery", *PROFILES, "growth-final"])
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--expected-source-commit", default="")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--receipt", type=pathlib.Path, action="append", default=[])
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        if args.profile == "growth-discovery":
            if not 1 <= args.count <= 20:
                raise ValueError("discovery count must be between 1 and 20")
            result = _discovery(output_root, args.count)
        elif args.profile == "growth-final":
            if not args.expected_source_commit:
                raise ValueError("growth-final requires --expected-source-commit")
            result = _final(output_root, args.receipt, args.expected_source_commit)
        else:
            if not args.expected_source_commit:
                raise ValueError("formal growth groups require --expected-source-commit")
            result = _formal_group(args.profile, output_root, args.expected_source_commit)
    except Exception as exc:
        result = {
            "profile": args.profile,
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "redacted_error": str(exc)[:1000],
            "contains_credentials": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
