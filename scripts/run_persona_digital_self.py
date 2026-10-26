from __future__ import annotations

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.persona_digital_self.runner import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CGKN Persona Digital Self v1 evaluation")
    parser.add_argument("--profile", choices=("status", "lifelong", "community-read", "final"), default="lifelong")
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "artifacts" / "persona_v1" / "latest")
    parser.add_argument("--source-commit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_evaluation(repo_root=ROOT, output_dir=args.output_dir.resolve(), source_commit=args.source_commit,
                            include_real_read=args.profile in {"community-read", "final"})
    p3 = report["lifelong"]["variants"]["P3"]["metrics"]
    summary = {"status": report["status"], "profile": args.profile, "evaluation_hash": report["evaluation_hash"],
               "episodes": report["lifelong"]["episodes"], "identity_consistency": p3["identity_consistency_rate"],
               "memory_hallucination_rate": p3["memory_hallucination_rate"], "generic_reply_rate": p3["generic_reply_rate"],
               "context_reduction": report["context_localization"]["reduction"], "external_writes": report["security"]["external_writes"]}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True) if args.json else "\n".join(f"{k}: {v}" for k, v in summary.items()))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
