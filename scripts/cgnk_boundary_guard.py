#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "boundary_policy.yaml"

CHECK_NAMES = [
    "role_contract",
    "stage_lane",
    "artifact_boundary",
    "tool_permission",
    "provider_permission",
    "gate_dependency",
]

TOOL_ACTIONS = {
    "local_file_read": {"read_artifact"},
    "local_file_write": {"write_artifact", "modify_file", "package_project", "summarize_delivery"},
    "run_command": {"run_command"},
    "capture_screenshot": {"capture_screenshot"},
    "provider_call": {"provider_call"},
}


def load_policy_pack(config_path: pathlib.Path | str | None = None) -> dict[str, Any]:
    path = pathlib.Path(config_path) if config_path is not None else DEFAULT_POLICY_PATH
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(f"{path} is not JSON-compatible YAML and PyYAML is not installed.") from exc
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} must load to an object.")
        return loaded


def normalize_artifact_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("artifact.") and "@" in value:
        return value
    if "@" in value and not value.startswith("artifact."):
        return f"artifact.{value}"
    if value.startswith("artifact."):
        return f"{value}@1"
    if value and "/" not in value and "\\" not in value and "." not in value:
        return f"artifact.{value}@1"
    return value


def normalize_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace("\\", "/")


def normalize_intent(intent: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(intent)
    normalized.setdefault("kind", "AgentActionIntent")
    for key in ("reads", "writes"):
        normalized[key] = [normalize_artifact_ref(item) for item in normalized.get(key, [])]
    for key in ("paths_read", "paths_write"):
        normalized[key] = [normalize_path(item) for item in normalized.get(key, [])]
    normalized["tools"] = list(normalized.get("tools", []))
    normalized["provider_request"] = bool(normalized.get("provider_request", False))
    return normalized


def _new_check_result() -> dict[str, Any]:
    return {"status": "pass", "messages": []}


def _fail(message: str) -> dict[str, Any]:
    return {"status": "fail", "messages": [message]}


def _warning(message: str) -> dict[str, Any]:
    return {"status": "warning", "messages": [message]}


def _not_applicable() -> dict[str, Any]:
    return {"status": "not_applicable", "messages": []}


def _role_policy(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any] | None:
    return policy_pack.get("roles", {}).get(intent.get("role"))


def check_role_contract(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any]:
    role = intent.get("role")
    role_policy = _role_policy(intent, policy_pack)
    if role_policy is None:
        return _fail(f"Unknown role: {role}")
    action_type = intent.get("action_type")
    if action_type not in set(role_policy.get("allowed_actions", [])):
        return _fail(f"Role {role} cannot perform action_type {action_type}.")
    return _new_check_result()


def check_stage_lane(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any]:
    role = intent.get("role")
    role_policy = _role_policy(intent, policy_pack)
    if role_policy is None:
        return _fail(f"Unknown role: {role}")
    stage = intent.get("stage")
    lane = intent.get("lane")
    if stage not in set(role_policy.get("allowed_stages", [])):
        return _fail(f"Role {role} cannot act in stage {stage}.")
    if lane not in set(role_policy.get("allowed_lanes", [])):
        return _fail(f"Role {role} cannot act in lane {lane}.")
    return _new_check_result()


def _matches_any(path: str, patterns: list[str]) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def check_artifact_boundary(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any]:
    role = intent.get("role")
    role_policy = _role_policy(intent, policy_pack)
    if role_policy is None:
        return _fail(f"Unknown role: {role}")

    messages: list[str] = []
    allowed_artifacts = set(role_policy.get("can_write_artifacts", []))
    for artifact_ref in intent.get("writes", []):
        if not isinstance(artifact_ref, str) or not artifact_ref.startswith("artifact."):
            continue
        if artifact_ref not in allowed_artifacts:
            messages.append(f"Role {role} cannot write artifact {artifact_ref}.")

    denied_patterns = role_policy.get("cannot_write_paths", [])
    allowed_patterns = role_policy.get("can_write_paths", [])
    for path in intent.get("paths_write", []):
        if _matches_any(path, denied_patterns):
            messages.append(f"Role {role} cannot write forbidden path {path}.")
            continue
        if not allowed_patterns or not _matches_any(path, allowed_patterns):
            messages.append(f"Role {role} cannot write path {path}.")

    if messages:
        return {"status": "fail", "messages": messages}
    return _new_check_result()


def check_tool_permission(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any]:
    known_tools = policy_pack.get("tools", {})
    messages: list[str] = []
    action_type = intent.get("action_type")
    for tool in intent.get("tools", []):
        if tool not in known_tools:
            messages.append(f"Tool {tool} is not authorized by policy.")
            continue
        allowed_actions = TOOL_ACTIONS.get(tool)
        if allowed_actions and action_type not in allowed_actions and tool != "provider_call":
            messages.append(f"Tool {tool} is not authorized for action_type {action_type}.")
    if messages:
        return {"status": "fail", "messages": messages}
    return _new_check_result()


def check_provider_permission(intent: dict[str, Any], policy_pack: dict[str, Any]) -> dict[str, Any]:
    role = intent.get("role")
    role_policy = _role_policy(intent, policy_pack)
    if role_policy is None:
        return _fail(f"Unknown role: {role}")
    wants_provider = bool(intent.get("provider_request")) or "provider_call" in set(intent.get("tools", []))
    if not wants_provider:
        return _new_check_result()
    if not role_policy.get("provider_allowed", False):
        return _fail(f"Role {role} is not allowed to request provider execution.")
    allowed_stages = set(policy_pack.get("provider_allowed_stages", []))
    if allowed_stages and intent.get("stage") not in allowed_stages:
        return _fail(f"Stage {intent.get('stage')} is not allowed to request provider execution.")
    return _new_check_result()


def _artifact_key(ref: str) -> str:
    name = ref
    if name.startswith("artifact."):
        name = name[len("artifact.") :]
    if "@" in name:
        name = name.split("@", 1)[0]
    return name


def _collect_run_state_artifacts(run_state: Any) -> set[str]:
    artifacts: set[str] = set()
    if not isinstance(run_state, dict):
        return artifacts
    for key in ("artifacts", "available_artifacts", "completed_artifacts"):
        value = run_state.get(key)
        if isinstance(value, list):
            artifacts.update(str(normalize_artifact_ref(item)) for item in value)
        elif isinstance(value, dict):
            artifacts.update(str(normalize_artifact_ref(item)) for item, present in value.items() if present)
    return artifacts


def check_gate_dependency(
    intent: dict[str, Any],
    run_state: dict[str, Any] | None,
    policy_pack: dict[str, Any],
) -> dict[str, Any]:
    gates = policy_pack.get("gates", {})
    available = set(str(item) for item in intent.get("reads", []))
    available.update(_collect_run_state_artifacts(run_state))

    messages: list[str] = []
    applicable = False
    for artifact_ref in intent.get("writes", []):
        if not isinstance(artifact_ref, str) or not artifact_ref.startswith("artifact."):
            continue
        gate = gates.get(_artifact_key(artifact_ref))
        if gate is None:
            continue
        applicable = True
        required = [str(normalize_artifact_ref(item)) for item in gate.get("requires", [])]
        missing = [item for item in required if item not in available]
        if missing:
            messages.append(f"Missing gate dependencies for {artifact_ref}: {', '.join(missing)}.")

    if not applicable:
        return _not_applicable()
    if messages:
        return {"status": "fail", "messages": messages}
    return _new_check_result()


def _needs_rewrite(original: dict[str, Any], normalized: dict[str, Any]) -> bool:
    keys = ("reads", "writes", "paths_read", "paths_write")
    return any(original.get(key, []) != normalized.get(key, []) for key in keys)


def _decision_checks(results: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {name: results.get(name, _not_applicable())["status"] for name in CHECK_NAMES}


def _decision_messages(results: dict[str, dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for name in CHECK_NAMES:
        for message in results.get(name, {}).get("messages", []):
            messages.append(f"{name}: {message}")
    return messages


def _build_decision(
    intent: dict[str, Any],
    normalized: dict[str, Any],
    results: dict[str, dict[str, Any]],
    rewrite: bool,
) -> dict[str, Any]:
    checks = _decision_checks(results)
    messages = _decision_messages(results)
    if any(status == "fail" for status in checks.values()):
        status = "block"
        reason = "Boundary Guard blocked the action intent because one or more boundary checks failed."
        suggested_rewrite = None
    elif rewrite:
        status = "rewrite"
        reason = "Boundary Guard rewrote safe local aliases to canonical refs before execution."
        suggested_rewrite = normalized
    else:
        status = "allow"
        reason = "Boundary Guard allowed the action intent; all applicable checks passed."
        suggested_rewrite = None

    return {
        "kind": "BoundaryDecision",
        "status": status,
        "reason": reason,
        "agent_id": normalized.get("agent_id", intent.get("agent_id")),
        "checks": checks,
        "messages": messages,
        "suggested_rewrite": suggested_rewrite,
        "requires_approval_from": None,
    }


def decide(
    intent: dict[str, Any],
    run_state: dict[str, Any] | None = None,
    policy_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy_pack if policy_pack is not None else load_policy_pack()
    normalized = normalize_intent(intent)
    results = {
        "role_contract": check_role_contract(normalized, policy),
        "stage_lane": check_stage_lane(normalized, policy),
        "artifact_boundary": check_artifact_boundary(normalized, policy),
        "tool_permission": check_tool_permission(normalized, policy),
        "provider_permission": check_provider_permission(normalized, policy),
        "gate_dependency": check_gate_dependency(normalized, run_state, policy),
    }
    return _build_decision(intent, normalized, results, _needs_rewrite(intent, normalized))


def append_ledger(decision: dict[str, Any], ledger_path: pathlib.Path | str | None = None) -> None:
    if ledger_path is None:
        raise ValueError("ledger_path is required.")
    path = pathlib.Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


class BoundaryGuard:
    def __init__(
        self,
        config_path: pathlib.Path | str | None = None,
        ledger_path: pathlib.Path | str | None = None,
    ) -> None:
        self.config_path = pathlib.Path(config_path) if config_path is not None else DEFAULT_POLICY_PATH
        self.policy_pack = load_policy_pack(self.config_path)
        self.ledger_path = pathlib.Path(ledger_path) if ledger_path is not None else None

    def decide(self, intent: dict[str, Any], run_state: dict[str, Any] | None = None) -> dict[str, Any]:
        decision = decide(intent, run_state=run_state, policy_pack=self.policy_pack)
        if self.ledger_path is not None:
            self.append_ledger(decision)
        return decision

    def append_ledger(self, decision: dict[str, Any]) -> None:
        append_ledger(decision, self.ledger_path)


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_intent_case(path: pathlib.Path, case_name: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = _load_json(path)
    if case_name is not None:
        if not isinstance(payload, dict) or "cases" not in payload:
            raise ValueError("--case requires an intent file with a top-level cases object.")
        case_payload = payload["cases"].get(case_name)
        if case_payload is None:
            raise ValueError(f"Unknown intent case: {case_name}")
    else:
        case_payload = payload

    if isinstance(case_payload, dict) and "intent" in case_payload:
        return case_payload["intent"], case_payload.get("run_state")
    if isinstance(case_payload, dict):
        return case_payload, None
    raise ValueError("Intent case must be a JSON object.")


def print_human_decision(decision: dict[str, Any]) -> None:
    print(f"Boundary Guard decision: {decision['status']}")
    print(f"Agent: {decision.get('agent_id')}")
    print(f"Reason: {decision['reason']}")
    print("Checks:")
    for name, status in decision.get("checks", {}).items():
        print(f"  - {name}: {status}")
    if decision.get("messages"):
        print("Messages:")
        for message in decision["messages"]:
            print(f"  - {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local pre-action Agent Boundary Guard sidecar.")
    parser.add_argument("--intent", type=pathlib.Path, required=True, help="AgentActionIntent JSON file.")
    parser.add_argument("--case", help="Case key to load from a sample intent file.")
    parser.add_argument("--policy", type=pathlib.Path, default=DEFAULT_POLICY_PATH, help="Boundary policy path.")
    parser.add_argument("--ledger", type=pathlib.Path, help="Optional JSONL decision ledger path.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    intent, run_state = _load_intent_case(args.intent, args.case)
    guard = BoundaryGuard(config_path=args.policy, ledger_path=args.ledger)
    decision = guard.decide(intent, run_state=run_state)
    if args.json:
        print(json.dumps(decision, ensure_ascii=False, indent=2))
    else:
        print_human_decision(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
