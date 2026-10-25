#!/usr/bin/env python3
"""Fail-closed release license, provenance, privacy, and secret audit."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import threading
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator


ROOT = pathlib.Path(__file__).resolve().parents[1]
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
PROVENANCE = pathlib.Path("research/release-056/provenance_manifest.json")
BINARY_SUFFIXES = {
    ".7z", ".avi", ".bin", ".db", ".dll", ".dylib", ".eot", ".exe",
    ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".mp3", ".mp4", ".otf",
    ".parquet", ".pdf", ".png", ".so", ".tar", ".ttf", ".wav", ".webm",
    ".webp", ".woff", ".woff2", ".zip",
}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(rb"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_token": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "assigned_secret": re.compile(
        rb"(?i)(?:api[_-]?key|authorization|bearer|client[_-]?secret|password|"
        rb"provider[_-]?secret|access[_-]?token)\s*[:=]\s*['\"]"
        rb"(?!placeholder\b|example\b|dummy\b|test\b|changeme\b|redacted\b|"
        rb"env\b|none\b|null\b)[A-Za-z0-9_./+\-=]{16,}"
    ),
}
USER_PATH = re.compile(
    rb"(?i)(?:[A-Z]:[\\/]+Users[\\/]+(?!USER\b|USERNAME\b|example\b|test\b)"
    rb"[^\\/\s\"']+|/home/(?!user\b|example\b|test\b)[^/\s\"']+)"
)
TEXT_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    gate: str
    severity: str
    location: str
    fingerprint: str
    detail: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(*args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, input=input_bytes, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def tracked_paths() -> list[pathlib.Path]:
    return [pathlib.Path(line) for line in run_git("ls-files", "-z").decode().split("\0") if line]


def _line_number(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def scan_bytes(data: bytes, location: str, *, history: bool) -> list[Finding]:
    if len(data) > TEXT_LIMIT or b"\x00" in data[:8192]:
        return []
    findings: list[Finding] = []
    repository_path = location.split(":", 1)[-1].replace("\\", "/") if history else location
    is_test_fixture = repository_path.startswith("tests/")
    for name, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(data):
            line = _line_number(data, match.start())
            findings.append(Finding(
                gate="secret_history" if history else "secret_current",
                severity="P1" if is_test_fixture else "P0",
                location=f"{location}:{line}",
                fingerprint=sha256(match.group(0))[:16],
                detail=f"{name}; {'test fixture candidate' if is_test_fixture else 'unreviewed secret candidate'}",
            ))
    for match in USER_PATH.finditer(data):
        line = _line_number(data, match.start())
        findings.append(Finding(
            gate="privacy_history" if history else "privacy_current",
            severity="P2" if is_test_fixture else "P1",
            location=f"{location}:{line}",
            fingerprint=sha256(match.group(0).lower())[:16],
            detail="user-home absolute path",
        ))
    return findings


def scan_current(paths: Iterable[pathlib.Path]) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        path = ROOT / rel
        if path.is_file():
            findings.extend(scan_bytes(path.read_bytes(), rel.as_posix(), history=False))
    return findings


def history_blobs() -> Iterator[tuple[str, str, bytes]]:
    object_lines = run_git("rev-list", "--objects", "--all").decode("utf-8", "replace").splitlines()
    names: dict[str, str] = {}
    for line in object_lines:
        oid, _, path = line.partition(" ")
        if path and oid not in names:
            names[oid] = path
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None

    def write_requests() -> None:
        try:
            for oid in names:
                process.stdin.write((oid + "\n").encode("ascii"))
            process.stdin.close()
        except BrokenPipeError:
            pass

    writer = threading.Thread(target=write_requests, daemon=True)
    writer.start()
    for requested_oid, path in names.items():
        header = process.stdout.readline().decode("ascii", "replace").strip().split()
        if len(header) < 3:
            continue
        oid, object_type, raw_size = header[:3]
        size = int(raw_size)
        data = process.stdout.read(size)
        process.stdout.read(1)
        if oid != requested_oid:
            raise RuntimeError("git cat-file response order mismatch")
        if object_type == "blob" and size <= TEXT_LIMIT:
            yield oid, path, data
    writer.join()
    returncode = process.wait()
    if returncode:
        stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        raise RuntimeError(f"git cat-file failed: {stderr}")


def scan_history() -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    seen: set[str] = set()
    for oid, path, data in history_blobs():
        count += 1
        for finding in scan_bytes(data, f"{oid}:{path}", history=True):
            key = f"{finding.gate}:{finding.fingerprint}:{path}"
            if key not in seen:
                seen.add(key)
                findings.append(finding)
    return findings, count


def metadata_findings() -> list[Finding]:
    findings: list[Finding] = []
    license_path = ROOT / "LICENSE"
    if not license_path.is_file() or sha256(license_path.read_bytes()) != LICENSE_SHA256:
        findings.append(Finding("license", "P0", "LICENSE", "apache-text", "Apache-2.0 text mismatch"))
    for rel in (pathlib.Path("pyproject.toml"), pathlib.Path("tools/cgkn-agent-kit/pyproject.toml")):
        try:
            project = tomllib.loads((ROOT / rel).read_text("utf-8"))["project"]
            if project.get("license") != "Apache-2.0":
                raise ValueError("SPDX license is not Apache-2.0")
        except Exception as exc:
            findings.append(Finding("license", "P0", rel.as_posix(), "metadata", str(exc)))
    for rel in ("README.md", "CITATION.cff", "CONTRIBUTING.md", "SECURITY.md", "docs/THIRD_PARTY_LICENSES.md"):
        if not (ROOT / rel).is_file():
            findings.append(Finding("release_metadata", "P0", rel, "missing", "required release document missing"))
    return findings


def postiz_findings(paths: Iterable[pathlib.Path]) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        if rel.suffix != ".py":
            continue
        path = ROOT / rel
        try:
            tree = ast.parse(path.read_text("utf-8"), filename=rel.as_posix())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(module == "postiz" or module.startswith("postiz.") for module in modules):
                findings.append(Finding("postiz_boundary", "P0", rel.as_posix(), "import", "Postiz implementation import"))
    return findings


def provenance_findings(paths: Iterable[pathlib.Path]) -> tuple[list[Finding], dict]:
    manifest = json.loads((ROOT / PROVENANCE).read_text("utf-8"))
    declared = {item["path"]: item for item in manifest["tracked_binary_assets"]}
    actual = sorted(rel.as_posix() for rel in paths if rel.suffix.lower() in BINARY_SUFFIXES)
    findings: list[Finding] = []
    for rel in actual:
        item = declared.get(rel)
        if item is None:
            findings.append(Finding("asset_provenance", "P0", rel, "undeclared", "binary asset missing provenance"))
            continue
        digest = sha256((ROOT / rel).read_bytes())
        if digest != item.get("sha256"):
            findings.append(Finding("asset_provenance", "P0", rel, digest[:16], "binary asset hash mismatch"))
    for rel in sorted(set(declared) - set(actual)):
        findings.append(Finding("asset_provenance", "P0", rel, "missing", "declared binary asset not tracked"))
    benchmark_paths = [rel.as_posix() for rel in paths if rel.as_posix().startswith("benchmarks/")]
    prefixes = tuple(item["path_prefix"] for item in manifest["benchmark_materials"])
    for rel in benchmark_paths:
        if not rel.startswith(prefixes):
            findings.append(Finding("benchmark_provenance", "P0", rel, "undeclared", "benchmark material has no provenance entry"))
    return findings, {"binary_assets": actual, "benchmark_file_count": len(benchmark_paths)}


def audit(*, include_history: bool) -> dict:
    paths = tracked_paths()
    for required in (pathlib.Path("LICENSE"), PROVENANCE, pathlib.Path("pyproject.toml"), pathlib.Path("CITATION.cff")):
        if required not in paths and (ROOT / required).exists():
            paths.append(required)
    findings = metadata_findings() + postiz_findings(paths) + scan_current(paths)
    provenance, inventory = provenance_findings(paths)
    findings.extend(provenance)
    history_blob_count = 0
    if include_history:
        historical, history_blob_count = scan_history()
        findings.extend(historical)
    blockers = [finding for finding in findings if finding.severity == "P0"]
    return {
        "kind": "CGKNReleaseComplianceAudit",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository_head": run_git("rev-parse", "HEAD").decode().strip(),
        "history_included": include_history,
        "history_blob_count": history_blob_count,
        "inventory": inventory,
        "finding_count": len(findings),
        "p0_count": len(blockers),
        "status": "PASS" if not blockers else "PUBLIC_RELEASE_BLOCKED_LICENSE_OR_PROVENANCE",
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true", help="scan all reachable Git blobs")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    report = audit(include_history=args.history)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
