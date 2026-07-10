from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, append_jsonl, now, read_jsonl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, append_jsonl, now, read_jsonl


class AgentActionRecorder:
    def __init__(self, out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR) -> None:
        self.out_dir = pathlib.Path(out_dir)
        self.path = self.out_dir / "agent_actions.jsonl"
        self._count = len(read_jsonl(self.path))

    def record(
        self,
        *,
        agent_id: str,
        agent_role: str,
        stage: str,
        action: str,
        reason: str,
        input_context_id: str,
        expected_verification: list[str],
        target_files: list[str] | None = None,
        outputs: list[str] | None = None,
        claimed_complete: bool = False,
    ) -> dict[str, Any]:
        self._count += 1
        doc: dict[str, Any] = {
            "action_id": f"A{self._count:04d}",
            "agent_id": agent_id,
            "agent_role": agent_role,
            "stage": stage,
            "action": action,
            "reason": reason,
            "input_context_id": input_context_id,
            "expected_verification": list(expected_verification),
            "claimed_complete": bool(claimed_complete),
            "created_at": now(),
        }
        if target_files:
            doc["target_files"] = list(target_files)
        if outputs:
            doc["outputs"] = list(outputs)
        append_jsonl(self.path, doc)
        return doc


def validate_agent_action(action: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in ("action_id", "agent_id", "stage", "expected_verification"):
        if not action.get(key):
            missing.append(key)
    if not action.get("target_files") and not action.get("outputs"):
        missing.append("target_files_or_outputs")
    if action.get("delivery_pass") is True or action.get("claimed_complete") == "delivery_pass":
        missing.append("agent_claimed_delivery_pass")
    return missing


def validate_action_log(path: str | pathlib.Path) -> dict[str, Any]:
    actions = read_jsonl(path)
    invalid = [{"action_id": item.get("action_id", ""), "missing": validate_agent_action(item)} for item in actions]
    invalid = [item for item in invalid if item["missing"]]
    return {
        "kind": "AgentTreeActionProtocolValidation",
        "actions": len(actions),
        "invalid_actions": invalid,
        "verdict": "PASS" if actions and not invalid else "FAIL",
    }
