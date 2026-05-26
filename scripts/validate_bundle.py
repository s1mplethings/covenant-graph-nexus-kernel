#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cgnk_core import validate_bundle  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--flow", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--schema", action="store_true", help="Run optional jsonschema validation. Semantic compile checks run by default.")
    args = ap.parse_args()

    root = pathlib.Path(args.root).resolve()
    out = validate_bundle(root, flows=args.flow, schema=args.schema)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for msg in out["schema_validation"]:
            print(f"SCHEMA: {msg}")
        for result in out["results"]:
            print(f"{result['flow_ref']}: {'OK' if result['ok'] else 'FAIL'} errors={result['statistics']['errors']}")
            for diag in result["diagnostics"]:
                print(f"  {diag['severity'].upper()} {diag['code']} {diag['path']}: {diag['message']}")

    real_schema_errs = [m for m in out["schema_validation"] if not m.startswith("schema validation skipped")]
    return 0 if not real_schema_errs and all(r["ok"] for r in out["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
