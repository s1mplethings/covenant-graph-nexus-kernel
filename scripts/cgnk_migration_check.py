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
from cgnk_ctcp.migration import check_migration_spec, write_reports  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctcp-root", required=True)
    parser.add_argument("--migration", default=str(ROOT / "examples" / "migrations" / "project_generation.migration.json"))
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    registry = ContractRegistry(ROOT, validate_schema=True)
    report = check_migration_spec(load_json(pathlib.Path(args.migration)), registry, pathlib.Path(args.ctcp_root))
    write_reports(report, pathlib.Path(args.output_dir))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
