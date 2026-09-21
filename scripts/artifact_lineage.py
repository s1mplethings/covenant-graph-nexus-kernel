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
from cgkn.artifacts.lineage import build_lineage, render_lineage


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain an artifact's complete local lineage.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    store = ArtifactStore(pathlib.Path(args.run_dir), ArtifactTypeRegistry(ROOT))
    tree = build_lineage(store, args.artifact)
    print(json.dumps(tree, ensure_ascii=False, indent=2) if args.json else render_lineage(tree))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
