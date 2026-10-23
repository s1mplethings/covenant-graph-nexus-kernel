from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_knowledge_growth_evaluation import run_benchmark  # noqa: E402


def test_controlled_growth_benchmark_proves_local_scope() -> None:
    result = run_benchmark([100])
    assert result["status"] == "PASS"
    rows = {row["policy"]: row for row in result["rows"]}
    assert rows["FLAT_APPEND"]["retrieval_candidates_evaluated"] > rows["LOCAL_LAZY"]["retrieval_candidates_evaluated"]
    assert rows["EAGER_GLOBAL_REBUILD"]["nodes_recomputed_on_write"] > rows["LOCAL_LAZY"]["nodes_recomputed_on_write"]
    assert rows["LOCAL_LAZY"]["nodes_invalidated"] == 1
    assert rows["LOCAL_LAZY"]["bucket_items_touched"] <= 4
    assert result["duplicate_probe"]["model_calls"] == 0
