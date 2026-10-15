from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from typing import Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PREFIXES = ("cgkn/", "contracts/", "tests/architecture/")
CORE_FILES = {
    "governance/kernel_layers.json",
    "governance/kernel_authorities.json",
    "governance/test_coverage_manifest.json",
    "scripts/kernel_architecture_gate.py",
    "scripts/kernel_completeness_gate.py",
    "scripts/kernel_gate_common.py",
    "scripts/kernel_source_identity.py",
    "scripts/test_architecture_gate.py",
    "scripts/run_kernel_profiles.py",
}


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _hash_rows(objects: Mapping[str, str], paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        object_id = objects.get(path)
        if not object_id: raise RuntimeError(f"cannot identify committed source: {path}")
        digest.update(path.encode("utf-8") + b"\0" + object_id.encode("ascii") + b"\0")
    return "sha256:" + digest.hexdigest()


def identity(commit: str = "HEAD") -> dict[str, object]:
    source_commit = _git("rev-parse", commit)
    rows = _git("ls-tree", "-r", source_commit).splitlines()
    objects = {line.split(None, 3)[3]: line.split(None, 3)[2] for line in rows if len(line.split(None, 3)) == 4}
    paths = list(objects)
    core_paths = [path for path in paths if path in CORE_FILES or path.startswith(CORE_PREFIXES) or path.startswith("scripts/kernel_")]
    test_paths = [path for path in paths if path.startswith(("tests/", "scripts/test_")) and path.endswith(".py")]
    authority_paths = [path for path in ("governance/kernel_layers.json", "governance/kernel_authorities.json") if path in paths]
    coverage_paths = [path for path in ("governance/test_coverage_manifest.json",) if path in paths]
    return {
        "kind": "CGKNKernelSourceIdentity",
        "schema_version": "1.0",
        "source_commit": source_commit,
        "source_tree_sha": _git("rev-parse", f"{source_commit}^{{tree}}"),
        "core_source_hash": _hash_rows(objects, core_paths),
        "test_source_hash": _hash_rows(objects, test_paths),
        "authority_manifest_hash": _hash_rows(objects, authority_paths),
        "coverage_manifest_hash": _hash_rows(objects, coverage_paths),
        "core_path_count": len(core_paths),
        "test_path_count": len(test_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output")
    args = parser.parse_args()
    value = identity(args.commit)
    rendered = json.dumps(value, indent=2) + "\n"
    if args.output:
        (ROOT / args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
