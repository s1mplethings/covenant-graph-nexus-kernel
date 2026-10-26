#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release_057_oracle_analysis import analyze_oracle, canonical_hash  # noqa: E402


def _read_index(path: pathlib.Path, expected_baseline: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("baseline") != expected_baseline:
        raise ValueError(f"expected {expected_baseline} at {path}")
    if value.get("task_count") != 72 or value.get("completed_count") != 72:
        raise ValueError(f"expected a complete 72-task run at {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ITER-057 paired architecture-routing oracle gate")
    parser.add_argument("--direct", type=pathlib.Path, required=True)
    parser.add_argument("--architecture", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    direct = _read_index(args.direct, "B0_DIRECT_CHEAP")
    architecture = _read_index(args.architecture, "B4_OPTIMIZED_CGNK_RC")
    result = analyze_oracle(direct["rows"], architecture["rows"])
    result.update({
        "direct_batch_id": direct.get("batch_id"),
        "architecture_batch_id": architecture.get("batch_id"),
        "source_result_hashes": {
            "direct": direct.get("receipt_hash"),
            "architecture": architecture.get("receipt_hash"),
        },
    })
    result["analysis_hash"] = canonical_hash({key: value for key, value in result.items() if key != "analysis_hash"})
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"router-opportunity: {result['router_opportunity']} "
            f"(oracle={result['oracle_successes']}/{result['task_count']}, "
            f"gain={result['oracle_gain_percentage_points']:.2f}pp)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
