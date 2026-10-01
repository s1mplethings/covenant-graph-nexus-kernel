#!/usr/bin/env python3
"""Refresh a local Codex plugin through the supported CLI and verify package identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from typing import Callable, Sequence


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
IGNORED_PARTS = {"__pycache__", ".pytest_cache"}


def package_digest(root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if IGNORED_PARTS.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def plugin_version(root: pathlib.Path) -> str:
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    value = manifest.get("version")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("PLUGIN_VERSION_MISSING")
    return value.strip()


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)


def refresh(*, source: pathlib.Path, cache_root: pathlib.Path, codex: pathlib.Path,
            selector: str = "cgkn@personal", runner: Runner = default_runner) -> dict[str, object]:
    source = source.resolve()
    version = plugin_version(source)
    source_digest = package_digest(source)
    installed = cache_root / "personal" / "cgkn" / version
    prior_digest = package_digest(installed) if installed.is_dir() else None
    if prior_digest == source_digest:
        return {"ok": True, "changed": False, "version": version, "source_digest": source_digest,
                "installed_digest": prior_digest, "installed_root": str(installed)}

    remove = runner([str(codex), "plugin", "remove", selector])
    if remove.returncode != 0 and "not installed" not in (remove.stdout + remove.stderr).lower():
        raise RuntimeError("PLUGIN_REMOVE_FAILED: " + (remove.stderr or remove.stdout).strip())
    add = runner([str(codex), "plugin", "add", selector, "--json"])
    if add.returncode != 0:
        raise RuntimeError("PLUGIN_ADD_FAILED: " + (add.stderr or add.stdout).strip())
    if not installed.is_dir():
        raise RuntimeError("PLUGIN_CACHE_NOT_MATERIALIZED")
    installed_digest = package_digest(installed)
    if installed_digest != source_digest:
        raise RuntimeError("PLUGIN_INSTALLED_IDENTITY_MISMATCH")
    return {"ok": True, "changed": True, "version": version, "source_digest": source_digest,
            "installed_digest": installed_digest, "installed_root": str(installed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--cache-root", required=True, type=pathlib.Path)
    parser.add_argument("--codex", required=True, type=pathlib.Path)
    parser.add_argument("--selector", default="cgkn@personal")
    args = parser.parse_args()
    print(json.dumps(refresh(source=args.source, cache_root=args.cache_root, codex=args.codex,
                             selector=args.selector), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
