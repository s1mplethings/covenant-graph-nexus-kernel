#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.capability_routing.formal import load_pricing_catalog, load_routing  # noqa: E402
from cgkn.providers import GatewayCompletionClient, completion_client_from_environment  # noqa: E402
from experiments.strong_escalation_evidence.closure import (  # noqa: E402
    analyze_closure,
    load_document,
    run_single_replacement,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def _frozen_harness(expected: str) -> str:
    actual = _git("rev-parse", "HEAD")
    if actual != expected:
        raise RuntimeError("PB-027 live replacement requires the exact harness commit")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("PB-027 live replacement requires a clean checkout")
    return actual


def _write_exclusive(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close PB-027 strong-escalation economic evidence")
    parser.add_argument("--profile", choices=("replacement", "audit"), required=True)
    parser.add_argument("--previous-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--previous-budget", type=pathlib.Path, required=True)
    parser.add_argument("--pricing-snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--product-source-commit", required=True)
    parser.add_argument("--product-source-tree", required=True)
    parser.add_argument("--expected-harness-commit", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--replacement", type=pathlib.Path)
    parser.add_argument(
        "--routing",
        type=pathlib.Path,
        default=ROOT / "config/provider_profiles/gateway_model_routing.json",
    )
    args = parser.parse_args(argv)
    harness = _frozen_harness(args.expected_harness_commit)
    previous = load_document(args.previous_receipt)
    if args.profile == "replacement":
        client = completion_client_from_environment()
        if not isinstance(client, GatewayCompletionClient):
            raise RuntimeError("PB-027 replacement requires the reviewed local Gateway route")
        result = run_single_replacement(
            client=client,
            routing=load_routing(args.routing),
            previous_receipt=previous,
            product_source_commit=args.product_source_commit,
            product_source_tree=args.product_source_tree,
            harness_commit=harness,
            run_id="pb027-strong-6-replacement",
        )
    else:
        result = analyze_closure(
            previous_receipt_path=args.previous_receipt,
            previous_budget_path=args.previous_budget,
            pricing_catalog=load_pricing_catalog(args.pricing_snapshot),
            pricing_snapshot_path=args.pricing_snapshot,
            product_source_commit=args.product_source_commit,
            product_source_tree=args.product_source_tree,
            harness_commit=harness,
            replacement_path=args.replacement,
            repository_root=ROOT,
        )
    _write_exclusive(args.output, result)
    if _frozen_harness(harness) != harness:
        raise RuntimeError("PB-027 harness changed during execution")
    print(json.dumps({"status": "PASS", "profile": args.profile, "output": str(args.output), "receipt_hash": result["receipt_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
