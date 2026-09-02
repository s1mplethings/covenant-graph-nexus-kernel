from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__
from .core import (
    AgentKitError, codex_draft, doctor, generation_command, initialize_project,
    load_project, prepare_request, resolve_cgkn_root, run_generation, seal_draft,
)


CATEGORIES = (
    "environment_blocker", "generation_failure", "integration_failure",
    "planning_gap", "research_gap", "test_failure", "tool_gap",
)


def _project(value: str) -> pathlib.Path:
    return pathlib.Path(value or ".").resolve()


def _emit(value: dict, *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cgkn-agent", description="Use Agent-assisted CGKN from any local project.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize support state in a project")
    init.add_argument("--project", default=".")
    init.add_argument("--cgkn-root", default="")
    init.add_argument("--force", action="store_true")

    check = sub.add_parser("doctor", help="Check CGKN, Provider mainline, and optional Codex CLI")
    check.add_argument("--project", default=".")
    check.add_argument("--codex-command", default="")

    prepare = sub.add_parser("prepare", help="Build a bounded, redacted Agent request")
    prepare.add_argument("--project", default=".")
    prepare.add_argument("--goal", required=True)
    prepare.add_argument("--gap", required=True)
    prepare.add_argument("--category", choices=CATEGORIES, default="planning_gap")

    seal = sub.add_parser("seal", help="Validate a manual Agent draft and produce a sealed brief")
    seal.add_argument("--project", default=".")
    seal.add_argument("--request", default="")
    seal.add_argument("--draft", required=True)

    assist = sub.add_parser("assist", help="Prepare, run Codex read-only, and seal its advisory brief")
    assist.add_argument("--project", default=".")
    assist.add_argument("--goal", required=True)
    assist.add_argument("--gap", required=True)
    assist.add_argument("--category", choices=CATEGORIES, default="planning_gap")
    assist.add_argument("--codex-command", default="")
    assist.add_argument("--timeout", type=int, default=600)

    generate = sub.add_parser("generate", help="Invoke the existing reviewed CGKN Provider route")
    generate.add_argument("--project", default=".")
    generate.add_argument("--goal", required=True)
    generate.add_argument("--brief", default="")
    generate.add_argument("--out-dir", default="")
    generate.add_argument("--model", default="gpt-4.1")
    generate.add_argument("--allow-network", action="store_true", help="Allow existing CGKN online research inputs")
    generate.add_argument("--timeout", type=int, default=1800)
    generate.add_argument("--dry-run", action="store_true")
    return parser


def execute(args: argparse.Namespace) -> dict:
    root = _project(getattr(args, "project", "."))
    if args.command == "init":
        config = initialize_project(root, resolve_cgkn_root(args.cgkn_root), force=args.force)
        return {"ok": True, "command": "init", "config": str(root / ".cgkn" / "agent-kit.json"), "project": config}
    if args.command == "doctor":
        return {"ok": True, "command": "doctor", "report": doctor(root, codex_command=args.codex_command)}
    if args.command == "prepare":
        request = prepare_request(root, goal=args.goal, gap=args.gap, category=args.category)
        return {"ok": True, "command": "prepare", "request": str(request)}
    if args.command == "seal":
        project_root, config, _ = load_project(root)
        request = pathlib.Path(args.request) if args.request else project_root / str(config["artifact_dir"]) / "codex_request.json"
        brief = seal_draft(root, request, pathlib.Path(args.draft))
        return {"ok": True, "command": "seal", "brief": str(brief)}
    if args.command == "assist":
        request = prepare_request(root, goal=args.goal, gap=args.gap, category=args.category)
        draft = codex_draft(root, request, codex_command=args.codex_command, timeout=args.timeout)
        brief = seal_draft(root, request, draft)
        return {"ok": True, "command": "assist", "request": str(request), "draft": str(draft), "brief": str(brief)}
    project_root, config, cgkn_root = load_project(root)
    brief = pathlib.Path(args.brief) if args.brief else project_root / str(config["artifact_dir"]) / "codex_capability_brief.json"
    argv = generation_command(
        root, goal=args.goal, brief_path=brief,
        out_dir=pathlib.Path(args.out_dir) if args.out_dir else None,
        model=args.model, allow_network=args.allow_network,
    )
    if args.dry_run:
        return {"ok": True, "command": "generate", "executed": False, "argv": argv, "secrets_in_argv": False}
    completed = run_generation(argv, cgkn_root=cgkn_root, timeout=args.timeout)
    return {"ok": True, "command": "generate", "executed": True, "stdout": completed.stdout.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        result = execute(parser.parse_args(argv))
    except AgentKitError as exc:
        _emit({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
