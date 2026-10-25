from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("analyze_release_056", ROOT / "scripts" / "analyze_release_056.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _run(name: str, successes: tuple[bool, ...], contexts: tuple[int, ...]) -> dict:
    return {
        "baseline": name,
        "batch_id": "synthetic",
        "rows": [
            {
                "case_id": f"C{index}", "status": "PASS" if success else "FAIL", "success": success,
                "context_chars": context, "input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                "cached_tokens": 0, "elapsed_ms": 10, "model": "deepseek-flash",
            }
            for index, (success, context) in enumerate(zip(successes, contexts), start=1)
        ],
    }


def _pricing() -> dict:
    return {
        "models": [{"model": "deepseek-flash", "input_price": 0.30, "output_price": 1.20, "cache_hit_input_price": 0.006}],
    }


def test_bootstrap_and_mcnemar_are_deterministic() -> None:
    first = MODULE.paired_bootstrap_interval([1, 1, 0, 1], [1, 0, 0, 0], resamples=1000)
    second = MODULE.paired_bootstrap_interval([1, 1, 0, 1], [1, 0, 0, 0], resamples=1000)
    assert first == second
    assert first["mean_difference"] == 0.5
    assert MODULE.mcnemar_exact([True, True, False], [True, False, True]) == {
        "left_only_success": 1,
        "right_only_success": 1,
        "discordant": 2,
        "p_value_two_sided": 1.0,
    }


def test_cost_and_unknown_usage_are_not_conflated_with_zero() -> None:
    prices = MODULE._price_by_model(_pricing())
    assert MODULE.row_cost({"model": "deepseek-flash", "input_tokens": 100, "output_tokens": 10, "cached_tokens": 0}, prices) == 0.000042
    assert MODULE.row_cost({"model": "deepseek-flash", "input_tokens": None, "output_tokens": None}, prices) is None


def test_analysis_applies_frozen_quality_and_context_gates() -> None:
    runs = {
        "B2_FLAT_CONTEXT_CHEAP": _run("B2_FLAT_CONTEXT_CHEAP", (True, True, True, False), (1000, 1000, 1000, 1000)),
        "B3_CURRENT_CGNK_BASELINE": _run("B3_CURRENT_CGNK_BASELINE", (True, True, True, False), (200, 200, 200, 200)),
        "B4_OPTIMIZED_CGNK_RC": _run("B4_OPTIMIZED_CGNK_RC", (True, True, True, False), (100, 100, 100, 100)),
    }
    result = MODULE.analyze(runs, _pricing())
    assert result["conclusions"]["H1_INDEXED_RETRIEVAL"] == "QUALITY_NON_INFERIOR"
    assert result["conclusions"]["H2_LOCALIZED_CONTEXT"] == "SUPPORTED"
    assert result["comparisons"]["B4_vs_B2"]["median_context_reduction"] == 0.9
