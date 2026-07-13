from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from datetime import datetime, timezone
from typing import Any


VALID_STATUS = {"candidate", "confirmed", "deprecated", "conflicted", "rejected"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def signature(problem: dict[str, Any]) -> str:
    relevant = {
        "project_type": problem.get("project_type", ""),
        "task_type": problem.get("task_type", ""),
        "stage": problem.get("stage", ""),
        "symptoms": sorted(str(item).lower() for item in problem.get("symptoms", []) if str(item).strip()),
    }
    raw = json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExperienceStore:
    def __init__(self, db_path: str | pathlib.Path, audit_path: str | pathlib.Path | None = None) -> None:
        self.db_path = pathlib.Path(db_path)
        self.audit_path = pathlib.Path(audit_path) if audit_path else self.db_path.with_suffix(".jsonl")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                create table if not exists experiences(
                    experience_id text primary key,
                    problem_signature text not null,
                    project_type text not null,
                    task_type text not null,
                    stage text not null,
                    symptoms_json text not null,
                    root_cause text not null,
                    action text not null,
                    verification text not null,
                    outcome text not null,
                    confidence real not null,
                    evidence_refs_json text not null,
                    source_run_id text not null,
                    source_task_id text not null,
                    applicable_versions_json text not null,
                    model_source text not null,
                    created_at text not null,
                    last_used_at text not null,
                    use_count integer not null default 0,
                    success_count integer not null default 0,
                    failure_count integer not null default 0,
                    status text not null,
                    negative_conditions_json text not null default '[]'
                )
                """
            )
            db.execute("create index if not exists idx_experience_signature on experiences(problem_signature)")
            db.execute("create index if not exists idx_experience_lookup on experiences(project_type, task_type, stage, status)")

    def _audit(self, event: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {"created_at": utc_now(), **event}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def record_candidate(self, doc: dict[str, Any]) -> dict[str, Any]:
        status = str(doc.get("status") or "candidate")
        if status not in VALID_STATUS:
            raise ValueError(f"invalid experience status: {status}")
        if status == "confirmed" and not self._confirmation_allowed(doc):
            raise ValueError("confirmed experience requires verified execution evidence")
        problem_signature = str(doc.get("problem_signature") or signature(doc))
        experience_id = str(doc.get("experience_id") or f"exp_{problem_signature[:16]}")
        now = utc_now()
        row = {
            "experience_id": experience_id,
            "problem_signature": problem_signature,
            "project_type": str(doc.get("project_type", "")),
            "task_type": str(doc.get("task_type", "")),
            "stage": str(doc.get("stage", "")),
            "symptoms_json": json.dumps(doc.get("symptoms", []), ensure_ascii=False),
            "root_cause": str(doc.get("root_cause", "")),
            "action": str(doc.get("action", "")),
            "verification": str(doc.get("verification", "")),
            "outcome": str(doc.get("outcome", "")),
            "confidence": float(doc.get("confidence", 0.25)),
            "evidence_refs_json": json.dumps(doc.get("evidence_refs", []), ensure_ascii=False),
            "source_run_id": str(doc.get("source_run_id", "")),
            "source_task_id": str(doc.get("source_task_id", "")),
            "applicable_versions_json": json.dumps(doc.get("applicable_versions", []), ensure_ascii=False),
            "model_source": str(doc.get("model_source", "deterministic")),
            "created_at": now,
            "last_used_at": now,
            "status": status,
            "negative_conditions_json": json.dumps(doc.get("negative_conditions", []), ensure_ascii=False),
        }
        with self.connect() as db:
            db.execute(
                """
                insert or replace into experiences(
                    experience_id, problem_signature, project_type, task_type, stage, symptoms_json,
                    root_cause, action, verification, outcome, confidence, evidence_refs_json,
                    source_run_id, source_task_id, applicable_versions_json, model_source,
                    created_at, last_used_at, status, negative_conditions_json
                ) values(
                    :experience_id, :problem_signature, :project_type, :task_type, :stage, :symptoms_json,
                    :root_cause, :action, :verification, :outcome, :confidence, :evidence_refs_json,
                    :source_run_id, :source_task_id, :applicable_versions_json, :model_source,
                    :created_at, :last_used_at, :status, :negative_conditions_json
                )
                """,
                row,
            )
        self._audit({"event": "experience_recorded", "experience_id": experience_id, "status": status})
        return self.get(experience_id)

    def confirm_from_verified_repair(self, experience_id: str, *, evidence_refs: list[str], verification: str) -> dict[str, Any]:
        row = self.get(experience_id)
        if not row:
            raise KeyError(experience_id)
        if not evidence_refs or not verification:
            raise ValueError("confirmed repair requires evidence refs and verification")
        confidence = max(float(row["confidence"]), 0.72)
        with self.connect() as db:
            db.execute(
                "update experiences set status='confirmed', confidence=?, evidence_refs_json=?, verification=?, outcome='verified_repair', last_used_at=? where experience_id=?",
                (confidence, json.dumps(evidence_refs, ensure_ascii=False), verification, utc_now(), experience_id),
            )
        self._audit({"event": "experience_confirmed", "experience_id": experience_id})
        return self.get(experience_id)

    def _confirmation_allowed(self, doc: dict[str, Any]) -> bool:
        return bool(doc.get("verified_execution") and doc.get("test_result") == "PASS" and doc.get("evidence_refs"))

    def get(self, experience_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("select * from experiences where experience_id=?", (experience_id,)).fetchone()
        return self._decode(dict(row)) if row else {}

    def retrieve(self, query: dict[str, Any], *, top_k: int = 5) -> dict[str, Any]:
        project_type = str(query.get("project_type", ""))
        task_type = str(query.get("task_type", ""))
        stage = str(query.get("stage", ""))
        version = str(query.get("version", ""))
        symptoms = set(str(item).lower() for item in query.get("symptoms", []) if str(item).strip())
        with self.connect() as db:
            rows = [self._decode(dict(row)) for row in db.execute("select * from experiences where status='confirmed'")]
        scored: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for row in rows:
            versions = row.get("applicable_versions", [])
            if versions and version and version not in versions:
                rejected.append({"experience_id": row["experience_id"], "reason": "version_filter"})
                continue
            if row.get("project_type") not in {"", project_type}:
                rejected.append({"experience_id": row["experience_id"], "reason": "project_type_filter"})
                continue
            row_symptoms = set(str(item).lower() for item in row.get("symptoms", []))
            overlap = len(symptoms & row_symptoms)
            score = float(row.get("confidence", 0.0))
            if row.get("task_type") == task_type:
                score += 0.25
            if row.get("stage") == stage:
                score += 0.15
            score += min(0.25, overlap * 0.08)
            scored.append({"score": round(score, 4), **row})
        selected = sorted(scored, key=lambda item: item["score"], reverse=True)[: max(1, int(top_k))]
        conflicts = self.detect_conflicts(selected)
        if conflicts:
            for item in selected:
                if item["experience_id"] in conflicts["conflicted_ids"]:
                    item["status"] = "conflicted"
            selected = [item for item in selected if item.get("status") != "conflicted"]
        result = {
            "retrieved_experience_ids": [item["experience_id"] for item in scored],
            "selected_experiences": selected,
            "rejected_experiences": rejected,
            "conflicts": conflicts,
            "injection_token_estimate": sum(max(1, len(json.dumps(item, ensure_ascii=False)) // 4) for item in selected),
        }
        self._audit({"event": "experience_retrieved", "selected": [item["experience_id"] for item in selected], "rejected": rejected})
        return result

    def detect_conflicts(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_signature: dict[str, set[str]] = {}
        for row in rows:
            by_signature.setdefault(str(row.get("problem_signature", "")), set()).add(str(row.get("action", "")))
        conflicted = [sig for sig, actions in by_signature.items() if len(actions) > 1]
        ids = [row["experience_id"] for row in rows if row.get("problem_signature") in conflicted]
        if ids:
            with self.connect() as db:
                db.executemany("update experiences set status='conflicted' where experience_id=?", [(item,) for item in ids])
        return {"conflicted_signatures": conflicted, "conflicted_ids": ids}

    def update_reuse_outcome(self, experience_id: str, *, success: bool, negative_condition: str = "") -> dict[str, Any]:
        row = self.get(experience_id)
        if not row:
            raise KeyError(experience_id)
        confidence = float(row["confidence"])
        confidence = min(0.99, confidence + 0.05) if success else max(0.05, confidence - 0.20)
        negatives = list(row.get("negative_conditions", []))
        if negative_condition and negative_condition not in negatives:
            negatives.append(negative_condition)
        with self.connect() as db:
            db.execute(
                """
                update experiences
                set use_count=use_count+1,
                    success_count=success_count+?,
                    failure_count=failure_count+?,
                    confidence=?,
                    negative_conditions_json=?,
                    last_used_at=?
                where experience_id=?
                """,
                (1 if success else 0, 0 if success else 1, confidence, json.dumps(negatives, ensure_ascii=False), utc_now(), experience_id),
            )
        self._audit({"event": "experience_reuse_outcome", "experience_id": experience_id, "success": success})
        return self.get(experience_id)

    def report(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = [self._decode(dict(row)) for row in db.execute("select * from experiences")]
        return {
            "total": len(rows),
            "confirmed": len([row for row in rows if row["status"] == "confirmed"]),
            "candidate": len([row for row in rows if row["status"] == "candidate"]),
            "rejected": len([row for row in rows if row["status"] == "rejected"]),
            "conflicted": len([row for row in rows if row["status"] == "conflicted"]),
            "rows": rows,
        }

    def _decode(self, row: dict[str, Any]) -> dict[str, Any]:
        row["symptoms"] = json.loads(row.pop("symptoms_json"))
        row["evidence_refs"] = json.loads(row.pop("evidence_refs_json"))
        row["applicable_versions"] = json.loads(row.pop("applicable_versions_json"))
        row["negative_conditions"] = json.loads(row.pop("negative_conditions_json"))
        return row
