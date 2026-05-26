#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry  # noqa: E402
from cgnk_ctcp.feature_map import check_feature_map, load_feature_map  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-map", default=str(ROOT / "examples" / "ctcp" / "ctcp_feature_map.json"))
    parser.add_argument("--ctcp-root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    registry = ContractRegistry(ROOT, validate_schema=True)
    ctcp_root = pathlib.Path(args.ctcp_root) if args.ctcp_root else None
    report = check_feature_map(load_feature_map(pathlib.Path(args.feature_map)), registry, ctcp_root)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
