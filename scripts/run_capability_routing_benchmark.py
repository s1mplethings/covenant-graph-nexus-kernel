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

from cgkn.application.capability_routing.benchmarks import run_discovery  # noqa: E402
from cgkn.application.capability_routing.contracts import stable_hash  # noqa: E402
from cgkn.application.capability_routing.formal import (  # noqa: E402
    FORMAL_BENCHMARK_VERSION,
    load_pricing_catalog,
    load_routing,
    run_formal_decision,
    run_formal_search,
)
from cgkn.providers import GatewayCompletionClient, completion_client_from_environment  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def _frozen_source(expected_commit: str) -> tuple[str, str]:
    commit = _git("rev-parse", "HEAD")
    if not expected_commit or commit != expected_commit:
        raise RuntimeError("formal benchmark requires the exact expected integrated source commit")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("formal benchmark requires a clean integrated source checkout")
    return commit, _git("rev-parse", "HEAD^{tree}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run capability search and decision-routing benchmarks")
    parser.add_argument(
        "--profile",
        choices=("discovery", "formal-search", "formal-decision", "formal"),
        default="discovery",
    )
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--expected-source-commit")
    parser.add_argument(
        "--routing",
        type=pathlib.Path,
        default=ROOT / "config" / "provider_profiles" / "gateway_model_routing.json",
    )
    parser.add_argument("--pricing-snapshot", type=pathlib.Path)
    args = parser.parse_args(argv)
    if args.profile == "discovery":
        receipt = run_discovery()
    else:
        if args.output is None:
            parser.error("formal profiles require --output")
        source_commit, source_tree = _frozen_source(str(args.expected_source_commit or ""))
        search = run_formal_search(source_commit=source_commit, source_tree=source_tree)
        decision = None
        if args.profile in {"formal-decision", "formal"}:
            client = completion_client_from_environment()
            if not isinstance(client, GatewayCompletionClient):
                raise RuntimeError("formal decision benchmark requires the reviewed local Gateway route")
            routing = load_routing(args.routing.resolve())
            decision = run_formal_decision(
                client=client,
                routing=routing,
                source_commit=source_commit,
                source_tree=source_tree,
                pricing_catalog=(
                    load_pricing_catalog(args.pricing_snapshot.resolve())
                    if args.pricing_snapshot
                    else None
                ),
            )
        if args.profile == "formal-search":
            receipt = search
        elif args.profile == "formal-decision":
            receipt = decision
        else:
            body = {
                "kind": "CapabilityRoutingFormalReceipt",
                "schema_version": "1.0",
                "benchmark_version": FORMAL_BENCHMARK_VERSION,
                "source_commit": source_commit,
                "source_tree": source_tree,
                "search": search,
                "decision": decision,
                "contains_credentials": False,
            }
            receipt = body | {"receipt_hash": stable_hash(body)}
        after_commit, after_tree = _frozen_source(source_commit)
        if (after_commit, after_tree) != (source_commit, source_tree):
            raise RuntimeError("integrated source identity changed during formal benchmark")
    raw = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.profile == "discovery":
            args.output.write_text(raw, encoding="utf-8")
        else:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(raw)
    if args.json or not args.output:
        print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
