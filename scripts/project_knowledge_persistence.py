from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cgnk_knowledge import (  # noqa: E402
    SegmentedKnowledgeStore,
    detect_persistence_format,
    load_project_knowledge,
    migrate_legacy_pack,
    project_knowledge_semantic_hash,
)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and maintain ProjectKnowledgePack persistence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("path")

    verify = subparsers.add_parser("verify")
    verify.add_argument("path")

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("source")
    migrate.add_argument("target")

    checkpoint = subparsers.add_parser("checkpoint")
    checkpoint.add_argument("path")

    compact = subparsers.add_parser("compact")
    compact.add_argument("path")
    compact.add_argument("--max-segments", type=int)

    args = parser.parse_args(argv)
    if args.command == "inspect":
        persistence_format = detect_persistence_format(args.path)
        pack = load_project_knowledge(args.path)
        value = {
            "kind": "ProjectKnowledgePersistenceInspection",
            "format": persistence_format,
            "path": str(pathlib.Path(args.path).resolve()),
            "pack_id": pack.get("id"),
            "knowledge_revision": pack.get("knowledge_revision"),
            "item_count": len(pack.get("all_items", ())),
            "semantic_hash": project_knowledge_semantic_hash(pack),
            "load_receipt": getattr(pack, "_load_receipt", {}),
        }
    elif args.command == "verify":
        if detect_persistence_format(args.path) != "2":
            raise SystemExit("verify requires a v2 segmented store")
        value = SegmentedKnowledgeStore(args.path).verify()
    elif args.command == "migrate":
        value = migrate_legacy_pack(args.source, args.target)
    elif args.command == "checkpoint":
        value = SegmentedKnowledgeStore(args.path).create_checkpoint()
    else:
        value = SegmentedKnowledgeStore(args.path).compact(max_segments=args.max_segments)
    _print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
