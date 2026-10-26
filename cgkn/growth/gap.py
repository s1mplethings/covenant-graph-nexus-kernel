from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CapabilityGap:
    gap_id: str
    project_id: str
    run_id: str
    requested_capability: str
    required_inputs: tuple[str, ...]
    required_outputs: tuple[str, ...]
    required_effects: tuple[str, ...]
    reason: str
    requesting_node: str
    risk_ceiling: str
    created_at: str = field(default_factory=now)

    def as_dict(self) -> dict[str, object]:
        return {key: list(value) if isinstance(value, tuple) else value for key, value in self.__dict__.items()}
