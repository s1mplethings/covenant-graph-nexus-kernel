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
from cgnk_ctcp.readiness import check_slice_readiness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature", required=True)
    parser.add_argument("--ctcp-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--feature-map", default=str(ROOT / "examples" / "ctcp" / "ctcp_feature_map.json"))
    parser.add_argument("--proposal", default=str(ROOT / "examples" / "proposals" / "replace_plan_provider_with_contract_only_ok.proposal.json"))
    args = parser.parse_args()

    registry = ContractRegistry(ROOT, validate_schema=True)
    report = check_slice_readiness(
        args.feature,
        load_json(pathlib.Path(args.feature_map)),
        registry,
        pathlib.Path(args.ctcp_root),
        pathlib.Path(args.proposal),
    )
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
