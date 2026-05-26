#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import ContractRegistry, apply_graph_edit_proposal  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    registry = ContractRegistry(pathlib.Path(args.root).resolve(), validate_schema=True)
    result = apply_graph_edit_proposal(load_json(pathlib.Path(args.proposal)), registry, dry_run=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
