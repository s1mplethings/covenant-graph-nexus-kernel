#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


FORMAL_CHAIN_STAGES = {"planning", "generation", "repair"}
NON_FORMAL_STAGES = {"external_smoke", "support_reply", "public_status", "delivery_summary"}
FORMAL_CONTEXTS = {
    "formal_live_generation",
    "feasibility_live_smoke",
    "project_generation_manifest",
    "commercial_readiness",
    "delivery_candidate_generation",
    "repair",
    "fix",
}

FORMAL_MODEL_NOT_USED = "FORMAL_MODEL_NOT_USED"
FORMAL_MODEL_EVIDENCE_MISSING = "FORMAL_MODEL_EVIDENCE_MISSING"
FORMAL_GENERATION_REQUIRES_MODEL = "FORMAL_GENERATION_REQUIRES_MODEL"
FORMAL_MODEL_LEDGER_EXTERNAL_ONLY = "FORMAL_MODEL_LEDGER_EXTERNAL_ONLY"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(str(text).encode("utf-8", errors="replace")).hexdigest()


def ledger_path(run_dir: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(run_dir)
    if root.name == "artifacts":
        return root / "model_call_ledger.jsonl"
    return root / "artifacts" / "model_call_ledger.jsonl"


def normalize_stage(stage: str) -> str:
    value = str(stage or "").strip().lower()
    if value in FORMAL_CHAIN_STAGES or value in NON_FORMAL_STAGES:
        return value
    if value in {"project_generation", "component_generation", "component_file_manifest"}:
        return "generation"
    if value in {"semantic_review", "provider_semantic_review", "semantic_repair", "file_repair", "post_build_repair"}:
        return "repair"
    if value in {"usage_planning", "usage_plan", "lightweight_summary", "pipeline_planner", "cfo_pipeline"}:
        return "planning"
    return value or "unknown"


def requires_model(context: str) -> bool:
    value = str(context or "").strip().lower()
    if value in FORMAL_CONTEXTS:
        return True
    return any(token in value for token in ("formal", "feasibility_live", "project_generation", "commercial", "delivery_candidate", "repair", "fix"))


def formal_record(record: dict[str, Any]) -> bool:
    return (
        bool(record.get("executed"))
        and bool(record.get("used_in_formal_chain"))
        and str(record.get("status", "")).lower() == "ok"
        and normalize_stage(str(record.get("stage", ""))) in FORMAL_CHAIN_STAGES
    )


def append_model_call(
    run_dir: str | pathlib.Path,
    *,
    run_id: str = "",
    stage: str,
    provider: str,
    model: str,
    requested: bool,
    executed: bool,
    status: str,
    used_in_formal_chain: bool,
    input_value: Any = "",
    output_value: Any = "",
    output_refs: list[str] | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> pathlib.Path:
    path = ledger_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": now(),
        "run_id": run_id or pathlib.Path(run_dir).name,
        "stage": normalize_stage(stage),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "requested": bool(requested),
        "executed": bool(executed),
        "status": str(status or ""),
        "used_in_formal_chain": bool(used_in_formal_chain),
        "input_hash": stable_hash(input_value) if input_value not in (None, "") else "",
        "output_hash": stable_hash(output_value) if output_value not in (None, "") else "",
        "output_refs": output_refs or [],
        "error": error,
    }
    if metadata:
        record["metadata"] = metadata
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def read_ledger(run_dir: str | pathlib.Path) -> list[dict[str, Any]]:
    path = ledger_path(run_dir)
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


def evaluate_model_participation(
    *,
    context: str,
    run_dir: str | pathlib.Path | None = None,
    usage_plan: dict[str, Any] | None = None,
    ledger_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required = requires_model(context)
    usage = usage_plan or {}
    usage_uses_model = usage.get("uses_model")
    if required and usage_uses_model is False:
        return {
            "status": "fail",
            "reason": FORMAL_MODEL_NOT_USED,
            "requires_model": True,
            "uses_model": False,
            "formal_model_evidence": False,
        }
    records = ledger_records if ledger_records is not None else (read_ledger(run_dir) if run_dir is not None else [])
    formal = [row for row in records if formal_record(row)]
    if required and not records:
        return {
            "status": "fail",
            "reason": FORMAL_MODEL_EVIDENCE_MISSING,
            "requires_model": True,
            "uses_model": bool(usage.get("uses_model")),
            "formal_model_evidence": False,
        }
    if required and not formal:
        non_formal_ok = [row for row in records if str(row.get("status", "")).lower() == "ok"]
        reason = FORMAL_MODEL_LEDGER_EXTERNAL_ONLY if non_formal_ok else FORMAL_MODEL_EVIDENCE_MISSING
        return {
            "status": "fail",
            "reason": reason,
            "requires_model": True,
            "uses_model": bool(usage.get("uses_model")),
            "formal_model_evidence": False,
            "ledger_records": len(records),
        }
    return {
        "status": "pass",
        "reason": "FORMAL_MODEL_PARTICIPATION_OK" if required else "MODEL_NOT_REQUIRED",
        "requires_model": required,
        "uses_model": True if formal else bool(usage.get("uses_model")),
        "formal_model_evidence": bool(formal),
        "formal_records": len(formal),
        "ledger_records": len(records),
    }
