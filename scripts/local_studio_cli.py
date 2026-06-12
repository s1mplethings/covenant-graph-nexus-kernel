#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

try:
    from . import local_conversation_manager
    from . import local_repo_manager
    from .main_agent_manager import MainAgentManager
except ImportError:  # pragma: no cover - script execution path
    import local_conversation_manager  # type: ignore
    import local_repo_manager  # type: ignore
    from main_agent_manager import MainAgentManager  # type: ignore


def print_json(doc: dict[str, Any] | list[Any]) -> None:
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def list_conversations() -> list[dict[str, Any]]:
    root = local_conversation_manager.conversation_root()
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for path in sorted(root.glob("*/conversation.json")):
        conversation = local_conversation_manager.load_conversation(path.parent.name)
        out.append(local_conversation_manager.conversation_summary(conversation))
    return out


def list_projects() -> list[dict[str, Any]]:
    root = local_repo_manager.managed_projects_root()
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for path in sorted(root.glob("*/project.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def rollback_project_payload(project_id: str, revision_index: int) -> dict[str, Any]:
    metadata = local_repo_manager.rollback_to_revision(project_id, revision_index)
    return {
        "status": "rolled_back",
        "project_id": project_id,
        "revision_index": int(metadata.get("current_revision", revision_index)),
        "current_worktree": str(metadata.get("current_worktree", "")),
        "conversation_sync": "not_applied",
        "note": "Use conversation-level rollback in Phase 2 to update active_project.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Studio control surface for CGNK conversations and managed projects.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-conversations")
    show_conv = sub.add_parser("show-conversation")
    show_conv.add_argument("conversation_id")
    new_project = sub.add_parser("new-project")
    new_project.add_argument("conversation_id")
    new_project.add_argument("text")
    revise = sub.add_parser("revise")
    revise.add_argument("conversation_id")
    revise.add_argument("text")
    status = sub.add_parser("status")
    status.add_argument("conversation_id")
    sub.add_parser("list-projects")
    show_project = sub.add_parser("show-project")
    show_project.add_argument("project_id")
    list_revisions = sub.add_parser("list-revisions")
    list_revisions.add_argument("project_id")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("project_id")
    rollback.add_argument("--rev", type=int, required=True)
    redeliver = sub.add_parser("redeliver")
    redeliver.add_argument("conversation_id")

    args = parser.parse_args(argv)
    manager = MainAgentManager()
    if args.command == "list-conversations":
        print_json(list_conversations())
    elif args.command == "show-conversation":
        print_json(local_conversation_manager.load_conversation(args.conversation_id))
    elif args.command == "new-project":
        print_json(manager.handle_user_turn(args.conversation_id, args.text, source="local_cli"))
    elif args.command == "revise":
        print_json(manager.handle_user_turn(args.conversation_id, args.text, source="local_cli"))
    elif args.command == "status":
        conversation = local_conversation_manager.load_conversation(args.conversation_id)
        print_json(manager.get_status(conversation))
    elif args.command == "list-projects":
        print_json(list_projects())
    elif args.command == "show-project":
        print_json(local_repo_manager.load_project_metadata(args.project_id))
    elif args.command == "list-revisions":
        metadata = local_repo_manager.load_project_metadata(args.project_id)
        print_json(metadata.get("revisions", []) if isinstance(metadata.get("revisions"), list) else [])
    elif args.command == "rollback":
        print_json(rollback_project_payload(args.project_id, args.rev))
    elif args.command == "redeliver":
        conversation = local_conversation_manager.load_conversation(args.conversation_id)
        active = local_conversation_manager.get_active_project(conversation)
        print_json({"status": "recorded", "intent": "redeliver_request", "active_project": active})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
