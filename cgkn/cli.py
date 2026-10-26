"""Public CGNK command line surface."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from cgkn.application.project_corpus import ProjectCorpus


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _corpus(args: argparse.Namespace) -> int:
    corpus = ProjectCorpus(args.root)
    command = args.corpus_command
    if command == "init":
        result = corpus.initialize()
    elif command == "stats":
        result = corpus.stats()
    elif command == "list":
        result = {"items": corpus.list_attempts(limit=args.limit)}
    elif command == "show":
        result = corpus.show(args.entry_id)
    elif command == "search":
        result = {
            "items": corpus.search(
                text=args.text,
                family_id=args.family,
                status=args.status,
                split=args.split,
                project_type=args.project_type,
                complexity=args.complexity,
                provider=args.provider,
                model=args.model,
            )
        }
    elif command == "family":
        result = {"items": corpus.search(family_id=args.family_id)}
    elif command == "failures":
        result = {"items": corpus.search(status="FAIL", family_id=args.family)}
    elif command == "verify":
        result = corpus.verify()
    elif command == "recover":
        result = corpus.recover_staging()
    elif command == "rebuild-catalog":
        result = corpus.rebuild_catalog()
    elif command == "reconstruct":
        result = corpus.reconstruct(args.snapshot_id, args.output)
    elif command == "export":
        result = corpus.export_family(args.family_id, args.output)
    elif command == "import":
        result = corpus.import_bundle(args.archive)
    elif command == "benchmark-sample":
        result = corpus.benchmark_sample(
            count=args.count,
            seed=args.seed,
            split=args.split,
            project_type=args.project_type,
            complexity=args.complexity,
            status=args.status,
        )
        if args.output:
            output = pathlib.Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    else:  # pragma: no cover - argparse prevents this
        raise ValueError(f"unknown corpus command: {command}")
    _print(result)
    return 0 if result.get("status", "PASS") not in {"FAIL", "SPLIT_LEAKAGE"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cgkn", description="CGNK project utilities")
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("corpus", help="Manage the local Project Corpus")
    corpus.add_argument("--root", help="Corpus root; defaults to CGNK_PROJECT_CORPUS_ROOT")
    sub = corpus.add_subparsers(dest="corpus_command", required=True)

    sub.add_parser("init")
    sub.add_parser("stats")
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    show = sub.add_parser("show")
    show.add_argument("entry_id")
    search = sub.add_parser("search")
    search.add_argument("--text")
    search.add_argument("--family")
    search.add_argument("--status")
    search.add_argument("--split")
    search.add_argument("--project-type")
    search.add_argument("--complexity")
    search.add_argument("--provider")
    search.add_argument("--model")
    family = sub.add_parser("family")
    family.add_argument("family_id")
    failures = sub.add_parser("failures")
    failures.add_argument("--family")
    sub.add_parser("verify")
    sub.add_parser("recover")
    sub.add_parser("rebuild-catalog")
    reconstruct = sub.add_parser("reconstruct")
    reconstruct.add_argument("snapshot_id")
    reconstruct.add_argument("output")
    export = sub.add_parser("export")
    export.add_argument("family_id")
    export.add_argument("output")
    importing = sub.add_parser("import")
    importing.add_argument("archive")
    sample = sub.add_parser("benchmark-sample")
    sample.add_argument("--split", default="DEVELOPMENT")
    sample.add_argument("--project-type")
    sample.add_argument("--complexity")
    sample.add_argument("--status")
    sample.add_argument("--count", type=int, required=True)
    sample.add_argument("--seed", type=int, default=5901)
    sample.add_argument("--output")
    corpus.set_defaults(func=_corpus)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _print({"status": "FAIL", "error_type": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
