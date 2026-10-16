from __future__ import annotations

import argparse
import json
import pathlib

from cgkn.application.requirements import compare_csv_strategies, write_strategy_comparison
from cgkn.providers import ModelRoleConfig, OpenAICompatibleClient


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("live-single", "live-repeat"), required=True)
    parser.add_argument("--output", default="artifacts/obligation-strategy")
    args = parser.parse_args()
    repeats = 1 if args.profile == "live-single" else 3
    target = (ROOT / args.output).resolve()
    comparison = compare_csv_strategies(
        ROOT, target, OpenAICompatibleClient(),
        ModelRoleConfig("agent", "qwen3.8-max", timeout_seconds=90, max_output_tokens=7000),
        ModelRoleConfig("worker", "qwen3.7-flash", timeout_seconds=90, max_output_tokens=6000),
        repeats,
    )
    path = write_strategy_comparison(target / f"{args.profile}.json", comparison)
    print(json.dumps({"status": "PASS", "receipt": str(path), "comparison": comparison.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
