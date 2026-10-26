#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import random
import statistics
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINES = (
    "B0_DIRECT_CHEAP",
    "B1_DIRECT_STRONG",
    "B2_FLAT_CONTEXT_CHEAP",
    "B3_CURRENT_CGNK_BASELINE",
    "B4_OPTIMIZED_CGNK_RC",
)
SEED = 56025
BOOTSTRAP_RESAMPLES = 10_000


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_bootstrap_interval(
    left: Sequence[float], right: Sequence[float], *, seed: int = SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, float | int | None]:
    if len(left) != len(right):
        raise ValueError("paired samples must have equal length")
    if not left:
        return {"n": 0, "mean_difference": None, "ci95_low": None, "ci95_high": None}
    differences = [float(a) - float(b) for a, b in zip(left, right)]
    rng = random.Random(seed)
    means = [
        statistics.fmean(differences[rng.randrange(len(differences))] for _ in differences)
        for _ in range(resamples)
    ]
    return {
        "n": len(differences),
        "mean_difference": statistics.fmean(differences),
        "ci95_low": percentile(means, 0.025),
        "ci95_high": percentile(means, 0.975),
    }


def mcnemar_exact(left: Sequence[bool], right: Sequence[bool]) -> dict[str, int | float | None]:
    if len(left) != len(right):
        raise ValueError("paired samples must have equal length")
    left_only = sum(bool(a) and not bool(b) for a, b in zip(left, right))
    right_only = sum(not bool(a) and bool(b) for a, b in zip(left, right))
    discordant = left_only + right_only
    if discordant == 0:
        p_value: float | None = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(left_only, right_only) + 1)) / (2 ** discordant)
        p_value = min(1.0, 2.0 * tail)
    return {
        "left_only_success": left_only,
        "right_only_success": right_only,
        "discordant": discordant,
        "p_value_two_sided": p_value,
    }


def _known_numbers(rows: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]


def _price_by_model(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(row["model"]): row for row in snapshot.get("models", ())}


def row_cost(row: Mapping[str, Any], prices: Mapping[str, Mapping[str, Any]]) -> float | None:
    input_tokens = row.get("input_tokens")
    output_tokens = row.get("output_tokens")
    if not isinstance(input_tokens, (int, float)) or not isinstance(output_tokens, (int, float)):
        return None
    price = prices.get(str(row.get("actual_model") or row.get("model")))
    if price is None:
        return None
    cached = row.get("cached_tokens")
    cached_tokens = float(cached) if isinstance(cached, (int, float)) else 0.0
    uncached_tokens = max(0.0, float(input_tokens) - cached_tokens)
    cache_price = price.get("cache_hit_input_price")
    cached_rate = float(cache_price) if isinstance(cache_price, (int, float)) else float(price["input_price"])
    return (
        uncached_tokens * float(price["input_price"])
        + cached_tokens * cached_rate
        + float(output_tokens) * float(price["output_price"])
    ) / 1_000_000.0


def summarize_run(run: Mapping[str, Any], prices: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(run.get("rows", ()))
    completed = [row for row in rows if row.get("status") != "BLOCKED_PROVIDER"]
    costs = [cost for row in completed if (cost := row_cost(row, prices)) is not None]
    successes = sum(bool(row.get("success")) for row in completed)
    return {
        "baseline": run.get("baseline"),
        "batch_id": run.get("batch_id"),
        "tasks": len(rows),
        "completed": len(completed),
        "successes": successes,
        "success_rate": successes / len(completed) if completed else None,
        "context_chars_p50": percentile(_known_numbers(completed, "context_chars"), 0.50),
        "context_chars_p95": percentile(_known_numbers(completed, "context_chars"), 0.95),
        "input_tokens": sum(_known_numbers(completed, "input_tokens")) or None,
        "output_tokens": sum(_known_numbers(completed, "output_tokens")) or None,
        "total_tokens": sum(_known_numbers(completed, "total_tokens")) or None,
        "elapsed_ms_p50": percentile(_known_numbers(completed, "elapsed_ms"), 0.50),
        "elapsed_ms_p95": percentile(_known_numbers(completed, "elapsed_ms"), 0.95),
        "estimated_cost_usd": sum(costs) if len(costs) == len(completed) else None,
        "usage_known": len(costs) == len(completed),
    }


def paired_comparison(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_rows = {str(row["case_id"]): row for row in left.get("rows", ())}
    right_rows = {str(row["case_id"]): row for row in right.get("rows", ())}
    case_ids = sorted(left_rows.keys() & right_rows.keys())
    left_success = [bool(left_rows[key].get("success")) for key in case_ids]
    right_success = [bool(right_rows[key].get("success")) for key in case_ids]
    success = paired_bootstrap_interval(
        [float(value) for value in left_success], [float(value) for value in right_success],
    )
    context_pairs = [
        (float(left_rows[key]["context_chars"]), float(right_rows[key]["context_chars"]))
        for key in case_ids
        if isinstance(left_rows[key].get("context_chars"), (int, float))
        and isinstance(right_rows[key].get("context_chars"), (int, float))
    ]
    context = paired_bootstrap_interval(
        [pair[0] for pair in context_pairs], [pair[1] for pair in context_pairs],
    )
    return {
        "left": left.get("baseline"),
        "right": right.get("baseline"),
        "paired_case_count": len(case_ids),
        "success_difference": success,
        "mcnemar_exact": mcnemar_exact(left_success, right_success),
        "context_chars_difference": context,
    }


def _git_identity() -> tuple[str, str]:
    def command(*args: str) -> str:
        value = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        )
        return value.stdout.strip()
    return command("rev-parse", "HEAD"), command("show", "-s", "--format=%T", "HEAD")


def analyze(runs: Mapping[str, Mapping[str, Any]], pricing: Mapping[str, Any]) -> dict[str, Any]:
    prices = _price_by_model(pricing)
    summaries = {name: summarize_run(runs[name], prices) for name in sorted(runs)}
    comparison_specs = {
        "B4_vs_B3": ("B4_OPTIMIZED_CGNK_RC", "B3_CURRENT_CGNK_BASELINE"),
        "B4_vs_B2": ("B4_OPTIMIZED_CGNK_RC", "B2_FLAT_CONTEXT_CHEAP"),
        "B1_vs_B0": ("B1_DIRECT_STRONG", "B0_DIRECT_CHEAP"),
    }
    comparisons = {
        name: paired_comparison(runs[left], runs[right])
        for name, (left, right) in comparison_specs.items()
        if left in runs and right in runs
    }
    conclusions: dict[str, str] = {}
    if "B4_vs_B3" in comparisons:
        delta = comparisons["B4_vs_B3"]["success_difference"]["mean_difference"]
        conclusions["H1_INDEXED_RETRIEVAL"] = "QUALITY_NON_INFERIOR" if delta is not None and delta >= -0.05 else "NOT_PROVEN"
    if "B4_vs_B2" in comparisons:
        delta = comparisons["B4_vs_B2"]["success_difference"]["mean_difference"]
        optimized = summaries["B4_OPTIMIZED_CGNK_RC"]["context_chars_p50"]
        flat = summaries["B2_FLAT_CONTEXT_CHEAP"]["context_chars_p50"]
        reduction = None if not isinstance(flat, (int, float)) or not flat else 1.0 - float(optimized) / float(flat)
        comparisons["B4_vs_B2"]["median_context_reduction"] = reduction
        conclusions["H2_LOCALIZED_CONTEXT"] = (
            "SUPPORTED" if delta is not None and delta >= -0.05 and reduction is not None and reduction >= 0.30 else "NOT_PROVEN"
        )
    return {
        "schema_version": "1.0",
        "kind": "CGKNRelease056StatisticalAnalysis",
        "seed": SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "price_snapshot_hash": canonical_hash(pricing),
        "summaries": summaries,
        "comparisons": comparisons,
        "conclusions": conclusions,
        "limitations": [
            "One execution per task does not estimate provider nondeterminism.",
            "Paired intervals are directional evidence and do not imply broad population validity.",
            "Unknown provider usage yields null cost rather than zero.",
        ],
    }


def _write_outputs(output: pathlib.Path, result: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "statistics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    summaries = list(result["summaries"].values())
    fields = list(summaries[0]) if summaries else ["baseline"]
    with (output / "normalized_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    width, height = 760, 380
    maximum = max((float(row.get("success_rate") or 0) for row in summaries), default=1.0) or 1.0
    bars: list[str] = []
    for index, row in enumerate(summaries):
        x = 80 + index * 130
        value = float(row.get("success_rate") or 0)
        bar_height = 240 * value / maximum
        y = 300 - bar_height
        label = str(row["baseline"]).replace("&", "&amp;")
        bars.extend((
            f'<rect x="{x}" y="{y:.2f}" width="80" height="{bar_height:.2f}" fill="#2f6f9f"/>',
            f'<text x="{x + 40}" y="{y - 8:.2f}" text-anchor="middle" font-size="12">{value:.3f}</text>',
            f'<text x="{x + 40}" y="320" text-anchor="middle" font-size="9">{label}</text>',
        ))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/><text x="20" y="28" font-size="18">CGNK Release 056 holdout success</text>'
        '<line x1="60" y1="300" x2="730" y2="300" stroke="black"/>' + "".join(bars) + "</svg>\n"
    )
    (output / "success_rate.svg").write_text(svg, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize and analyze frozen ITER-056 holdout runs")
    parser.add_argument("--run", action="append", default=[], metavar="BASELINE=INDEX_JSON")
    parser.add_argument("--pricing", type=pathlib.Path, default=ROOT / "research" / "release-056" / "model_pricing_snapshot.json")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    runs: dict[str, Mapping[str, Any]] = {}
    for item in args.run:
        if "=" not in item:
            parser.error("--run must be BASELINE=INDEX_JSON")
        name, raw_path = item.split("=", 1)
        if name not in BASELINES:
            parser.error(f"unknown baseline: {name}")
        value = json.loads(pathlib.Path(raw_path).read_text(encoding="utf-8"))
        if value.get("baseline") != name:
            parser.error(f"baseline mismatch for {name}")
        if not args.allow_incomplete and (value.get("task_count") != 72 or value.get("completed_count") != 72):
            parser.error(f"formal run {name} must contain 72 completed tasks")
        runs[name] = value
    if not args.allow_incomplete and set(runs) != set(BASELINES):
        parser.error("formal analysis requires all five preregistered baselines")
    pricing = json.loads(args.pricing.read_text(encoding="utf-8"))
    result = analyze(runs, pricing)
    source_commit, source_tree = _git_identity()
    result.update({"source_commit": source_commit, "source_tree": source_tree})
    result["analysis_hash"] = canonical_hash(result)
    _write_outputs(args.output.resolve(), result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"release-056-analysis: PASS ({len(runs)} baselines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
