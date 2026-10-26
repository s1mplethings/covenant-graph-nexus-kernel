from __future__ import annotations

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.community_operator.runner import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CGKN Community Operator evaluation")
    parser.add_argument("--profile", choices=("audit", "evaluate", "real-read", "final"), default="evaluate")
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "artifacts" / "community_v1" / "latest")
    parser.add_argument("--source-commit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    include_real = args.profile in {"real-read", "final"}
    report = run_evaluation(repo_root=ROOT, output_dir=args.output_dir.resolve(), source_commit=args.source_commit, include_real_read=include_real)
    summary = {"status": report["status"], "profile": args.profile, "output_dir": str(args.output_dir.resolve()), "evaluation_hash": report["evaluation_hash"], "opportunity_cases": report["opportunity_benchmark"]["passed"], "reply_cases": report["reply_benchmark"]["passed"], "policy_cases": report["policy_benchmark"]["passed"], "real_read": report["real_read_dogfood"]["status"], "external_writes": report["security"]["external_writes"]}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True) if args.json else "\n".join(f"{key}: {value}" for key, value in summary.items()))
    return 0 if report["status"] == "PASS" or (not include_real and report["status"].startswith("PASS")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

