from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ExecutionStrategy(str, Enum):
    DIRECT_AGENT = "DIRECT_AGENT"
    COMPOSED_DAG = "COMPOSED_DAG"


@dataclass(frozen=True)
class ExecutionStrategyDecision:
    strategy: ExecutionStrategy
    reasons: tuple[str, ...]
    estimated_source_files: int
    work_unit_count: int
    decided_before_execution: bool = True
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNExecutionStrategyDecision", "schema_version": self.schema_version,
            "strategy": self.strategy.value, "reasons": list(self.reasons),
            "estimated_source_files": self.estimated_source_files, "work_unit_count": self.work_unit_count,
            "decided_before_execution": self.decided_before_execution,
        }


def decide_execution_strategy(*, source_files: int, work_units: int, long_lived_state: bool,
                              parallel_opportunity: bool, high_risk_effects: bool) -> ExecutionStrategyDecision:
    direct = source_files <= 5 and work_units <= 3 and not long_lived_state and not parallel_opportunity and not high_risk_effects
    reasons = (
        "bounded project with at most five source files",
        "no long-lived state or high-risk side effect",
        "no useful parallel opportunity",
    ) if direct else (
        "multiple independently verifiable work units or persistent state",
        "composition provides isolated failure and evidence domains",
    )
    return ExecutionStrategyDecision(ExecutionStrategy.DIRECT_AGENT if direct else ExecutionStrategy.COMPOSED_DAG, reasons, source_files, work_units)
