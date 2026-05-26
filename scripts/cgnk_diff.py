#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core.diff import diff_compile_results  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    diff = diff_compile_results(load_json(pathlib.Path(args.before)), load_json(pathlib.Path(args.after)))
    print(json.dumps(diff, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
