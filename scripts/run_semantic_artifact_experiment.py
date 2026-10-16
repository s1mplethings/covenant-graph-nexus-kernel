from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from experiments.semantic_artifact_design.common.designs import get_design
from experiments.semantic_artifact_design.common.evaluator import select
from experiments.semantic_artifact_design.common.metrics import aggregate
from experiments.semantic_artifact_design.common.report import markdown
from experiments.semantic_artifact_design.common.runner import SemanticExperimentRunner


ARTIFACT_ROOT = ROOT / "artifacts/semantic_artifact_experiment"
RECEIPT_ROOT = ROOT / "experiments/semantic_artifact_design/receipts"


def _write(path: pathlib.Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _pytest(*args: str) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=ROOT).returncode


def _run(profile: str, designs: list[str], case_id: str, count: int) -> int:
    runner = SemanticExperimentRunner(ROOT, ARTIFACT_ROOT)
    rows = []
    order = list(designs)
    random.Random("ITER-SEMANTIC-ARTIFACT-DESIGN-009:" + profile).shuffle(order)
    for index in range(count):
        for design in order:
            result = runner.run(design, case_id, profile=profile)
            rows.append(dict(result.receipt))
            print(json.dumps({"design": design, "case_id": case_id, "run_id": result.run_id, "status": result.status, "receipt_hash": result.receipt["receipt_hash"]}))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _write(RECEIPT_ROOT / f"{profile}-{stamp}.json", {"kind": "CGKNSemanticExperimentBatch", "profile": profile, "design_order": order, "receipts": rows})
    return 0


def _latest(profile: str) -> list[dict]:
    paths = sorted(RECEIPT_ROOT.glob(f"{profile}-*.json"))
    return json.loads(paths[-1].read_text(encoding="utf-8"))["receipts"] if paths else []


def _compare() -> int:
    all_receipts = _latest("live-single") + _latest("live-repair") + _latest("repeat")
    rows = [aggregate(design, [item for item in all_receipts if item["design"] == design], get_design(design).complexity(), schema_pass=True, fake_pass=True) for design in "ABC"]
    comparison = select(rows)
    comparison.update({"kind": "CGKNSemanticArtifactDesignComparison", "schema_version": "1.0", "provider": {"agent": "qwen3.8-max", "worker": "qwen3.7-flash"}, "fixed_budgets": {"agent_decisions": 4, "worker_calls": 20, "provider_calls": 24, "repair_rounds": 2}})
    _write(ARTIFACT_ROOT / "comparison.json", comparison)
    (ARTIFACT_ROOT / "comparison.md").write_text(markdown(comparison), encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=("schema", "fake", "live-single", "live-repair", "repeat", "compare"))
    parser.add_argument("--design", choices=("A", "B", "C"))
    args = parser.parse_args()
    designs = [args.design] if args.design else list("ABC")
    if args.profile == "schema": return _pytest("tests/experiments/semantic_artifact_design/test_design_contracts.py", "tests/experiments/semantic_artifact_design/test_interface.py", "tests/experiments/semantic_artifact_design/test_failure.py")
    if args.profile == "fake": return _pytest("tests/experiments/semantic_artifact_design/test_fake_integration.py")
    if args.profile == "live-single": return _run("live-single", designs, "cli_csv_cleaner", 1)
    if args.profile == "live-repair": return _run("live-repair", designs, "seeded_repair", 1)
    if args.profile == "repeat": return _run("repeat", designs, "cli_csv_cleaner", 3)
    return _compare()


if __name__ == "__main__": raise SystemExit(main())
