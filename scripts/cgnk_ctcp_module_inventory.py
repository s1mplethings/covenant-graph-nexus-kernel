#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import SchemaLoader  # noqa: E402
from cgnk_ctcp.module_discovery import discover_module_inventory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctcp-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--transfer-plan")
    args = parser.parse_args()

    schema_loader = SchemaLoader(ROOT)
    inventory, transfer_plan = discover_module_inventory(pathlib.Path(args.ctcp_root), schema_loader)

    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.transfer_plan:
        transfer_path = pathlib.Path(args.transfer_plan)
        transfer_path.parent.mkdir(parents=True, exist_ok=True)
        transfer_path.write_text(json.dumps(transfer_plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"ok": inventory["ok"] and transfer_plan["ok"], "output": str(output), "transfer_plan": args.transfer_plan}, indent=2, ensure_ascii=False))
    return 0 if inventory["ok"] and transfer_plan["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
