#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.artifacts import ArtifactStore, ArtifactTypeRegistry
from cgkn.compiler import ArtifactFlowCompiler
from cgkn.runtime import ArtifactInvalidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Invalidate only consumers and descendants of one artifact.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--flow", default="flow.artifact_driven_project_refactor@1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compiler = ArtifactFlowCompiler(ROOT)
    result = compiler.compile(args.flow)
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    store = ArtifactStore(pathlib.Path(args.run_dir), compiler.registry)
    report = ArtifactInvalidator(store, result["graph"]).invalidate(args.artifact, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
