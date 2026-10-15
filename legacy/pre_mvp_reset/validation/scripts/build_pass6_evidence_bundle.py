#!/usr/bin/env python3
"""Build the Pass 6 support-evidence set without promoting formal status."""

from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cgkn-function-stress-pass" / "pass6-long-horizon-reliability"
REGRESSION = OUT / "full-provider-free-final" / "regression_summary.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_diff() -> str:
    tracked = [
        "project_management/current/active_iteration.json",
        "project_management/current/backlog.json",
        "project_management/current/risks.json",
        "project_management/current/enterprise_experience.json",
        "scripts/run_real_workload_recovery_stress.py",
    ]
    result = subprocess.run(["git", "diff", "--", *tracked], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    chunks = [result.stdout]
    new_files = [
        "scripts/run_pass6_long_horizon.py",
        "scripts/pass6_blind_evaluator.py",
        "scripts/build_pass6_evidence_bundle.py",
        "tests/test_pass6_long_horizon.py",
    ]
    for relative in new_files:
        path = ROOT / relative
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{relative}"))
    return "".join(chunks)


def performance_svg(sanity: dict) -> str:
    segments = sanity.get("summary", {}).get("trends", {}).get("segments", [])
    p95s = [float(row.get("p95") or 0) for row in segments]
    throughputs = [float(row.get("effective_throughput") or 0) for row in segments]
    labels = [str(row.get("name", "")) for row in segments]
    bars = []
    for index, (label, p95, throughput) in enumerate(zip(labels, p95s, throughputs)):
        x = 130 + index * 190
        bars.append(f'<rect x="{x}" y="{310 - min(220, p95 * 180):.1f}" width="55" height="{min(220, p95 * 180):.1f}" fill="#5b8ff9"/><text x="{x}" y="335" font-size="14">{label}</text>')
        bars.append(f'<rect x="{x + 65}" y="{310 - min(220, throughput * 150):.1f}" width="55" height="{min(220, throughput * 150):.1f}" fill="#61d9a7"/>')
    return """<svg xmlns="http://www.w3.org/2000/svg" width="760" height="430" viewBox="0 0 760 430">
<rect width="760" height="430" fill="#fbfcfe"/><text x="40" y="46" font-size="25" font-family="Segoe UI">CGKN Pass 6 sanity performance</text>
<text x="40" y="76" font-size="16" fill="#b42318">24-hour soak: NOT_EVALUATED / INCOMPLETE</text>
<line x1="90" y1="310" x2="700" y2="310" stroke="#475467"/><line x1="90" y1="90" x2="90" y2="310" stroke="#475467"/>
""" + "".join(bars) + """
<rect x="480" y="365" width="18" height="18" fill="#5b8ff9"/><text x="505" y="379" font-size="14">p95 latency (s)</text>
<rect x="480" y="395" width="18" height="18" fill="#61d9a7"/><text x="505" y="409" font-size="14">accepted throughput (/s)</text>
</svg>"""


def redact(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    # JSON may render each Windows separator one or more times depending on
    # nesting.  Match every escaped representation so a username cannot
    # survive packaging.
    text = re.sub(r"[A-Za-z]:\\+Users\\+[^\\\"\s]+", "<USER_HOME>", text, flags=re.IGNORECASE)
    text = text.replace(str(ROOT), "<REPO_ROOT>").replace(str(ROOT).replace("\\", "\\\\"), "<REPO_ROOT>")
    return text.encode("utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sanity = json.loads((OUT / "SANITY_RUN_RESULT.json").read_text(encoding="utf-8"))
    administrative = {"at": now(), "event": "soak_not_completed", "formal_evidence_status": "NOT_EVALUATED", "reason": "single_continuous_86400_second_run_not_completed"}
    (OUT / "SOAK_EVENTS.jsonl").write_text(json.dumps(administrative, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUT / "RESOURCE_EVENTS.jsonl").write_text(json.dumps({**administrative, "event": "resource_series_not_available"}, separators=(",", ":")) + "\n", encoding="utf-8")
    soak_summary = {
        "kind": "CGKNPass6SoakSummary",
        "formal_evidence_status": "NOT_EVALUATED",
        "workflow_state": "incomplete",
        "status": "NOT_EVALUATED",
        "reason": "single_continuous_86400_second_run_not_completed",
        "sanity_run": sanity,
    }
    dump(OUT / "SOAK_SUMMARY.json", soak_summary)
    trends = {"kind": "CGKNPass6ResourceTrends", "formal_evidence_status": "NOT_EVALUATED", "status": "NOT_EVALUATED", "reason": "24h_resource_series_not_available", "sanity_only": sanity["summary"]["trends"]}
    dump(OUT / "RESOURCE_TRENDS.json", trends)
    (OUT / "PERFORMANCE_CURVES.svg").write_text(performance_svg(sanity), encoding="utf-8")

    regression = json.loads(REGRESSION.read_text(encoding="utf-8")) if REGRESSION.is_file() else {
        "kind": "CGKNProviderFreeRegression",
        "formal_evidence_status": "NOT_EVALUATED",
        "status": "NOT_EVALUATED",
        "reason": "full_regression_not_run_after_pass6_changes",
    }
    dump(OUT / "FULL_REGRESSION_RESULTS.json", regression)
    (OUT / "KNOWN_LIMITS_PASS6.md").write_text(
        "# Known limits — Pass 6\n\n- The uninterrupted 24-hour Provider-free soak has not completed and remains `NOT_EVALUATED`.\n- No paid Provider call is authorized.\n- A running Ollama process and GPU were observed, but repository authorization, model identity, quantization, context, and isolation were not established; real-model quality remains `NOT_EVALUATED`.\n- The sanity workload exercises the existing ProviderJob generation and independent acceptance boundary but does not claim a final public delivery for each synthetic project; delivery counts therefore remain zero.\n- Blind-case infrastructure and contamination controls are engineering support evidence, not model-quality evidence.\n",
        encoding="utf-8",
    )
    (OUT / "REPRODUCE_PASS6.md").write_text(
        "# Reproduce CGKN Pass 6\n\nUse Python 3.13 from the frozen baseline.\n\n```powershell\npy -3.13 scripts\\run_pass6_long_horizon.py prepare --output-dir <new-run-dir>\npy -3.13 scripts\\run_pass6_long_horizon.py sanity --output-dir <new-run-dir> --duration-seconds 15\npy -3.13 scripts\\run_pass6_long_horizon.py soak --output-dir <new-run-dir>\npy -3.13 scripts\\run_pass3_regression.py --output-dir <new-run-dir>\\full-provider-free --scope full --timeout-seconds 7200\n```\n\nDo not combine interrupted runs. A source repair requires a new run id and a restart from the first case.\n",
        encoding="utf-8",
    )
    (OUT / "CURRENT_DIFF.patch").write_text(current_diff(), encoding="utf-8")

    include = [
        "PASS6_BASELINE.md", "PASS6_BASELINE.json", "SOAK_CONFIG.json", "SOAK_EVENTS.jsonl", "RESOURCE_EVENTS.jsonl",
        "SOAK_SUMMARY.json", "RESOURCE_TRENDS.json", "PERFORMANCE_CURVES.svg", "BLIND_CASE_MANIFEST.json",
        "BLIND_TEST_PROTOCOL.md", "CONTAMINATION_RESULTS.json", "MODEL_RUN_RESULTS.json", "FULL_REGRESSION_RESULTS.json",
        "KNOWN_LIMITS_PASS6.md", "REPRODUCE_PASS6.md", "CURRENT_DIFF.patch", "SANITY_RUN_RESULT.json",
    ]
    zip_path = OUT / "CGKN_PASS6_REDACTED_EVIDENCE.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in include:
            path = OUT / name
            archive.writestr(name, redact(path.read_bytes()))
        for path in sorted((OUT / "blind_cases" / "visible").glob("*.json")):
            archive.writestr(f"blind_cases/visible/{path.name}", redact(path.read_bytes()))
    bad = zipfile.ZipFile(zip_path).testzip()
    if bad:
        raise RuntimeError(f"bad zip member: {bad}")
    digest = sha256(zip_path)
    (OUT / "CGKN_PASS6_REDACTED_EVIDENCE.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(zip_path), "sha256": digest, "zip_test": "PASS", "regression_status": regression.get("status")}, indent=2))


if __name__ == "__main__":
    main()
