#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "artifacts" / "continuous_generation_iterations.jsonl"
LAYERS = {
    "requirement_decision",
    "product_contract",
    "implementation",
    "delivery",
    "test_infrastructure",
    "provider_transport",
    "naming_consistency",
}
STATUSES = {"PASS", "PARTIAL", "FAIL", "BLOCKED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_iterations(path: pathlib.Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            records.append(doc)
    return records


def next_iteration(path: pathlib.Path = LEDGER_PATH) -> int:
    records = load_iterations(path)
    if not records:
        return 1
    return max(int(record.get("iteration") or 0) for record in records) + 1


def normalize_record(record: dict[str, Any], path: pathlib.Path = LEDGER_PATH) -> dict[str, Any]:
    started = str(record.get("started_at") or now())
    ended = str(record.get("ended_at") or now())
    layer = str(record.get("layer") or "test_infrastructure")
    if layer not in LAYERS:
        layer = "test_infrastructure"
    status = str(record.get("status") or "PARTIAL").upper()
    if status not in STATUSES:
        status = "PARTIAL"
    normalized = {
        "iteration": int(record.get("iteration") or next_iteration(path)),
        "started_at": started,
        "ended_at": ended,
        "selected_gap": str(record.get("selected_gap") or "unspecified_gap"),
        "layer": layer,
        "reason_for_priority": str(record.get("reason_for_priority") or ""),
        "micro_plan": list(record.get("micro_plan") or []),
        "acceptance_criteria": list(record.get("acceptance_criteria") or []),
        "files_changed": list(record.get("files_changed") or []),
        "tests_added_or_updated": list(record.get("tests_added_or_updated") or []),
        "commands_run": list(record.get("commands_run") or []),
        "test_results": list(record.get("test_results") or []),
        "benchmark_results": list(record.get("benchmark_results") or []),
        "status": status,
        "known_gaps_after_iteration": list(record.get("known_gaps_after_iteration") or []),
        "next_recommended_action": str(record.get("next_recommended_action") or ""),
    }
    return normalized


def append_iteration(record: dict[str, Any], path: pathlib.Path = LEDGER_PATH) -> dict[str, Any]:
    normalized = normalize_record(record, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(LEDGER_PATH))
    parser.add_argument("--record-json", default="")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    path = pathlib.Path(args.path)
    if args.list:
        print(json.dumps(load_iterations(path), ensure_ascii=False, indent=2))
        return 0
    record = json.loads(args.record_json) if args.record_json else {}
    written = append_iteration(record, path)
    print(json.dumps(written, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
