from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Any

STORE_VERSION = 1
DEFAULT_SCORE = 0.72
EXTERNAL_EVENTS = {"provider_quota", "provider_unavailable", "network_transient", "user_changed_requirement"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reputation_store_path(path: str | pathlib.Path | None = None) -> pathlib.Path:
    if path:
        return pathlib.Path(path)
    env_path = os.environ.get("CGKN_AGENT_REPUTATION_PATH", "").strip()
    if env_path:
        return pathlib.Path(env_path)
    return pathlib.Path(".agent_private") / "agent_reputation.json"


def _empty_store() -> dict[str, Any]:
    return {"kind": "AgentReputationStore", "version": STORE_VERSION, "records": {}, "updated_at": now()}


def load_reputation_store(path: str | pathlib.Path | None = None) -> dict[str, Any]:
    store_path = reputation_store_path(path)
    if not store_path.exists():
        return _empty_store()
    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    if int(data.get("version", 0) or 0) < STORE_VERSION:
        data = migrate_store(data)
    data.setdefault("records", {})
    data.setdefault("version", STORE_VERSION)
    return data


def migrate_store(data: dict[str, Any]) -> dict[str, Any]:
    migrated = _empty_store()
    records = data.get("records", {}) if isinstance(data.get("records"), dict) else {}
    migrated["records"] = records
    migrated["migrated_from_version"] = data.get("version", 0)
    return migrated


def save_reputation_store(store: dict[str, Any], path: str | pathlib.Path | None = None) -> pathlib.Path:
    store_path = reputation_store_path(path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store["version"] = STORE_VERSION
    store["updated_at"] = now()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(store_path.parent), prefix=store_path.name, suffix=".tmp") as handle:
        json.dump(store, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    pathlib.Path(temp_name).replace(store_path)
    return store_path


def reputation_key(agent_id: str, domain: str, task_type: str) -> str:
    return "::".join([str(agent_id), str(domain), str(task_type)])


def cold_record(agent_id: str, role: str, domain: str, task_type: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "role": role,
        "domain": domain,
        "task_type": task_type,
        "evidence_count": 0,
        "successful_tasks": 0,
        "failed_tasks": 0,
        "first_pass_rate": DEFAULT_SCORE,
        "scope_discipline": DEFAULT_SCORE,
        "integration_rework_rate": 0.0,
        "budget_predictability": DEFAULT_SCORE,
        "management_score": DEFAULT_SCORE,
        "reviewer_score": DEFAULT_SCORE,
        "last_updated_at": "",
        "decay_version": "linear_v1",
        "store_version": STORE_VERSION,
    }


def record_reputation_event(
    path: str | pathlib.Path | None,
    *,
    agent_id: str,
    role: str,
    domain: str,
    task_type: str,
    event_type: str,
    first_pass: bool = False,
    scope_violation: bool = False,
    integration_rework: bool = False,
    budget_variance: float = 0.0,
    management_fault: bool = False,
) -> dict[str, Any]:
    store = load_reputation_store(path)
    key = reputation_key(agent_id, domain, task_type)
    record = dict(store["records"].get(key) or cold_record(agent_id, role, domain, task_type))
    if event_type in EXTERNAL_EVENTS:
        record["last_updated_at"] = now()
        store["records"][key] = record
        save_reputation_store(store, path)
        return record
    record["evidence_count"] = int(record.get("evidence_count", 0)) + 1
    if event_type == "task_completed":
        record["successful_tasks"] = int(record.get("successful_tasks", 0)) + 1
        record["first_pass_rate"] = _rolling(record.get("first_pass_rate", DEFAULT_SCORE), 1.0 if first_pass else 0.55, record["evidence_count"])
        record["scope_discipline"] = _rolling(record.get("scope_discipline", DEFAULT_SCORE), 0.95 if not scope_violation else 0.35, record["evidence_count"])
        record["budget_predictability"] = _rolling(record.get("budget_predictability", DEFAULT_SCORE), max(0.0, 1.0 - abs(float(budget_variance))), record["evidence_count"])
    elif event_type in {"task_failed", "scope_violation", "false_success"}:
        record["failed_tasks"] = int(record.get("failed_tasks", 0)) + 1
        record["scope_discipline"] = _rolling(record.get("scope_discipline", DEFAULT_SCORE), 0.2 if scope_violation or event_type == "scope_violation" else 0.55, record["evidence_count"])
    if integration_rework:
        total = max(1, int(record.get("evidence_count", 1)))
        record["integration_rework_rate"] = min(1.0, (float(record.get("integration_rework_rate", 0.0)) * (total - 1) + 1.0) / total)
    if management_fault:
        record["management_score"] = max(0.0, float(record.get("management_score", DEFAULT_SCORE)) - 0.15)
    record["last_updated_at"] = now()
    store["records"][key] = record
    save_reputation_store(store, path)
    return record


def _rolling(old: Any, new: float, count: int) -> float:
    prior = float(old if isinstance(old, (int, float)) else DEFAULT_SCORE)
    weight = min(0.5, 1.0 / max(1, count))
    return round(prior * (1.0 - weight) + float(new) * weight, 4)


def reputation_score(record: dict[str, Any], *, decay_factor: float = 1.0) -> float:
    quality = (
        float(record.get("first_pass_rate", DEFAULT_SCORE)) * 0.25
        + float(record.get("scope_discipline", DEFAULT_SCORE)) * 0.25
        + (1.0 - float(record.get("integration_rework_rate", 0.0))) * 0.15
        + float(record.get("budget_predictability", DEFAULT_SCORE)) * 0.15
        + float(record.get("management_score", DEFAULT_SCORE)) * 0.10
        + float(record.get("reviewer_score", DEFAULT_SCORE)) * 0.10
    )
    evidence_bonus = min(0.08, int(record.get("evidence_count", 0)) * 0.01)
    return round(max(0.0, min(1.0, quality * max(0.0, min(1.0, decay_factor)) + evidence_bonus)), 4)


def reputation_snapshot(path: str | pathlib.Path | None, *, domain: str, task_type: str, decay_factor: float = 1.0) -> dict[str, Any]:
    store = load_reputation_store(path)
    records = {}
    for key, record in store.get("records", {}).items():
        if not isinstance(record, dict):
            continue
        if record.get("domain") == domain and record.get("task_type") == task_type:
            item = dict(record)
            item["reputation_score"] = reputation_score(item, decay_factor=decay_factor)
            records[str(record.get("agent_id"))] = item
    return {"kind": "AgentReputationSnapshot", "domain": domain, "task_type": task_type, "records": records, "decay_factor": decay_factor, "created_at": now()}


def select_with_reputation(
    candidates: list[str],
    *,
    path: str | pathlib.Path | None,
    domain: str,
    task_type: str,
    loads: dict[str, int] | None = None,
    decay_factor: float = 1.0,
) -> dict[str, Any]:
    snapshot = reputation_snapshot(path, domain=domain, task_type=task_type, decay_factor=decay_factor)
    rows = []
    for agent_id in candidates:
        record = snapshot["records"].get(agent_id) or cold_record(agent_id, "", domain, task_type)
        score = reputation_score(record, decay_factor=decay_factor) - min(0.3, int((loads or {}).get(agent_id, 0)) * 0.1)
        rows.append({"agent_id": agent_id, "score": round(score, 4), "evidence_count": int(record.get("evidence_count", 0))})
    rows.sort(key=lambda item: (-item["score"], -item["evidence_count"], item["agent_id"]))
    return {"selected_agent": rows[0]["agent_id"] if rows else "", "candidates": rows, "snapshot": snapshot}

