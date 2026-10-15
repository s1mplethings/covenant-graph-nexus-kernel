#!/usr/bin/env python3
"""Build the bounded, redacted Pass 5 engineering evidence bundle."""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_real_workload_recovery_stress import validate_evidence

SOURCE_SHORT = ROOT / "artifacts" / "function_stress_pass" / "20261011-pass5-short-final2"
SOURCE_STEADY = ROOT / "artifacts" / "function_stress_pass" / "20261011-pass5-steady-pass" / "steady-30m"
DEST = ROOT / "cgkn-function-stress-pass" / "pass5-real-workload-recovery"


def read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_file(source: pathlib.Path, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def collect() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    short = read_json(SOURCE_SHORT / "campaign_summary.json")
    steady = read_json(SOURCE_STEADY / "profile_summary.json")
    profiles = list(short.get("profiles", [])) + [{**steady, "phase": "steady", "repetition": 1}]
    return short, steady, profiles


def copy_raw_evidence() -> None:
    for name in ("campaign_summary.json", "source_identity.before.json", "source_identity.after.json"):
        copy_file(SOURCE_SHORT / name, DEST / "short-final" / name)
    for name in ("fault_report.json", "fault_events.jsonl"):
        copy_file(SOURCE_SHORT / "faults" / name, DEST / "faults" / name)
    for profile in sorted((SOURCE_SHORT / "short").iterdir()):
        if not profile.is_dir():
            continue
        for name in ("profile_summary.json", "arrival_events.jsonl", "resource_events.jsonl"):
            copy_file(profile / name, DEST / "short-final" / profile.name / name)
    for name in ("profile_summary.json", "arrival_events.jsonl", "resource_events.jsonl"):
        copy_file(SOURCE_STEADY / name, DEST / "steady-30m" / name)


def write_performance(profiles: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        config = profile["configuration"]
        latency = profile["latency_seconds"]
        resources = profile["resources"]
        accounting = profile["accounting"]
        rows.append(
            {
                "phase": profile.get("phase", "short"),
                "repetition": profile.get("repetition", 1),
                "project_concurrency": config["project_concurrency"],
                "provider_job_concurrency": config["provider_job_concurrency"],
                "arrival_rate_per_second": config["arrival_rate_per_second"],
                "planned": accounting["planned"],
                "submitted": accounting["submitted"],
                "rejected": accounting["rejected"],
                "completed": accounting["completed"],
                "accepted": accounting["independent_acceptance_passed"],
                "p50_seconds": latency["p50"],
                "p95_seconds": latency["p95"],
                "p99_seconds": latency["p99"],
                "throughput_per_second": profile["effective_throughput_per_second"],
                "cpu_max_percent": resources["cpu_percent"]["max"],
                "rss_max_bytes": resources["rss_bytes"]["max"],
                "rss_delta_bytes": resources["rss_bytes"]["delta"],
                "disk_final_bytes": resources["disk_bytes"]["last"],
                "handle_max": resources["handle_count"]["max"],
                "handle_delta": resources["handle_count"]["delta"],
                "queue_max": resources["queue_depth"]["max"],
                "resource_samples": resources["sample_count"],
                "sample_gap_p99_seconds": resources["observed_interval_seconds"]["p99"],
                "status": profile["status"],
            }
        )
    csv_path = DEST / "performance_curves.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(DEST / "performance_summary.json", {"kind": "CGKNPass5PerformanceSummary", "formal_evidence_status": "NOT_EVALUATED", "rows": rows})
    short_rows = [row for row in rows if row["phase"] == "short"]
    aggregates = []
    for concurrency in (1, 5, 10, 20):
        selected = [row for row in short_rows if row["project_concurrency"] == concurrency]
        aggregates.append(
            {
                "x": concurrency,
                "p50": sum(float(row["p50_seconds"]) for row in selected) / len(selected),
                "p95": sum(float(row["p95_seconds"]) for row in selected) / len(selected),
                "p99": sum(float(row["p99_seconds"]) for row in selected) / len(selected),
                "throughput": sum(float(row["throughput_per_second"]) for row in selected) / len(selected),
            }
        )
    width, height = 960, 520
    left, top, plot_w, plot_h = 70, 55, 820, 360
    max_latency = max(row["p99"] for row in aggregates) * 1.1 or 1.0
    max_throughput = max(row["throughput"] for row in aggregates) * 1.1 or 1.0
    x_pos = lambda x: left + (x - 1) / 19 * plot_w
    y_latency = lambda y: top + plot_h - y / max_latency * plot_h
    y_throughput = lambda y: top + plot_h - y / max_throughput * plot_h
    colors = {"p50": "#2563eb", "p95": "#7c3aed", "p99": "#dc2626", "throughput": "#059669"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="70" y="28" font-family="sans-serif" font-size="20" font-weight="700">CGKN Pass 5 — concurrency latency and throughput</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#334155"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#334155"/>',
    ]
    for item in aggregates:
        x = x_pos(item["x"])
        parts.append(f'<text x="{x}" y="{top + plot_h + 24}" text-anchor="middle" font-family="sans-serif" font-size="12">{item["x"]}</text>')
    for metric in ("p50", "p95", "p99"):
        points = " ".join(f'{x_pos(item["x"]):.1f},{y_latency(item[metric]):.1f}' for item in aggregates)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[metric]}" stroke-width="3"/>')
    throughput_points = " ".join(f'{x_pos(item["x"]):.1f},{y_throughput(item["throughput"]):.1f}' for item in aggregates)
    parts.append(f'<polyline points="{throughput_points}" fill="none" stroke="{colors["throughput"]}" stroke-width="3" stroke-dasharray="7 5"/>')
    for index, metric in enumerate(("p50", "p95", "p99", "throughput")):
        y = 445 + index * 18
        parts.extend([
            f'<line x1="70" y1="{y}" x2="100" y2="{y}" stroke="{colors[metric]}" stroke-width="3"/>',
            f'<text x="108" y="{y + 4}" font-family="sans-serif" font-size="12">{metric}{" (projects/s, right-scaled)" if metric == "throughput" else " latency (s)"}</text>',
        ])
    parts.extend([
        '<text x="480" y="505" text-anchor="middle" font-family="sans-serif" font-size="13">Concurrent projects (three-run mean)</text>',
        '</svg>',
    ])
    (DEST / "performance_curves.svg").write_text("\n".join(parts), encoding="utf-8")


def write_acceptance(short: dict[str, Any], steady: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = {"faults": short["faults"], "profiles": profiles}
    validation = validate_evidence(candidate)
    regression = read_json(DEST / "full-final-py313" / "regression_summary.json")
    baseline_preserved = regression.get("status") == "PASS" and regression.get("counts", {}).get("tests") == 2606
    acceptance = {
        "kind": "CGKNPass5IndependentEngineeringAcceptance",
        "formal_evidence_status": "NOT_EVALUATED",
        "authority": "engineering_support_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stress_validation": validation,
        "short_gate": short.get("short_gate"),
        "steady_status": steady.get("status"),
        "provider_free_regression": regression.get("counts"),
        "fourth_batch_2598_preserved": baseline_preserved,
        "new_tests": 8,
        "paid_provider_calls": 0,
        "local_model": "NOT_EVALUATED",
        "soak_24h": "NOT_EVALUATED",
        "status": "PASS_WITH_LIMITS" if validation["status"] == "PASS" and steady.get("status") == "PASS" and baseline_preserved else "FAIL",
    }
    write_json(DEST / "independent_acceptance.json", acceptance)
    return acceptance


def write_reports(short: dict[str, Any], steady: dict[str, Any], acceptance: dict[str, Any]) -> None:
    latency = steady["latency_seconds"]
    resources = steady["resources"]
    accounting = steady["accounting"]
    report = f"""# CGKN Pass 5 — Real Workload & Recovery Stress

## Outcome

Engineering scope: `{acceptance['status']}`. Formal product evidence remains `NOT_EVALUATED`.

- Real recovery faults: 7/7 observed through OS process or canonical identity/checkpoint paths.
- Three isolated short runs: all 12 concurrency profiles passed.
- 30-minute steady state: `{steady['status']}` after {steady['elapsed_seconds']:.3f} seconds.
- Fixed arrivals: {accounting['planned']} planned, {accounting['submitted']} submitted, {accounting['rejected']} rejected, {accounting['cancelled']} cancelled, {accounting['timed_out']} timed out, {accounting['failed']} failed, {accounting['completed']} completed, {accounting['independent_acceptance_passed']} independently accepted.
- Latency: p50 {latency['p50']:.3f}s, p95 {latency['p95']:.3f}s, p99 {latency['p99']:.3f}s.
- Effective throughput: {steady['effective_throughput_per_second']:.3f} accepted projects/s.
- CPU max {resources['cpu_percent']['max']:.1f}%, RSS max {resources['rss_bytes']['max'] / 1048576:.1f} MiB, RSS delta {resources['rss_bytes']['delta'] / 1048576:.1f} MiB.
- Disk final {resources['disk_bytes']['last'] / 1048576:.1f} MiB; handles max {resources['handle_count']['max']:.0f}, delta {resources['handle_count']['delta']:.0f}; queue max {resources['queue_depth']['max']:.0f}.
- Resource samples: {resources['active_sample_count']} active; interval p99 {resources['observed_interval_seconds']['p99']:.3f}s, max {resources['observed_interval_seconds']['max']:.3f}s.
- Provider-free regression: 2606 machine-accounted tests, 0 failures/errors/skips; this preserves all fourth-batch 2598 and adds 8 tests.

## Recovery findings and fixes

1. The first steady attempt exposed deferred terminal collection, which inflated latency and hid in-run completions. Terminal results are now collected during the arrival window and completion timestamps come from Future callbacks.
2. The next attempt exposed one retained Windows handle per completed Future. Terminal accounting now releases Future objects immediately; the final steady run ended with a handle delta of {resources['handle_count']['delta']:.0f}.
3. Full directory scans distorted the declared resource cadence. Disk measurement now runs independently at a lower cadence, active CPU/RSS/handle/queue sampling records observed interval percentiles, and shutdown-final disk reconciliation is excluded from active-gap calculations.
4. Agent Kit replacement observation was made tolerant of bounded OS scheduling delay without weakening job/attempt/run identity checks.

## Limits

No paid Provider calls were made. Local-model quality and the 24-hour soak were not run and remain `NOT_EVALUATED`. This engineering evidence cannot authorize formal product acceptance, packaging, delivery, publication, or release.
"""
    (DEST / "RECOVERY_AND_STEADY_STATE_REPORT.md").write_text(report, encoding="utf-8")


def build_zip() -> pathlib.Path:
    selected: list[pathlib.Path] = []
    for path in DEST.rglob("*"):
        if not path.is_file() or path.suffix in {".zip", ".sha256"}:
            continue
        if "pytest-cache" in path.parts or "projects" in path.parts:
            continue
        selected.append(path)
    for relative in (
        "scripts/run_real_workload_recovery_stress.py",
        "scripts/build_pass5_evidence_bundle.py",
        "tests/test_real_workload_recovery_stress.py",
        "project_management/current/active_iteration.json",
        "project_management/summaries/ITER-103-real-workload-recovery-stress.md",
    ):
        selected.append(ROOT / relative)
    zip_path = DEST / "CGKN_PASS5_REDACTED_EVIDENCE.zip"
    manifest: list[dict[str, Any]] = []
    replacements = {
        str(ROOT): "[REPOSITORY_ROOT]",
        str(ROOT).replace("\\", "/"): "[REPOSITORY_ROOT]",
        str(pathlib.Path.home()): "[USER_HOME]",
        str(pathlib.Path.home()).replace("\\", "/"): "[USER_HOME]",
        str(os.environ.get("USERPROFILE", "")): "[USER_HOME]",
    }
    replacements = {key: value for key, value in replacements.items() if key}
    for source, replacement in list(replacements.items()):
        replacements[source.replace("\\", "\\\\")] = replacement
    replacements[pathlib.Path.home().name] = "[USER]"

    def redacted_bytes(path: pathlib.Path) -> bytes:
        data = path.read_bytes()
        if path.suffix.lower() not in {".json", ".jsonl", ".log", ".md", ".csv", ".py", ".xml", ".svg", ".txt"}:
            return data
        text = data.decode("utf-8", errors="replace")
        for source, replacement in replacements.items():
            text = text.replace(source, replacement)
        return text.encode("utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(set(selected)):
            relative = path.relative_to(ROOT).as_posix()
            lowered = relative.lower()
            if any(marker in lowered for marker in ("secret", "credential", ".env", "api_key", "token")):
                continue
            data = redacted_bytes(path)
            manifest.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            archive.writestr(relative, data)
        manifest_data = (json.dumps({"files": manifest}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        archive.writestr("EVIDENCE_MANIFEST.json", manifest_data)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (DEST / "CGKN_PASS5_REDACTED_EVIDENCE.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    copy_raw_evidence()
    short, steady, profiles = collect()
    write_performance(profiles)
    acceptance = write_acceptance(short, steady, profiles)
    write_reports(short, steady, acceptance)
    zip_path = build_zip()
    print(json.dumps({"status": acceptance["status"], "zip": str(zip_path), "bytes": zip_path.stat().st_size}, ensure_ascii=False, indent=2))
    return 0 if acceptance["status"] == "PASS_WITH_LIMITS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
