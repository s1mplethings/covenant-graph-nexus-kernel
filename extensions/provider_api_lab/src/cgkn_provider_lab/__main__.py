from __future__ import annotations

import argparse
import json
from pathlib import Path

from .storage import ProviderConfigStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CGKN Provider API Lab")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("gui", help="launch the local Tk GUI")
    list_parser = subcommands.add_parser("list", help="print metadata-only provider configuration")
    list_parser.add_argument("--config", type=Path, default=None)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command in {None, "gui"}:
        from .gui import run_gui

        run_gui()
        return 0
    if args.command == "list":
        store = ProviderConfigStore(args.config)
        print(json.dumps([item.public_dict() for item in store.load()], ensure_ascii=False, indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
