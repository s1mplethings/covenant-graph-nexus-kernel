from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_quick_large_sync_tree_benchmark import audit_synchronous_growth


def _write_ledger(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _complete_rows() -> list[dict]:
    rows = [{"round": 0, "branch": "root", "depth": 0, "action": "capture_goal", "checkpoint": True}]
    for round_no in (1, 2, 3, 4):
        for branch in ("requirement", "architecture"):
            rows.append(
                {
                    "round": round_no,
                    "branch": branch,
                    "depth": round_no,
                    "action": "checkpoint",
                    "checkpoint": True,
                    "parent_branch": "root" if round_no == 1 else branch,
                }
            )
    return rows


def test_complete_synchronous_ledger_passes(tmp_path: pathlib.Path) -> None:
    audit = audit_synchronous_growth(_write_ledger(tmp_path / "sync_growth_ledger.jsonl", _complete_rows()))

    assert audit["sync_status"] == "pass"
    assert audit["branch_count"] == 2
    assert audit["max_depth_gap"] == 0


def test_missing_branch_round_fails(tmp_path: pathlib.Path) -> None:
    rows = [row for row in _complete_rows() if not (row.get("round") == 3 and row.get("branch") == "architecture")]

    audit = audit_synchronous_growth(_write_ledger(tmp_path / "sync_growth_ledger.jsonl", rows))

    assert audit["sync_status"] == "fail"
    assert "architecture" in audit["starved_branches"]
    assert audit["missing_round_coverage"]


def test_depth_gap_greater_than_one_fails(tmp_path: pathlib.Path) -> None:
    rows = _complete_rows()
    for row in rows:
        if row.get("round") == 2 and row.get("branch") == "architecture":
            row["depth"] = 5

    audit = audit_synchronous_growth(_write_ledger(tmp_path / "sync_growth_ledger.jsonl", rows))

    assert audit["sync_status"] == "fail"
    assert audit["max_depth_gap"] > 1


def test_missing_checkpoint_fails(tmp_path: pathlib.Path) -> None:
    rows = _complete_rows()
    rows[2]["checkpoint"] = False

    audit = audit_synchronous_growth(_write_ledger(tmp_path / "sync_growth_ledger.jsonl", rows))

    assert audit["sync_status"] == "fail"
    assert audit["missing_checkpoints"]


def test_orphan_leaf_fails(tmp_path: pathlib.Path) -> None:
    rows = _complete_rows()
    rows.append({"round": 2, "branch": "search_leaf", "depth": 2, "action": "leaf", "checkpoint": True})

    audit = audit_synchronous_growth(_write_ledger(tmp_path / "sync_growth_ledger.jsonl", rows))

    assert audit["sync_status"] == "fail"
    assert audit["orphan_leaves"]
