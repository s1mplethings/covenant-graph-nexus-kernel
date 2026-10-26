"""Chain-level paired statistics for ITER-058."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Mapping

from .essential_workload import BASELINES, FAMILIES, canonical_hash
from .runner import summarize_runs


def _bootstrap_difference(pairs: list[tuple[int, int]], *, seed: int = 58026, samples: int = 10_000) -> dict[str, float]:
    if not pairs:
        return {"difference_pp": 0.0, "ci95_low_pp": 0.0, "ci95_high_pp": 0.0}
    observed = 100.0 * sum(c - d for d, c in pairs) / len(pairs)
    rng = random.Random(seed)
    draws = sorted(
        100.0 * sum(pairs[index][1] - pairs[index][0] for index in (rng.randrange(len(pairs)) for _ in pairs)) / len(pairs)
        for _ in range(samples)
    )
    return {
        "difference_pp": round(observed, 3),
        "ci95_low_pp": round(draws[int(samples * 0.025)], 3),
        "ci95_high_pp": round(draws[min(samples - 1, int(samples * 0.975))], 3),
    }


def _mcnemar_exact(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    direct_only = sum(d == 1 and c == 0 for d, c in pairs)
    cgnk_only = sum(d == 0 and c == 1 for d, c in pairs)
    discordant = direct_only + cgnk_only
    if not discordant:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(0, min(direct_only, cgnk_only) + 1)) / (2 ** discordant)
        p_value = min(1.0, 2.0 * tail)
    return {
        "direct_only": direct_only, "cgnk_only": cgnk_only,
        "discordant": discordant, "exact_two_sided_p": round(p_value, 6),
    }


def analyze(runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    summary = summarize_runs(runs)
    by_scenario: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in runs:
        by_scenario[str(row["scenario_id"])][str(row["baseline"])] = row
    comparisons: dict[str, Any] = {}
    family_results: dict[str, Any] = {}
    for direct in BASELINES[:2]:
        key = f"{direct}_VS_B2_CGNK_CURRENT"
        pairs = [
            (int(outcomes[direct]["chain_success"]), int(outcomes["B2_CGNK_CURRENT"]["chain_success"]))
            for outcomes in by_scenario.values()
            if direct in outcomes and "B2_CGNK_CURRENT" in outcomes
        ]
        comparisons[key] = {
            "chain_count": len(pairs),
            "paired_effect": _bootstrap_difference(pairs),
            "mcnemar": _mcnemar_exact(pairs),
            "interpretation": "DIRECTIONAL_SMALL_SAMPLE_NOT_STATISTICAL_PROOF",
        }
    for family in FAMILIES:
        rows = [row for row in runs if row["family"] == family]
        baseline_rows = {baseline: [row for row in rows if row["baseline"] == baseline] for baseline in BASELINES}
        family_results[family] = {
            baseline: {
                "chain_successes": sum(bool(row["chain_success"]) for row in subset),
                "chain_count": len(subset),
                "episode_successes": sum(int(row["episode_successes"]) for row in subset),
                "episode_count": sum(int(row["episode_count"]) for row in subset),
                "mean_context_chars": round(sum(int(row["context_chars"]) for row in subset) / max(1, len(subset)), 3),
                "mean_rework_count": round(sum(int(row["rework_count"]) for row in subset) / max(1, len(subset)), 3),
            }
            for baseline, subset in baseline_rows.items()
        }
    return {
        "kind": "CGNKEssentialFormalAnalysis", "schema_version": "1.0",
        "summary": summary, "comparisons": comparisons,
        "family_results": family_results,
        "analysis_hash": canonical_hash({"comparisons": comparisons, "family_results": family_results}),
        "limitations": [
            "Scenario chain is the primary statistical unit.",
            "Episode observations within a chain are not treated as independent.",
            "Eighteen formal chains provide directional evidence, not statistical significance.",
            "Provider nondeterminism is not estimated by a single run per route and chain.",
        ],
    }
