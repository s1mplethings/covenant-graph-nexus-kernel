from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_run_count": 3,
    "max_failed_runs": 0,
    "max_timeout_runs": 0,
    "max_invalid_output_runs": 0,
    "max_artifact_integrity_failures": 0,
    "require_deterministic_outputs": True,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_thresholds(thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(DEFAULT_THRESHOLDS)
    values.update(thresholds or {})
    for key in (
        "min_run_count",
        "max_failed_runs",
        "max_timeout_runs",
        "max_invalid_output_runs",
        "max_artifact_integrity_failures",
    ):
        values[key] = max(0, int(values[key]))
    values["require_deterministic_outputs"] = bool(values["require_deterministic_outputs"])
    return values


def reproducibility_hash(record: dict[str, Any]) -> str:
    direct = str(record.get("reproducibility_hash") or record.get("output_hash") or "").strip()
    if direct:
        return direct
    hashes = record.get("output_hashes", [])
    if not isinstance(hashes, list) or not hashes:
        return ""
    payload = "\n".join(sorted(str(item) for item in hashes if str(item).strip()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else ""


def evaluate(
    *,
    run_records: list[dict[str, Any]],
    output_path: pathlib.Path | None = None,
    thresholds: dict[str, Any] | None = None,
    gate_test_only: bool = False,
) -> dict[str, Any]:
    limits = normalize_thresholds(thresholds)
    records = [item for item in run_records if isinstance(item, dict)]
    run_count = len(records)
    timeout_runs = sum(1 for item in records if bool(item.get("timed_out")))
    invalid_runs = sum(1 for item in records if bool(item.get("invalid_output")))
    artifact_failures = sum(1 for item in records if str(item.get("artifact_integrity_status") or "FAIL").upper() != "PASS")
    successful_runs = sum(
        1
        for item in records
        if str(item.get("status") or "").upper() == "PASS"
        and not bool(item.get("timed_out"))
        and not bool(item.get("invalid_output"))
        and str(item.get("artifact_integrity_status") or "").upper() == "PASS"
    )
    failed_runs = run_count - successful_runs
    runtimes = [float(item.get("runtime_seconds") or 0.0) for item in records]
    hashes = [reproducibility_hash(item) for item in records]
    non_empty_hashes = [item for item in hashes if item]
    deterministic = bool(records) and len(non_empty_hashes) == run_count and len(set(non_empty_hashes)) == 1
    blockers: list[str] = []
    if run_count < limits["min_run_count"]:
        blockers.append("reliability_run_count_below_minimum")
    if failed_runs > limits["max_failed_runs"]:
        blockers.append("reliability_failed_runs_above_threshold")
    if timeout_runs > limits["max_timeout_runs"]:
        blockers.append("reliability_timeout_runs_above_threshold")
    if invalid_runs > limits["max_invalid_output_runs"]:
        blockers.append("reliability_invalid_output_runs_above_threshold")
    if artifact_failures > limits["max_artifact_integrity_failures"]:
        blockers.append("reliability_artifact_integrity_failures_above_threshold")
    if limits["require_deterministic_outputs"] and not deterministic:
        blockers.append("reliability_outputs_not_deterministic")
    status = "pass" if run_count and not blockers else ("not_ready" if run_count == 0 else "fail")
    report = {
        "generated_at": now(),
        "run_count": run_count,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "timeout_runs": timeout_runs,
        "invalid_output_runs": invalid_runs,
        "artifact_integrity_failures": artifact_failures,
        "average_runtime_seconds": round(sum(runtimes) / max(1, run_count), 6) if run_count else 0.0,
        "max_runtime_seconds": round(max(runtimes), 6) if runtimes else 0.0,
        "reproducibility_hashes": hashes,
        "deterministic_outputs": deterministic,
        "reliability_status": status,
        "thresholds": limits,
        "blockers": blockers,
        "gate_test_only": bool(gate_test_only),
        "reason": (
            "Repeat reliability evidence passed configured thresholds."
            if status == "pass"
            else "Repeat reliability evidence is missing or below configured thresholds."
        ),
    }
    if output_path:
        write_json(pathlib.Path(output_path), report)
    return report


def empty_report(output_path: pathlib.Path | None = None) -> dict[str, Any]:
    return evaluate(run_records=[], output_path=output_path)
