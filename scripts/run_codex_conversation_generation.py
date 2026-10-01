#!/usr/bin/env python3
"""CLI adapter for the sole reviewed Codex conversation generation route."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from . import codex_conversation
except ImportError:  # pragma: no cover
    import codex_conversation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--provider-mode", choices=("live", "codex_surrogate", "deterministic_replay"), default="live")
    parser.add_argument("--replay-dir", default="")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--codex-capability-brief", default="")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--use-api", action="store_true")
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--generation-job-state", default="")
    parser.add_argument("--generation-job-id", default="")
    args = parser.parse_args()
    if args.provider_mode != "live" and (args.allow_network or args.allow_provider):
        raise SystemExit("non-live Provider mode forbids network/provider transport")
    state_path = pathlib.Path(args.generation_job_state).resolve() if args.generation_job_state else None

    def write_job(update: dict) -> None:
        if state_path is None:
            return
        current = {}
        if state_path.is_file():
            try:
                current = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
        value = {
            **current,
            **update,
            "kind": "CGKNGenerationJob",
            "schema_version": "1.0",
            "job_id": args.generation_job_id or current.get("job_id", ""),
            "process_id": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False, dir=state_path.parent, prefix=f".{state_path.name}.", suffix=".tmp")
        temp_path = pathlib.Path(handle.name)
        try:
            with handle:
                handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            temp_path.replace(state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def started(generation: dict) -> None:
        write_job({
            "state": "RUNNING",
            "run_id": str(generation.get("run_id", "")),
            "run_dir": str(generation.get("provider_run_dir", "")),
            "source_commit_sha": str(generation.get("commit_sha", "")),
            "started_at": str(generation.get("started_at", "")),
            "terminal_reason": "",
        })

    try:
        result = codex_conversation.run_formal_generation_once(
            pathlib.Path(args.project_root),
            goal=args.goal,
            provider_mode=args.provider_mode,
            model=args.model,
            timeout=args.timeout,
            replay_dir=pathlib.Path(args.replay_dir) if args.replay_dir else None,
            result_path=pathlib.Path(args.result),
            codex_capability_brief=(
                pathlib.Path(args.codex_capability_brief)
                if args.codex_capability_brief
                else None
            ),
            on_started=started if state_path is not None else None,
        )
    except BaseException as exc:
        write_job({"state": "FAILED", "terminal_reason": type(exc).__name__, "error": str(exc)[:1000]})
        raise
    status = str(result.get("status", "FAILED") or "FAILED").upper()
    terminal_state = "COMPLETE" if status in {"PASS", "PASS_WITH_LIMITS", "DELIVERED", "DELIVERED_WITH_WARNINGS"} else status
    write_job({
        "state": terminal_state,
        "run_id": str(result.get("run_id", "")),
        "run_dir": str(result.get("run_dir", "")),
        "terminal_reason": "" if terminal_state == "COMPLETE" else status,
        "formal_evidence_status": str(result.get("formal_evidence_status", "NOT_EVALUATED")),
        "candidate_present": bool(result.get("candidate_hash")),
        "resume_safe": bool((result.get("resume", {}) or {}).get("safe", False)),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
