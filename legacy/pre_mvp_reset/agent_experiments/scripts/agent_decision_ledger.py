#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


def decision_ledger_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(run_dir)
    artifacts = root if root.name == "artifacts" else root / "artifacts"
    return artifacts / "agent_decision_ledger.jsonl"


def observed_state_hash(state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def read_decision_ledger(run_dir: str | pathlib.Path) -> list[dict[str, Any]]:
    path = decision_ledger_path(run_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_decision(run_dir: str | pathlib.Path, decision: dict[str, Any], result: dict[str, Any] | None = None) -> pathlib.Path:
    path = decision_ledger_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_decision_ledger(run_dir)
    record = dict(decision)
    record.setdefault("step", len(rows) + 1)
    record.setdefault("agent_role", "Project Director")
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("status", "planned")
    record.setdefault("selected_tool", "")
    record.setdefault("rejected_tools", [])
    record.setdefault("reason", "")
    record.setdefault("expected_outputs", [])
    record.setdefault("result_refs", [])
    if result is not None:
        record["execution_result"] = result
        if result.get("status"):
            record["status"] = str(result["status"])
        refs = result.get("artifacts") or result.get("result_refs") or []
        if isinstance(refs, list):
            record["result_refs"] = [str(item) for item in refs]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path
