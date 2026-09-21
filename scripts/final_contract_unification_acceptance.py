from __future__ import annotations

"""Deprecated CLI compatibility facade for formal mainline acceptance.

This module does not consume ``final_internal_acceptance.py`` output and does
not produce evidence itself. New callers should use
``scripts/formal_mainline_acceptance.py`` directly.
"""

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import formal_mainline_acceptance

PRODUCER = "scripts/formal_mainline_acceptance.py"
DEFAULT_FULL_ALL_RESULT = (
    ROOT
    / "generated"
    / "dynamic_agent_tree_fix_eval"
    / "test_profiles"
    / "full_all_result.json"
)


def build_acceptance(
    run_dir: str | pathlib.Path,
    *,
    candidate_dir: str | pathlib.Path | None = None,
    production_run_dir: str | pathlib.Path | None = None,
    test_conversation_id: str = "",
    full_all_result: str | pathlib.Path = DEFAULT_FULL_ALL_RESULT,
) -> dict[str, Any]:
    return formal_mainline_acceptance.build_acceptance(
        run_dir,
        candidate_dir=candidate_dir,
        production_run_dir=production_run_dir,
        full_all_result=full_all_result,
        codex_test_conversation_id=test_conversation_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--candidate-dir", default="")
    parser.add_argument("--production-run-dir", default="")
    parser.add_argument("--codex-test-conversation-id", default="")
    parser.add_argument("--full-all-result", default=str(DEFAULT_FULL_ALL_RESULT))
    args = parser.parse_args()
    result = build_acceptance(
        args.run_dir,
        candidate_dir=args.candidate_dir or None,
        production_run_dir=args.production_run_dir or None,
        test_conversation_id=args.codex_test_conversation_id,
        full_all_result=args.full_all_result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["inspection"] in {
        "PASS",
        "NEEDS_REWORK",
        "NOT_EVALUATED",
        "BLOCKED",
        "BLOCKED_PROVIDER",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
