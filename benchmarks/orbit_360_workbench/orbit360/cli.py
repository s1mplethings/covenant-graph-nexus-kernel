from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .contracts import OrbitError
from .planner import DEFAULT_UNIT_COUNT, DEFAULT_WIDTH, build_plan
from .repair import repair_unit
from .runner import run_workspace, workspace_status
from .workspace import materialize


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="orbit360", description="Run the ORBIT-360 dependency and evidence workbench.")
    sub = value.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Create a new deterministic workspace")
    plan.add_argument("--workspace", required=True)
    plan.add_argument("--units", type=int, default=DEFAULT_UNIT_COUNT)
    plan.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    run = sub.add_parser("run", help="Execute or resume a workspace")
    run.add_argument("--workspace", required=True)
    run.add_argument("--workers", type=int, default=8)
    repair = sub.add_parser("repair", help="Change one unit and invalidate its downstream closure")
    repair.add_argument("--workspace", required=True)
    repair.add_argument("--target", required=True)
    repair.add_argument("--delta", type=int, default=1)
    status = sub.add_parser("status", help="Inspect valid checkpoint coverage")
    status.add_argument("--workspace", required=True)
    return value


def execute(args: argparse.Namespace) -> dict:
    workspace = pathlib.Path(args.workspace)
    if args.command == "plan":
        return materialize(build_plan(args.units, args.width), workspace)
    if args.command == "run":
        return run_workspace(workspace, args.workers)
    if args.command == "repair":
        return repair_unit(workspace, args.target, args.delta)
    return workspace_status(workspace)


def main(argv: list[str] | None = None) -> int:
    try:
        result = execute(parser().parse_args(argv))
    except OrbitError as exc:
        emit({"ok": False, "error": str(exc), "formal_evidence_status": "NOT_EVALUATED"})
        return 2
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
