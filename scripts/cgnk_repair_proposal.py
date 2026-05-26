#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry  # noqa: E402
from cgnk_core.repair import build_repair_plan  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--flow", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    registry = ContractRegistry(ROOT, validate_schema=True)
    plan = build_repair_plan(load_json(pathlib.Path(args.proposal)), args.flow, registry)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
