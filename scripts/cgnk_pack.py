#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry, build_agent_contract_pack, compile_flow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    registry = ContractRegistry(root, validate_schema=True)
    result = compile_flow(args.flow, registry)
    if not result["ok"]:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    flow = registry.resolve_flow(args.flow)
    policy = registry.resolve_policy(result["policy_ref"])
    if flow is None or policy is None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1
    modules = list(registry.modules.values())
    artifacts = list(registry.artifacts.values())
    pack = build_agent_contract_pack(result, flow, policy, modules, artifacts, args.task)
    diagnostics = registry.schema_loader.validate(pack, "agent_contract_pack.schema.json", "$.agent_contract_pack")
    if diagnostics:
        print(json.dumps({"ok": False, "diagnostics": [d.as_dict() for d in diagnostics]}, indent=2, ensure_ascii=False))
        return 1

    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "target_flow": args.flow}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
