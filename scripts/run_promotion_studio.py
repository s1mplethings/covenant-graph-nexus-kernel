from __future__ import annotations

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.promotion_studio.runner import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CGKN Promotion Studio evaluation")
    parser.add_argument("--profile", choices=("audit", "promotion-evaluate", "real-campaign", "final"), default="promotion-evaluate")
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "artifacts" / "promotion_v1" / "latest")
    parser.add_argument("--source-commit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_evaluation(repo_root=ROOT, output_dir=args.output_dir.resolve(), source_commit=args.source_commit)
    summary = {"status": report["status"], "profile": args.profile, "output_dir": str(args.output_dir.resolve()), "evaluation_hash": report["evaluation_hash"], "signals": report["signal_cases"]["passed"], "campaigns": report["campaign_cases"]["passed"], "real_publication": report["real_publication"]["status"]}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True) if args.json else "\n".join(f"{key}: {value}" for key, value in summary.items()))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
