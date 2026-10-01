#!/usr/bin/env python3
"""CLI adapter for the sole reviewed Codex conversation generation route."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

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
    args = parser.parse_args()
    if args.provider_mode != "live" and (args.allow_network or args.allow_provider):
        raise SystemExit("non-live Provider mode forbids network/provider transport")
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
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
