#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_modules.registry import check_p0_modules  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0", action="store_true", help="Check the P0 clean-room module set")
    args = parser.parse_args()
    if not args.p0:
        parser.error("Only --p0 is supported")
    report = check_p0_modules(ROOT)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
