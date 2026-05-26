#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_modules.readiness import build_module_chain_readiness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chain", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_module_chain_readiness(args.chain, ROOT)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output), "readiness_status": report["readiness_status"]}, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
