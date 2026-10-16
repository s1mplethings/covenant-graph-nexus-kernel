from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SourceBoundary:
    name: str
    prefixes: tuple[str, ...]
    files: frozenset[str] = frozenset()
    excluded_prefixes: tuple[str, ...] = ()

    def contains(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        if any(normalized.startswith(prefix) for prefix in self.excluded_prefixes):
            return False
        return normalized in self.files or any(normalized.startswith(prefix) for prefix in self.prefixes)


KERNEL_PACKAGES = (
    "agent", "artifacts", "capabilities", "compiler", "component", "execution",
    "executors", "governance", "growth", "orchestration", "providers", "runtime",
    "state", "telemetry",
)
KERNEL_TEST_PREFIXES = tuple(f"tests/{name}/" for name in (
    "agent", "architecture", "artifacts", "capabilities", "compiler", "component",
    "execution", "executors", "growth", "orchestration", "providers", "recovery",
    "runtime", "state", "telemetry",
))

BOUNDARIES: Mapping[str, SourceBoundary] = {
    "kernel": SourceBoundary(
        "kernel",
        tuple(f"cgkn/{package}/" for package in KERNEL_PACKAGES)
        + ("contracts/",)
        + KERNEL_TEST_PREFIXES,
        frozenset({
            "governance/kernel_layers.json",
            "governance/kernel_authorities.json",
            "governance/test_coverage_manifest.json",
            "scripts/generate_kernel_coverage_report.py",
            "scripts/generate_kernel_test_receipt.py",
            "scripts/kernel_architecture_gate.py",
            "scripts/kernel_completeness_gate.py",
            "scripts/kernel_gate_common.py",
            "scripts/kernel_source_identity.py",
            "scripts/run_kernel_profiles.py",
            "scripts/source_boundaries.py",
            "scripts/test_architecture_gate.py",
            "scripts/verify_kernel_test_receipt.py",
            "tests/test_artifact_driven_kernel.py",
            "tests/test_capability_tree_mvp.py",
            "tests/test_component_runtime_integration.py",
            "tests/test_kernel_contract.py",
            "tests/test_provider_transport.py",
        }),
    ),
    "application": SourceBoundary(
        "application",
        ("cgkn/application/", "tests/application/", "benchmarks/real_project_generation/"),
        frozenset({"scripts/run_real_project_generation.py"}),
    ),
    "experiment": SourceBoundary(
        "experiment",
        ("experiments/", "tests/experiments/"),
        frozenset({"scripts/run_semantic_artifact_experiment.py"}),
        ("experiments/semantic_artifact_design/receipts/",),
    ),
}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def git_objects(commit: str) -> tuple[str, str, dict[str, str]]:
    source_commit = _git("rev-parse", commit)
    rows = _git("ls-tree", "-r", source_commit).splitlines()
    objects = {
        parts[3]: parts[2]
        for line in rows
        if len(parts := line.split(None, 3)) == 4
    }
    return source_commit, _git("show", "-s", "--format=%T", source_commit), objects


def hash_objects(objects: Mapping[str, str], paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        object_id = objects.get(path)
        if object_id is None:
            raise RuntimeError(f"cannot identify committed source: {path}")
        digest.update(path.encode("utf-8") + b"\0" + object_id.encode("ascii") + b"\0")
    return "sha256:" + digest.hexdigest()


def boundary_identity(boundary_name: str, commit: str = "HEAD") -> dict[str, object]:
    try:
        boundary = BOUNDARIES[boundary_name]
    except KeyError as exc:
        raise ValueError(f"unknown source boundary: {boundary_name}") from exc
    source_commit, source_tree_sha, objects = git_objects(commit)
    paths = tuple(path for path in objects if boundary.contains(path))
    return {
        "kind": "CGKNSourceBoundaryIdentity",
        "schema_version": "1.0",
        "boundary": boundary.name,
        "source_commit": source_commit,
        "source_tree_sha": source_tree_sha,
        "boundary_hash": hash_objects(objects, paths),
        "path_count": len(paths),
    }


def changed_paths_since(commit: str) -> set[str]:
    value = _git("diff", "--name-only", f"{commit}..HEAD")
    return {line.strip().replace("\\", "/") for line in value.splitlines() if line.strip()}


def changed_boundary_paths(commit: str, boundary_name: str) -> set[str]:
    boundary = BOUNDARIES[boundary_name]
    return {path for path in changed_paths_since(commit) if boundary.contains(path)}


def render_all(commit: str = "HEAD") -> dict[str, object]:
    return {
        "kind": "CGKNSourceBoundarySet",
        "schema_version": "1.0",
        "identities": [boundary_identity(name, commit) for name in BOUNDARIES],
    }


if __name__ == "__main__":
    print(json.dumps(render_all(), indent=2))
