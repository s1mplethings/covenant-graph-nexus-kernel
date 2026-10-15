#!/usr/bin/env python3
"""Build a local, redacted Pass 3 evidence bundle."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import pathlib
import re
import subprocess
import zipfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]


def classify(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in (
        "pipeline_planner_agent",
        "autonomous project studio kernel",
        "reasoning_none",
        "reasoning\"]",
        "qwen_feature_unit",
    )):
        return "LEGACY_CONTRACT_DRIFT"
    if any(token in lowered for token in (
        "planned required paths are absent",
        "provider emission may return only",
        "leaf repair exhausted",
        "target_file",
        "expected symbols",
    )):
        return "STRICT_FIXTURE_DRIFT"
    if any(token in lowered for token in (
        "filenotfounderror",
        "missing pytest profile markers",
        "tracked_runtime_output",
        "gitignore",
        "provider_baseline_unavailable",
        "https://new.example",
    )):
        return "ENVIRONMENT_OR_REPOSITORY_FIXTURE"
    return "CURRENT_IMPLEMENTATION_FAILURE"


def redact(text: str) -> str:
    value = text.replace(str(ROOT), "<WORKSPACE>").replace(str(ROOT).lower(), "<WORKSPACE>")
    value = re.sub(r"C:\\Users\\[^\\\r\n]+\\AppData\\Local\\Temp", "<TEMP>", value, flags=re.I)
    value = re.sub(r"C:\\Users\\[^\\\r\n]+", "<USER_HOME>", value, flags=re.I)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
    value = re.sub(
        r"(?im)^(\s*(?:OPENAI|QWEN|DASHSCOPE|CGKN|CGNK)[A-Z0-9_]*(?:KEY|TOKEN)\s*[=:]\s*).+$",
        r"\1[REDACTED]",
        value,
    )
    return value


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-root",
        type=pathlib.Path,
        default=ROOT / "cgkn-function-stress-pass" / "pass3-verdict-runtime-closure",
    )
    parser.add_argument(
        "--operational-result",
        type=pathlib.Path,
        default=ROOT / "generated" / "codex_provider_projects" / "pass3-operational-20261010" / "operational_closure.json",
    )
    args = parser.parse_args(argv)
    evidence = args.evidence_root.resolve()
    events_path = evidence / "regression-old-failures-02" / "pytest_events.jsonl"
    failures = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") == "test_phase" and row.get("when") == "call" and row.get("outcome") == "failed":
            longrepr = str(row.get("longrepr", ""))
            failures.append(
                {
                    "nodeid": row["nodeid"],
                    "classification": classify(longrepr),
                    "failure_excerpt": redact(longrepr)[-2000:],
                }
            )
    counts: dict[str, int] = {}
    for row in failures:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    classification = {
        "kind": "CGKNPass3FailureClassification",
        "formal_evidence_status": "NEEDS_REWORK",
        "total": len(failures),
        "counts": counts,
        "failures": failures,
    }
    (evidence / "FAILURE_CLASSIFICATION.json").write_text(
        json.dumps(classification, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    operational_text = redact(args.operational_result.read_text(encoding="utf-8"))
    (evidence / "operational_closure.redacted.json").write_text(
        operational_text,
        encoding="utf-8",
    )
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.splitlines()
    for relative in sorted(untracked):
        normalized = relative.replace("\\", "/")
        if not normalized.startswith(("scripts/", "tests/", "benchmarks/", "project_management/summaries/")):
            continue
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".json"}:
            continue
        content = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        diff += "".join(
            difflib.unified_diff(
                [],
                content,
                fromfile="/dev/null",
                tofile=f"b/{normalized}",
            )
        )
    (evidence / "working_diff.patch").write_text(redact(diff), encoding="utf-8")

    selected = [
        *sorted(
            path
            for path in evidence.glob("*")
            if path.is_file()
            and path.suffix != ".zip"
            and path.name != "EVIDENCE_MANIFEST.json"
        ),
        *sorted((evidence / "regression-old-failures-02").glob("*")),
        *sorted((evidence / "regression-targeted-01").glob("*")),
    ]
    selected = [path for path in selected if path.is_file() and "pytest-cache" not in path.parts]
    payloads = {
        path.relative_to(evidence).as_posix(): redact(
            path.read_text(encoding="utf-8", errors="replace")
        ).encode("utf-8")
        for path in selected
    }
    manifest = {
        "kind": "CGKNPass3EvidenceManifest",
        "formal_evidence_status": "NEEDS_REWORK",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "path": name,
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
            for name, payload in sorted(payloads.items())
        ],
    }
    manifest_path = evidence / "EVIDENCE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_payload = redact(manifest_path.read_text(encoding="utf-8")).encode("utf-8")
    zip_path = evidence / "CGKN_PASS3_REDACTED_EVIDENCE.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(payloads.items()):
            archive.writestr(name, payload)
        archive.writestr("EVIDENCE_MANIFEST.json", manifest_payload)
    with zipfile.ZipFile(zip_path) as archive:
        combined = b"\n".join(archive.read(name) for name in archive.namelist())
    forbidden = {
        "workspace_path": str(ROOT).encode("utf-8"),
        "user_home": b"C:\\Users\\",
        "secret_token": re.compile(rb"\bsk-[A-Za-z0-9_-]{12,}"),
    }
    findings = {
        name: (
            bool(pattern.search(combined))
            if hasattr(pattern, "search")
            else pattern.lower() in combined.lower()
        )
        for name, pattern in forbidden.items()
    }
    if any(findings.values()):
        raise RuntimeError(f"redacted evidence validation failed: {findings}")
    print(json.dumps({"zip": str(zip_path), "sha256": sha256(zip_path), "files": len(payloads) + 1}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
