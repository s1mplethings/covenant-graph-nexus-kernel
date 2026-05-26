#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgnk_core import SchemaLoader  # noqa: E402
from cgnk_core.schema_loader import load_json  # noqa: E402
from cgnk_ctcp.bridge_review import review_ctcp_bridge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--patch-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    review = review_ctcp_bridge(
        load_json(pathlib.Path(args.proposal)),
        load_json(pathlib.Path(args.patch_manifest)),
        schema_loader=SchemaLoader(ROOT),
    )
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(review, indent=2, ensure_ascii=False))
    return 0 if review["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
