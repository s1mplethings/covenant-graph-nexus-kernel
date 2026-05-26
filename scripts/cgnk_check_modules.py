#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_modules.registry import check_all_modules, check_p0_modules  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0", action="store_true", help="Check the P0 clean-room module set")
    parser.add_argument("--all", action="store_true", help="Check all registered clean-room modules")
    args = parser.parse_args()
    if args.p0 == args.all:
        parser.error("Pass exactly one of --p0 or --all")
    report = check_p0_modules(ROOT) if args.p0 else check_all_modules(ROOT)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
