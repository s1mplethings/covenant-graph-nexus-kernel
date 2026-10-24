from __future__ import annotations

from scripts.run_self_growth_benchmarks import _strong_growth_benefit


def metrics(*, success: float, admitted: int, zero_reuse: float, internalization: float, cost: float) -> dict:
    return {
        "success_rate": success,
        "new_capabilities_admitted": admitted,
        "zero_reuse_capability_rate": zero_reuse,
        "capability_internalization_rate": internalization,
        "known_cost_cny": cost,
    }


def test_strong_growth_is_harmful_when_it_costs_more_and_increases_debt() -> None:
    g2 = metrics(success=0.97, admitted=16, zero_reuse=0.0, internalization=0.93, cost=0.025)
    g3 = metrics(success=0.99, admitted=20, zero_reuse=0.25, internalization=0.90, cost=0.102)

    assert _strong_growth_benefit(g2, g3) == "HARMFUL"


def test_strong_growth_requires_preserved_success_and_better_abstraction() -> None:
    g2 = metrics(success=0.97, admitted=16, zero_reuse=0.2, internalization=0.90, cost=0.025)
    g3 = metrics(success=0.96, admitted=12, zero_reuse=0.1, internalization=0.95, cost=0.08)

    assert _strong_growth_benefit(g2, g3) == "PROVEN_DIRECTIONALLY"
