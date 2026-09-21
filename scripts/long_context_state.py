#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

import context_prompt


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "long-context"
DEFAULT_FLOW_REF = "flow.modular_project_generation@1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_text(value: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_key_values(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected KEY=VALUE, got {value!r}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty key in {value!r}")
        result[key] = raw.strip()
    return result


def parse_metadata(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("--metadata-json must be a JSON object")
    return doc


def artifact_dir(run_dir: pathlib.Path) -> pathlib.Path:
    return run_dir / "artifacts"


def turns_dir(run_dir: pathlib.Path) -> pathlib.Path:
    return artifact_dir(run_dir) / "conversation_turns"


def turn_index_path(run_dir: pathlib.Path) -> pathlib.Path:
    return artifact_dir(run_dir) / "conversation_turn_index.json"


def state_path(run_dir: pathlib.Path) -> pathlib.Path:
    return artifact_dir(run_dir) / "conversation_state.json"


def ledger_path(run_dir: pathlib.Path) -> pathlib.Path:
    return artifact_dir(run_dir) / "decision_ledger.json"


def checkpoint_path(run_dir: pathlib.Path) -> pathlib.Path:
    return artifact_dir(run_dir) / "generation_checkpoint.json"


def context_pack_path(run_dir: pathlib.Path, active_module: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", active_module).strip("_") or "context"
    return artifact_dir(run_dir) / "context_packs" / f"{safe}.json"


def load_turns(run_dir: pathlib.Path) -> list[dict[str, Any]]:
    index = load_json(turn_index_path(run_dir), [])
    if not isinstance(index, list):
        raise ValueError("conversation_turn_index.json must be a list")
    turns: list[dict[str, Any]] = []
    for rel_path in index:
        path = run_dir / str(rel_path)
        if path.exists():
            turns.append(load_json(path, {}))
    return sorted(turns, key=lambda item: (str(item.get("created_at", "")), str(item.get("turn_id", ""))))


def append_turn(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = pathlib.Path(args.run_dir).resolve()
    run_id = args.run_id or run_dir.name
    existing = load_turns(run_dir)
    turn_id = args.turn_id or f"turn-{len(existing) + 1:04d}"
    turn = {
        "kind": "ConversationTurn",
        "run_id": run_id,
        "turn_id": turn_id,
        "role": args.role,
        "content": args.content,
        "content_hash": content_hash(args.content),
        "created_at": now(),
        "artifact_refs": parse_key_values(args.artifact),
        "metadata": parse_metadata(args.metadata_json),
    }
    path = turns_dir(run_dir) / f"{turn_id}.json"
    write_json(path, turn)

    index = load_json(turn_index_path(run_dir), [])
    rel = path.relative_to(run_dir).as_posix()
    if rel not in index:
        index.append(rel)
    write_json(turn_index_path(run_dir), index)
    return {"status": "pass", "turn": turn, "path": str(path)}


def unique_append(items: list[str], value: str, limit: int) -> None:
    text = compact_text(value, limit=240)
    if text and text not in items and len(items) < limit:
        items.append(text)


def sentence_candidates(content: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", content)
    return [compact_text(part, 220) for part in parts if compact_text(part, 220)]


def reduce_state(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = pathlib.Path(args.run_dir).resolve()
    run_id = args.run_id or run_dir.name
    turns = load_turns(run_dir)
    existing_state = load_json(state_path(run_dir), {})

    stable_facts = list(existing_state.get("stable_facts", [])) if isinstance(existing_state, dict) else []
    open_questions = list(existing_state.get("open_questions", [])) if isinstance(existing_state, dict) else []
    confirmed_constraints = list(existing_state.get("confirmed_constraints", [])) if isinstance(existing_state, dict) else []
    user_preferences = list(existing_state.get("user_preferences", [])) if isinstance(existing_state, dict) else []
    rejected_options = list(existing_state.get("rejected_options", [])) if isinstance(existing_state, dict) else []
    artifact_refs: dict[str, str] = {}
    if isinstance(existing_state, dict):
        artifact_refs.update(existing_state.get("artifact_refs", {}))

    latest_user = ""
    summary_rows: list[str] = []
    for turn in turns:
        role = str(turn.get("role", "agent"))
        content = str(turn.get("content", ""))
        artifact_refs.update({str(k): str(v) for k, v in turn.get("artifact_refs", {}).items()})
        if role == "user" and content.strip():
            latest_user = compact_text(content, 260)
            unique_append(stable_facts, latest_user, args.max_items)
        for sent in sentence_candidates(content):
            lowered = sent.lower()
            if "?" in sent or "？" in sent:
                unique_append(open_questions, sent, args.max_items)
            if any(token in lowered for token in ["must", "constraint", "requirement"]) or any(token in sent for token in ["必须", "约束", "要求"]):
                unique_append(confirmed_constraints, sent, args.max_items)
            if any(token in lowered for token in ["prefer", "want", "希望", "想要", "偏好"]):
                unique_append(user_preferences, sent, args.max_items)
            if any(token in lowered for token in ["reject", "skip", "不要", "不想", "否决"]):
                unique_append(rejected_options, sent, args.max_items)
        summary_rows.append(f"{role}: {compact_text(content, 180)}")

    recent_turns = turns[-args.recent_turns :]
    summary = compact_text(" | ".join(summary_rows[-args.summary_turns :]), args.summary_chars)
    state = {
        "kind": "ConversationState",
        "run_id": run_id,
        "updated_at": now(),
        "turn_count": len(turns),
        "stable_facts": stable_facts[: args.max_items],
        "open_questions": open_questions[: args.max_items],
        "confirmed_constraints": confirmed_constraints[: args.max_items],
        "user_preferences": user_preferences[: args.max_items],
        "rejected_options": rejected_options[: args.max_items],
        "current_intent": latest_user or str(existing_state.get("current_intent", "")),
        "last_action": compact_text(turns[-1]["content"], 220) if turns else str(existing_state.get("last_action", "")),
        "next_recommended_action": args.next_action or "build_context_pack",
        "recent_turns": recent_turns,
        "summary": summary,
        "artifact_refs": artifact_refs,
    }
    write_json(state_path(run_dir), state)
    ledger = update_decision_ledger(run_dir, run_id, turns)
    return {"status": "pass", "state_path": str(state_path(run_dir)), "ledger_path": str(ledger_path(run_dir)), "state": state, "decision_count": len(ledger["decisions"])}


def update_decision_ledger(run_dir: pathlib.Path, run_id: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    ledger = load_json(ledger_path(run_dir), {"kind": "DecisionLedger", "run_id": run_id, "updated_at": now(), "decisions": []})
    decisions = list(ledger.get("decisions", []))
    existing_ids = {str(item.get("id")) for item in decisions}
    for turn in turns:
        metadata = turn.get("metadata", {})
        if not isinstance(metadata, dict) or "decision" not in metadata:
            continue
        decision_id = str(metadata.get("id") or f"{turn.get('turn_id')}:decision")
        if decision_id in existing_ids:
            continue
        decisions.append(
            {
                "id": decision_id,
                "stage": str(metadata.get("stage", "conversation")),
                "decision": str(metadata.get("decision", "")),
                "rationale": str(metadata.get("rationale", "")),
                "alternatives": [str(item) for item in metadata.get("alternatives", [])],
                "created_at": str(turn.get("created_at", now())),
                "artifact_refs": {str(k): str(v) for k, v in turn.get("artifact_refs", {}).items()},
                "inputArtifactRefs": list(metadata.get("inputArtifactRefs", [])),
                "outputArtifactRefs": list(metadata.get("outputArtifactRefs", [])),
            }
        )
        existing_ids.add(decision_id)
    ledger = {"kind": "DecisionLedger", "run_id": run_id, "updated_at": now(), "decisions": decisions}
    write_json(ledger_path(run_dir), ledger)
    return ledger


def file_manifest(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = pathlib.Path(raw_path).resolve()
        row: dict[str, Any] = {"path": str(path)}
        if path.exists() and path.is_file():
            data = path.read_bytes()
            row["sha256"] = hashlib.sha256(data).hexdigest()
            row["bytes"] = len(data)
        rows.append(row)
    return rows


def commit_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = pathlib.Path(args.run_dir).resolve()
    run_id = args.run_id or run_dir.name
    existing = load_json(checkpoint_path(run_dir), {})
    checkpoint_id = args.checkpoint_id or f"checkpoint-{now().replace(':', '').replace('.', '-')}"
    artifact_refs = {}
    if isinstance(existing, dict):
        artifact_refs.update(existing.get("artifact_refs", {}))
    artifact_refs.update(parse_key_values(args.artifact))

    manifest = []
    if isinstance(existing, dict):
        manifest.extend(existing.get("file_manifest", []))
    manifest.extend(file_manifest(args.file))

    failure = None
    if args.failure_json:
        failure = json.loads(args.failure_json)

    checkpoint = {
        "kind": "GenerationCheckpoint",
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "stage": args.stage,
        "status": args.status,
        "created_at": now(),
        "completed_steps": args.completed_step,
        "pending_steps": args.pending_step,
        "artifact_refs": artifact_refs,
        "file_manifest": manifest,
        "resume_command": args.resume_command,
        "failure": failure,
    }
    write_json(checkpoint_path(run_dir), checkpoint)
    return {"status": "pass", "checkpoint_path": str(checkpoint_path(run_dir)), "checkpoint": checkpoint}


def build_context_pack(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = pathlib.Path(args.run_dir).resolve()
    run_id = args.run_id or run_dir.name
    state = load_json(state_path(run_dir), {})
    checkpoint = load_json(checkpoint_path(run_dir), {})
    if not state:
        raise ValueError("conversation_state.json does not exist; run reduce first")
    checkpoint_ref = str(checkpoint_path(run_dir)) if checkpoint else ""
    prompt_pack = context_prompt.build_state_prompt_pack(
        state,
        checkpoint if isinstance(checkpoint, dict) else {},
        active_module=args.active_module,
        flow_ref=args.flow_ref,
        purpose=args.purpose,
        max_chars=int(args.prompt_max_chars),
        recent_turns=int(args.recent_turns),
    )
    pack = {
        "kind": "ContextPack",
        "run_id": run_id,
        "created_at": now(),
        "active_module": args.active_module,
        "flow_ref": args.flow_ref,
        "conversation_state_ref": str(state_path(run_dir)),
        "checkpoint_ref": checkpoint_ref,
        "bounded_context": {
            "summary": str(state.get("summary", "")),
            "stable_facts": state.get("stable_facts", []),
            "open_questions": state.get("open_questions", []),
            "recent_turns": state.get("recent_turns", [])[-args.recent_turns :],
            "artifact_refs": state.get("artifact_refs", {}),
            "resume": checkpoint if checkpoint else {},
            "key_points": prompt_pack.get("key_points", []),
            "prompt_budget": prompt_pack.get("budget", {}),
            "prompt_quality": prompt_pack.get("quality", {}),
            "prompt_text": prompt_pack.get("prompt_text", ""),
        },
    }
    path = pathlib.Path(args.output).resolve() if args.output else context_pack_path(run_dir, args.active_module)
    write_json(path, pack)
    quality = prompt_pack.get("quality", {})
    return {"status": quality.get("status", "fail"), "context_pack_path": str(path), "prompt_quality": quality, "context_pack": pack}


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--json", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist, reduce, and resume long CGNK conversations and generations.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append-turn")
    add_common_args(p_append)
    p_append.add_argument("--role", required=True, choices=["user", "agent", "tool", "system"])
    p_append.add_argument("--content", required=True)
    p_append.add_argument("--turn-id", default="")
    p_append.add_argument("--artifact", action="append", default=[], help="Artifact ref as KEY=PATH")
    p_append.add_argument("--metadata-json", default="")
    p_append.set_defaults(func=append_turn)

    p_reduce = sub.add_parser("reduce")
    add_common_args(p_reduce)
    p_reduce.add_argument("--recent-turns", type=int, default=8)
    p_reduce.add_argument("--summary-turns", type=int, default=16)
    p_reduce.add_argument("--summary-chars", type=int, default=1800)
    p_reduce.add_argument("--max-items", type=int, default=24)
    p_reduce.add_argument("--next-action", default="")
    p_reduce.set_defaults(func=reduce_state)

    p_checkpoint = sub.add_parser("checkpoint")
    add_common_args(p_checkpoint)
    p_checkpoint.add_argument("--stage", required=True)
    p_checkpoint.add_argument("--status", default="pass", choices=["ready", "running", "pass", "fail", "blocked"])
    p_checkpoint.add_argument("--checkpoint-id", default="")
    p_checkpoint.add_argument("--completed-step", action="append", default=[])
    p_checkpoint.add_argument("--pending-step", action="append", default=[])
    p_checkpoint.add_argument("--artifact", action="append", default=[], help="Artifact ref as KEY=PATH")
    p_checkpoint.add_argument("--file", action="append", default=[], help="Generated or runtime file to hash")
    p_checkpoint.add_argument("--resume-command", default="")
    p_checkpoint.add_argument("--failure-json", default="")
    p_checkpoint.set_defaults(func=commit_checkpoint)

    p_pack = sub.add_parser("context-pack")
    add_common_args(p_pack)
    p_pack.add_argument("--active-module", required=True)
    p_pack.add_argument("--flow-ref", default=DEFAULT_FLOW_REF)
    p_pack.add_argument("--recent-turns", type=int, default=6)
    p_pack.add_argument("--purpose", default="general", choices=["project_generation", "route_planning", "general"])
    p_pack.add_argument("--prompt-max-chars", type=int, default=6000)
    p_pack.add_argument("--output", default="")
    p_pack.set_defaults(func=build_context_pack)

    args = parser.parse_args()
    result = args.func(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            if key in {"state", "checkpoint", "context_pack", "turn"}:
                continue
            print(f"{key}={value}")
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
