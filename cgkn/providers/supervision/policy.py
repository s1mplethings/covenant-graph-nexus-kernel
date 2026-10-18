from __future__ import annotations

import math
from types import MappingProxyType
from typing import Iterable

from .contracts import ProviderOperationPolicy, ProviderRequestComplexity, SupervisionMode


_POLICIES = (
    ("connection.probe", 15, 45, 20, 60, 45, 0, 0, 90, 128),
    ("benchmark.micro", 15, 75, 25, 90, 75, 15, 2, 120, 4096),
    ("project.domain.simple", 20, 120, 45, 140, 120, 45, 3, 300, 7000),
    ("project.domain.persistent", 20, 150, 45, 180, 150, 60, 3, 360, 7000),
    ("project.domain.library", 20, 120, 45, 150, 120, 45, 3, 300, 7000),
    ("repository.patch", 20, 90, 35, 120, 90, 40, 2, 240, 6000),
    ("project.repair", 20, 90, 35, 120, 90, 40, 2, 240, 3000),
    ("capability.build", 20, 120, 45, 160, 120, 50, 3, 330, 7000),
)


class ProviderOperationPolicyRegistry:
    def __init__(self, policies: Iterable[ProviderOperationPolicy] | None = None) -> None:
        source = tuple(policies) if policies is not None else tuple(
            ProviderOperationPolicy(f"{name}@1", name, "STRUCTURED_COMPLETION",
                                    SupervisionMode.CHUNK_AWARE, connect, first, idle, base,
                                    minimum, extension, count, hard, tokens)
            for name, connect, first, idle, base, minimum, extension, count, hard, tokens in _POLICIES
        )
        values = {policy.task_class: policy for policy in source}
        if len(values) != len(source):
            raise ValueError("operation policy task classes must be unique")
        self._policies = MappingProxyType(values)

    def get(self, task_class: str, operation: str = "STRUCTURED_COMPLETION") -> ProviderOperationPolicy:
        normalized = "benchmark.micro" if task_class in {"provider.benchmark", "benchmark.micro"} else task_class
        try:
            policy = self._policies[normalized]
        except KeyError:
            policy = self._policies["project.domain.simple"]
        if operation == policy.operation:
            return policy
        return ProviderOperationPolicy(**{**policy.__dict__, "operation": operation})

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {key: value.as_dict() for key, value in self._policies.items()}


class DeadlineEstimatorV1:
    version = "deadline-estimator-v1"

    def estimate(self, policy: ProviderOperationPolicy, complexity: ProviderRequestComplexity,
                 historical_adjustment: int = 0) -> int:
        size_units = math.ceil((complexity.system_chars + complexity.user_chars + complexity.schema_chars + complexity.current_source_chars) / 8000)
        output_units = math.ceil(complexity.requested_output_tokens / 1000)
        estimated = (policy.base_deadline_seconds + min(60, size_units * 10)
                     + min(40, complexity.target_file_count * 10)
                     + min(90, output_units * 12) + max(0, int(historical_adjustment)))
        return max(policy.min_deadline_seconds, min(policy.hard_limit_seconds, estimated))

