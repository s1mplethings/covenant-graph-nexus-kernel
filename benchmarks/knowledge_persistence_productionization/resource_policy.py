from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


MIB = 1024 * 1024
GIB = 1024 * MIB
RESOURCE_POLICY_VERSION = "2.0"
ESTIMATOR_VERSION = "active-pack-structural-upper-v1"

POLICY = {
    "resource_policy_version": RESOURCE_POLICY_VERSION,
    "estimator_version": ESTIMATOR_VERSION,
    "calibration_scales": [1_000, 5_000],
    "minimum_calibration_points": 2,
    "authoritative_growth_margin": 1.25,
    "checkpoint_ratio_margin": 1.20,
    "tail_segment_count": 257,
    "compaction_batch_size": 32,
    "fixed_evidence_bytes": 128 * MIB,
    "minimum_estimator_error_bytes": 1 * GIB,
    "estimator_error_fraction": 0.35,
    "minimum_os_disk_headroom_bytes": 16 * GIB,
    "maximum_os_disk_headroom_bytes": 32 * GIB,
    "os_disk_headroom_fraction": 0.01,
    "benchmark_disk_contingency_bytes": 2 * GIB,
    "memory_growth_margin": 1.35,
    "memory_fixed_headroom_bytes": 512 * MIB,
    "minimum_os_memory_headroom_bytes": 2 * GIB,
    "os_memory_headroom_fraction": 0.10,
    "secondary_predicted_used_percent_limit": 98.0,
}


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"RESOURCE_METRIC_UNAVAILABLE: {field}")
    return float(value)


def _calibration_values(calibrations: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    if len(calibrations) < int(POLICY["minimum_calibration_points"]):
        raise ValueError("RESOURCE_CALIBRATION_INSUFFICIENT")
    values: list[float] = []
    for index, row in enumerate(calibrations):
        size = _positive_number(row.get("scale"), f"calibrations[{index}].scale")
        value = _positive_number(row.get(field), f"calibrations[{index}].{field}")
        values.append(value / size)
    return values


def estimate_peak_resources(
    *,
    scale: int,
    calibrations: Sequence[Mapping[str, Any]],
    historical_s0: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return auditable lower/expected/conservative active-pack bounds.

    The estimator models the persisted structures that may coexist instead of
    extrapolating one opaque total: authoritative segments, one checkpoint,
    bounded mutation tail, compaction output, atomic/rollback duplicate,
    compact evidence, and an explicit estimator-error allowance.
    """

    if not isinstance(scale, int) or scale <= 0:
        raise ValueError("RESOURCE_SCALE_INVALID")
    if any(row.get("measurement_status") != "COMPLETE" for row in calibrations):
        raise ValueError("RESOURCE_CALIBRATION_UNCERTAIN")

    authoritative_per_item = _calibration_values(calibrations, "initial_authoritative_bytes")
    if historical_s0:
        for historical_scale, row in historical_s0.items():
            file_mb = row.get("file_mb")
            if isinstance(historical_scale, int) and historical_scale > 0 and isinstance(file_mb, (int, float)) and file_mb > 0:
                authoritative_per_item.append(float(file_mb) * MIB / historical_scale)
    authoritative_lower = math.ceil(min(authoritative_per_item) * scale)
    authoritative_expected = math.ceil(max(authoritative_per_item) * scale)
    authoritative_upper = math.ceil(authoritative_expected * float(POLICY["authoritative_growth_margin"]))

    checkpoint_ratios: list[float] = []
    update_segment_bytes: list[float] = []
    compaction_bytes: list[float] = []
    manifest_bytes: list[float] = []
    active_peaks: list[float] = []
    memory_points: list[tuple[float, float]] = []
    runtime_rss: list[float] = []
    for index, row in enumerate(calibrations):
        initial = _positive_number(row.get("initial_authoritative_bytes"), f"calibrations[{index}].initial_authoritative_bytes")
        checkpoint = _positive_number(row.get("checkpoint_bytes"), f"calibrations[{index}].checkpoint_bytes")
        checkpoint_ratios.append(checkpoint / initial)
        update_segment_bytes.append(_positive_number(row.get("largest_update_segment_bytes"), f"calibrations[{index}].largest_update_segment_bytes"))
        compaction_bytes.append(_positive_number(row.get("compaction_bytes_written"), f"calibrations[{index}].compaction_bytes_written"))
        manifest_bytes.append(_positive_number(row.get("peak_manifest_bytes"), f"calibrations[{index}].peak_manifest_bytes"))
        active_peaks.append(_positive_number(row.get("observed_active_peak_bytes"), f"calibrations[{index}].observed_active_peak_bytes"))
        baseline_rss = _positive_number(row.get("baseline_rss_bytes"), f"calibrations[{index}].baseline_rss_bytes")
        peak_rss = _positive_number(row.get("peak_rss_bytes"), f"calibrations[{index}].peak_rss_bytes")
        runtime_rss.append(baseline_rss)
        memory_points.append((float(row["scale"]), peak_rss))

    checkpoint_ratio = max(1.0, max(checkpoint_ratios)) * float(POLICY["checkpoint_ratio_margin"])
    checkpoint_upper = math.ceil(authoritative_upper * checkpoint_ratio)
    tail_upper = math.ceil(max(update_segment_bytes) * int(POLICY["tail_segment_count"]))
    manifest_upper = math.ceil(max(manifest_bytes) * 2.0)
    compaction_duplicate = math.ceil(max(max(compaction_bytes), max(update_segment_bytes) * int(POLICY["compaction_batch_size"])) * 1.25)
    evidence_bytes = int(POLICY["fixed_evidence_bytes"])

    active_peak_per_item = [
        active_peak / float(row["scale"])
        for active_peak, row in zip(active_peaks, calibrations, strict=True)
    ]
    lower_bound = max(math.ceil(min(active_peak_per_item) * scale), authoritative_lower)
    steady_expected = authoritative_expected + math.ceil(authoritative_expected * max(checkpoint_ratios)) + tail_upper + manifest_upper
    expected_peak = steady_expected + compaction_duplicate + evidence_bytes
    transaction_duplicate = max(authoritative_upper, checkpoint_upper, compaction_duplicate)
    estimator_error = max(
        int(POLICY["minimum_estimator_error_bytes"]),
        math.ceil(expected_peak * float(POLICY["estimator_error_fraction"])),
    )
    conservative_peak = authoritative_upper + checkpoint_upper + tail_upper + manifest_upper + compaction_duplicate + transaction_duplicate + evidence_bytes + estimator_error

    # Estimate the growing part from differences between calibration points;
    # this avoids multiplying fixed interpreter/runtime RSS by the target
    # scale. The separate fixed allowance and margin retain conservatism.
    memory_points.sort()
    memory_slopes = [
        max(0.0, (high_peak - low_peak) / (high_scale - low_scale))
        for (low_scale, low_peak), (high_scale, high_peak) in zip(memory_points, memory_points[1:])
        if high_scale > low_scale
    ]
    if not memory_slopes:
        raise ValueError("RESOURCE_CALIBRATION_INSUFFICIENT_FOR_MEMORY_SLOPE")
    incremental_memory = math.ceil(max(memory_slopes) * scale * float(POLICY["memory_growth_margin"]))
    process_peak = math.ceil(max(runtime_rss) * 1.25 + incremental_memory + int(POLICY["memory_fixed_headroom_bytes"]))
    return {
        "scale": scale,
        "lower_bound_bytes": lower_bound,
        "expected_peak_bytes": expected_peak,
        "conservative_peak_bytes": conservative_peak,
        "components": {
            "authoritative_lower_bytes": authoritative_lower,
            "authoritative_expected_bytes": authoritative_expected,
            "authoritative_upper_bytes": authoritative_upper,
            "checkpoint_upper_bytes": checkpoint_upper,
            "tail_segments_upper_bytes": tail_upper,
            "manifest_upper_bytes": manifest_upper,
            "compaction_duplicate_bytes": compaction_duplicate,
            "transaction_or_rollback_duplicate_bytes": transaction_duplicate,
            "evidence_bytes": evidence_bytes,
            "estimator_error_bytes": estimator_error,
        },
        "predicted_process_peak_rss_bytes": process_peak,
        "measurement_points": len(calibrations),
        "estimator_version": ESTIMATOR_VERSION,
    }


def evaluate_resource_gate(
    *,
    volume_total_bytes: Any,
    volume_free_bytes: Any,
    memory_total_bytes: Any,
    memory_available_bytes: Any,
    estimate: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        total = _positive_number(volume_total_bytes, "volume_total_bytes")
        free = _positive_number(volume_free_bytes, "volume_free_bytes")
        memory_total = _positive_number(memory_total_bytes, "memory_total_bytes")
        memory_available = _positive_number(memory_available_bytes, "memory_available_bytes")
        conservative = _positive_number(estimate.get("conservative_peak_bytes"), "conservative_peak_bytes")
        process_peak = _positive_number(estimate.get("predicted_process_peak_rss_bytes"), "predicted_process_peak_rss_bytes")
    except ValueError as error:
        return {"status": "FAIL", "decision": "BLOCK", "reasons": [str(error)], "policy_version": RESOURCE_POLICY_VERSION}

    if free > total or memory_available > memory_total:
        return {"status": "FAIL", "decision": "BLOCK", "reasons": ["RESOURCE_METRICS_INCONSISTENT"], "policy_version": RESOURCE_POLICY_VERSION}
    disk_os_headroom = max(
        int(POLICY["minimum_os_disk_headroom_bytes"]),
        min(int(POLICY["maximum_os_disk_headroom_bytes"]), math.ceil(total * float(POLICY["os_disk_headroom_fraction"]))),
    )
    required_free = conservative + disk_os_headroom + int(POLICY["benchmark_disk_contingency_bytes"])
    memory_os_headroom = max(int(POLICY["minimum_os_memory_headroom_bytes"]), math.ceil(memory_total * float(POLICY["os_memory_headroom_fraction"])))
    required_memory = process_peak + memory_os_headroom
    predicted_free = free - conservative
    predicted_used_percent = ((total - predicted_free) / total) * 100.0
    reasons: list[str] = []
    if free < required_free:
        reasons.append("ABSOLUTE_DISK_HEADROOM_INSUFFICIENT")
    if memory_available < required_memory:
        reasons.append("ABSOLUTE_MEMORY_HEADROOM_INSUFFICIENT")
    if predicted_free <= 0 or predicted_used_percent >= float(POLICY["secondary_predicted_used_percent_limit"]):
        reasons.append("PREDICTED_VOLUME_NEARLY_FULL")
    return {
        "status": "PASS" if not reasons else "FAIL",
        "decision": "ALLOW" if not reasons else "BLOCK",
        "reasons": reasons,
        "policy_version": RESOURCE_POLICY_VERSION,
        "inputs": {
            "volume_total_bytes": int(total), "volume_free_bytes": int(free),
            "memory_total_bytes": int(memory_total), "memory_available_bytes": int(memory_available),
        },
        "thresholds": {
            "required_free_bytes": math.ceil(required_free), "disk_os_headroom_bytes": disk_os_headroom,
            "required_memory_available_bytes": math.ceil(required_memory), "memory_os_headroom_bytes": memory_os_headroom,
            "secondary_predicted_used_percent_limit": POLICY["secondary_predicted_used_percent_limit"],
        },
        "predicted_post_run": {
            "free_bytes": math.floor(predicted_free), "used_percent": round(predicted_used_percent, 3),
        },
        "estimate": dict(estimate),
    }
