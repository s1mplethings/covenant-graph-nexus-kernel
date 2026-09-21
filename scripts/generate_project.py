#!/usr/bin/env python3
from __future__ import annotations

"""LEGACY CLI ONLY. Not used by Codex conversation formal generation."""

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
LEGACY_DIR = ROOT / "legacy"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

import generate_project_legacy as _legacy


compose_local_pipeline = _legacy.compose_local_pipeline
context_prompt = _legacy.context_prompt
local_intent_router = _legacy.local_intent_router
requirement_blueprint = _legacy.requirement_blueprint
run_local_pipeline = _legacy.run_local_pipeline
run_product_studio = _legacy.run_product_studio
build_enriched_goal = _legacy.build_enriched_goal
DEFAULT_RESULT = _legacy.DEFAULT_RESULT


def run_generation(args):
    _legacy.build_enriched_goal = build_enriched_goal
    return _legacy.run_generation(args)


def main(argv=None):
    _legacy.build_enriched_goal = build_enriched_goal
    if argv is None:
        return _legacy.main()
    original_argv = sys.argv
    try:
        sys.argv = [original_argv[0], *argv]
        return _legacy.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    print("WARNING: LEGACY CLI ONLY. Not used by Codex conversation formal generation.", file=sys.stderr)
    raise SystemExit(main())
