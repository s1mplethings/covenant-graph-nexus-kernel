from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any


ALLOWED_CONNECTION_TYPES = {
    "dependency_handoff",
    "interface_question",
    "schema_negotiation",
    "blocker_assistance",
    "test_fixture_request",
    "review_request",
    "implementation_hint",
    "artifact_reference",
    "status_signal",
}

FORBIDDEN_SUMMARY_MARKERS = (
    "complete this whole task",
    "entire project history",
    "full unrelated repository",
    "modify your workspace",
    "approve delivery",
    "change ownership",
)

CONNECTION_STATUSES = {"requested", "approved", "active", "answered", "expired", "rejected", "escalated", "closed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: pathlib.Path, doc: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    return doc


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


class LeafCollaborationGraph:
    def __init__(self, path: str | pathlib.Path, *, run_id: str, same_branch_limit: int = 3, cross_branch_limit: int = 1, active_limit: int = 4) -> None:
        self.path = pathlib.Path(path)
        self.messages_path = self.path.with_name("leaf_messages.jsonl")
        self.run_id = run_id
        self.same_branch_limit = same_branch_limit
        self.cross_branch_limit = cross_branch_limit
        self.active_limit = active_limit

    def rows(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path)

    def messages(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.messages_path)

    def request_connection(
        self,
        *,
        source_leaf: str,
        target_leaf: str,
        source_branch: str,
        target_branch: str,
        connection_type: str,
        reason: str,
        requested_information: str,
        allowed_context: list[str] | None = None,
        forbidden_context: list[str] | None = None,
        authority: str = "leaf_advisory",
        max_messages: int = 6,
        token_budget: int = 4800,
        api_budget: int = 0,
        opened_by: str = "leaf",
        approved_by: str = "",
        expires_minutes: int = 30,
    ) -> dict[str, Any]:
        if connection_type not in ALLOWED_CONNECTION_TYPES:
            return self._record_rejected(
                source_leaf=source_leaf,
                target_leaf=target_leaf,
                source_branch=source_branch,
                target_branch=target_branch,
                connection_type=connection_type,
                reason="unsupported_connection_type",
            )
        duplicate = self._duplicate_question(source_leaf, target_leaf, connection_type, requested_information)
        if duplicate:
            return self._record_rejected(
                source_leaf=source_leaf,
                target_leaf=target_leaf,
                source_branch=source_branch,
                target_branch=target_branch,
                connection_type=connection_type,
                reason="duplicate_question",
            )
        active = [row for row in self.rows() if row.get("status") in {"approved", "active"}]
        if len(active) >= self.active_limit:
            return self._record_rejected(
                source_leaf=source_leaf,
                target_leaf=target_leaf,
                source_branch=source_branch,
                target_branch=target_branch,
                connection_type=connection_type,
                reason="active_connection_limit",
            )
        same_branch = source_branch == target_branch
        degree = len(
            [
                row
                for row in active
                if source_leaf in {row.get("source_leaf"), row.get("target_leaf")}
                and ((row.get("source_branch") == row.get("target_branch")) if same_branch else (row.get("source_branch") != row.get("target_branch")))
            ]
        )
        if same_branch and degree >= self.same_branch_limit:
            return self._record_rejected(
                source_leaf=source_leaf,
                target_leaf=target_leaf,
                source_branch=source_branch,
                target_branch=target_branch,
                connection_type=connection_type,
                reason="same_branch_degree_limit",
            )
        if not same_branch and degree >= self.cross_branch_limit and not approved_by:
            return self._record_rejected(
                source_leaf=source_leaf,
                target_leaf=target_leaf,
                source_branch=source_branch,
                target_branch=target_branch,
                connection_type=connection_type,
                reason="cross_branch_requires_l2_approval",
            )
        status = "approved" if approved_by or same_branch else "requested"
        contract = {
            "connection_id": stable_id(
                "conn",
                {
                    "run_id": self.run_id,
                    "source": source_leaf,
                    "target": target_leaf,
                    "type": connection_type,
                    "requested_information": requested_information,
                },
            ),
            "run_id": self.run_id,
            "source_leaf": source_leaf,
            "target_leaf": target_leaf,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "connection_type": connection_type,
            "reason": reason,
            "requested_information": requested_information,
            "allowed_context": list(allowed_context or []),
            "forbidden_context": list(forbidden_context or []),
            "authority": authority,
            "max_messages": min(max(1, int(max_messages)), 6),
            "token_budget": min(max(1, int(token_budget)), 4800),
            "API_budget": max(0, int(api_budget)),
            "opened_by": opened_by,
            "approved_by": approved_by,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=max(1, expires_minutes))).isoformat(),
            "status": status,
            "created_at": utc_now(),
        }
        return _append_jsonl(self.path, contract)

    def _record_rejected(self, **doc: Any) -> dict[str, Any]:
        row = {
            "connection_id": stable_id("conn_rejected", {"run_id": self.run_id, **doc, "created_at": utc_now()}),
            "run_id": self.run_id,
            "requested_information": "",
            "allowed_context": [],
            "forbidden_context": [],
            "authority": "none",
            "max_messages": 0,
            "token_budget": 0,
            "API_budget": 0,
            "opened_by": doc.get("source_leaf", ""),
            "approved_by": "",
            "expires_at": utc_now(),
            "status": "rejected",
            "created_at": utc_now(),
            **doc,
        }
        return _append_jsonl(self.path, row)

    def _duplicate_question(self, source_leaf: str, target_leaf: str, connection_type: str, requested_information: str) -> bool:
        normalized = " ".join(str(requested_information).lower().split())
        for row in self.rows():
            if row.get("status") == "rejected":
                continue
            if row.get("source_leaf") == source_leaf and row.get("target_leaf") == target_leaf and row.get("connection_type") == connection_type:
                if " ".join(str(row.get("requested_information", "")).lower().split()) == normalized:
                    return True
        return False

    def append_message(
        self,
        *,
        connection_id: str,
        sender: str,
        receiver: str,
        message_type: str,
        summary: str,
        artifact_refs: list[str] | None = None,
        interface_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        request_id: str = "",
        response_to: str = "",
        token_estimate: int = 0,
    ) -> dict[str, Any]:
        connection = next((row for row in self.rows() if row.get("connection_id") == connection_id), None)
        if not connection or connection.get("status") not in {"approved", "active", "requested"}:
            raise ValueError("connection is not active")
        existing = [row for row in self.messages() if row.get("connection_id") == connection_id]
        if len(existing) >= int(connection.get("max_messages", 0)):
            raise ValueError("connection message limit exceeded")
        total_tokens = sum(int(row.get("token_estimate", 0) or 0) for row in existing) + int(token_estimate or 0)
        if total_tokens > int(connection.get("token_budget", 0)):
            raise ValueError("connection token budget exceeded")
        lowered = str(summary).lower()
        if any(marker in lowered for marker in FORBIDDEN_SUMMARY_MARKERS):
            raise PermissionError("peer message attempts forbidden scope")
        message = {
            "message_id": stable_id("msg", {"connection_id": connection_id, "sender": sender, "receiver": receiver, "summary": summary, "created_at": utc_now()}),
            "connection_id": connection_id,
            "sender": sender,
            "receiver": receiver,
            "message_type": message_type,
            "summary": str(summary)[:3000],
            "artifact_refs": list(artifact_refs or []),
            "interface_refs": list(interface_refs or []),
            "evidence_refs": list(evidence_refs or []),
            "request_id": request_id,
            "response_to": response_to,
            "token_estimate": int(token_estimate or 0),
            "created_at": utc_now(),
        }
        return _append_jsonl(self.messages_path, message)

    def detect_circular_waiting(self) -> dict[str, Any]:
        waiting_edges = set()
        for message in self.messages():
            if message.get("message_type") == "status_signal" and "waiting" in str(message.get("summary", "")).lower():
                waiting_edges.add((message.get("sender"), message.get("receiver")))
        cycles = sorted([[a, b] for a, b in waiting_edges if (b, a) in waiting_edges and a and b])
        return {"status": "NEEDS_REWORK" if cycles else "PASS", "cycles": cycles}

    def connection_health(self) -> dict[str, Any]:
        rows = self.rows()
        messages = self.messages()
        active = [row for row in rows if row.get("status") in {"approved", "active", "requested"}]
        central: dict[str, int] = {}
        for row in active:
            central[str(row.get("source_leaf", ""))] = central.get(str(row.get("source_leaf", "")), 0) + 1
            central[str(row.get("target_leaf", ""))] = central.get(str(row.get("target_leaf", "")), 0) + 1
        bottlenecks = [leaf for leaf, count in central.items() if leaf and count > self.active_limit]
        circular = self.detect_circular_waiting()
        no_new_info = [
            row["connection_id"]
            for row in rows
            if len({msg.get("summary") for msg in messages if msg.get("connection_id") == row.get("connection_id")}) == 1
            and len([msg for msg in messages if msg.get("connection_id") == row.get("connection_id")]) >= 3
        ]
        problems = bool(bottlenecks or circular["cycles"] or no_new_info)
        return {
            "status": "NEEDS_REWORK" if problems else "PASS",
            "active_count": len(active),
            "bottlenecks": bottlenecks,
            "circular_waiting": circular["cycles"],
            "no_new_information_connections": no_new_info,
        }
