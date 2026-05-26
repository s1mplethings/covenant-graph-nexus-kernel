#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402
from cgnk_ctcp.candidate_promotion import validate_candidate_promotion  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default=str(ROOT / "examples" / "ctcp" / "ctcp_module_inventory.curated.json"))
    parser.add_argument("--transfer-plan", default=str(ROOT / "examples" / "ctcp" / "ctcp_transfer_plan.curated.json"))
    args = parser.parse_args()

    registry = ContractRegistry(ROOT, validate_schema=True)
    report = validate_candidate_promotion(load_json(pathlib.Path(args.inventory)), load_json(pathlib.Path(args.transfer_plan)), registry)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
