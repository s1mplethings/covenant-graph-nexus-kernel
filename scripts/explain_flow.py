#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.compiler import ArtifactFlowCompiler


def explain(flow_ref: str) -> dict:
    compiler = ArtifactFlowCompiler(ROOT)
    result = compiler.compile(flow_ref)
    if not result["ok"]:
        return result
    flow = result["compiled_bundle"]["normalized_flow"]
    rows = []
    for node in flow["nodes"]:
        module = compiler.modules[node["uses"]]
        rows.append(
            {
                "node": node["id"],
                "module": node["uses"],
                "inputs": {key: value["artifact_type"] for key, value in module["ports"]["input"].items()},
                "outputs": {key: value["artifact_type"] for key, value in module["ports"]["output"].items()},
                "effects": module["effects"],
                "policy": flow.get("policy_ref"),
                "cacheable": module.get("implementation", {}).get("cacheable", False),
            }
        )
    return {"kind": "ArtifactFlowExplanation", "flowRef": flow_ref, "nodes": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain typed inputs, outputs, effects, policy, and cacheability for a flow.")
    parser.add_argument("--flow", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = explain(args.flow)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in result.get("nodes", []):
            print(f"{row['node']} ({row['module']})")
            print(f"  input: {row['inputs']}")
            print(f"  output: {row['outputs']}")
            print(f"  effects: {row['effects']}")
            print(f"  policy: {row['policy']} cacheable={row['cacheable']}")
    return 0 if "diagnostics" not in result or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
