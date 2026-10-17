from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import replace
from typing import Iterable, Sequence

from .contracts import (
    ProviderBenchmarkReceipt,
    ProviderCapabilityProfile,
    ProviderSelectionDecision,
    RunProviderRoutingSnapshot,
    canonical_hash,
)


SELECTION_POLICY_VERSION = "provider-selection-v1"
TIE_MARGIN = 0.01


def _rate(rows: Sequence[ProviderBenchmarkReceipt], field: str) -> float:
    return round(sum(bool(getattr(row, field)) for row in rows) / len(rows), 6)


def _numeric(values: Iterable[object]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def aggregate_profiles(
    receipts: Sequence[ProviderBenchmarkReceipt],
    *,
    benchmark_suite_hash: str,
    selection_policy_version: str = SELECTION_POLICY_VERSION,
    minimum_samples: int = 2,
) -> tuple[ProviderCapabilityProfile, ...]:
    grouped: dict[tuple[str, str, str, str, str], list[ProviderBenchmarkReceipt]] = {}
    for receipt in receipts:
        key = (
            receipt.provider_id,
            receipt.actual_model,
            receipt.task_class,
            receipt.benchmark_version,
            receipt.gateway_config_hash,
        )
        grouped.setdefault(key, []).append(receipt)
    profiles: list[ProviderCapabilityProfile] = []
    for (provider_id, actual_model, task_class, benchmark_version, gateway_hash), rows in sorted(grouped.items()):
        repair_rows = [row for row in rows if row.repair_required]
        reasons: list[str] = []
        if len(rows) < minimum_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
        if not all(row.schema_valid for row in rows):
            reasons.append("SCHEMA_COMPLIANCE_BELOW_100_PERCENT")
        if not all(row.scope_valid for row in rows):
            reasons.append("SCOPE_VIOLATION")
        if not all(row.interface_valid for row in rows):
            reasons.append("INTERFACE_VIOLATION")
        if not all(row.secret_safe for row in rows):
            reasons.append("SECRET_OR_ERROR_LEAKAGE")
        tokens = _numeric(row.total_tokens for row in rows)
        costs = _numeric(row.cost_estimate for row in rows)
        failures = Counter(row.error_class for row in rows if row.error_class != "NONE")
        provisional = ProviderCapabilityProfile(
            provider_id=provider_id,
            actual_model=actual_model,
            task_class=task_class,
            samples=len(rows),
            functional_success_rate=_rate(rows, "functional_valid"),
            schema_success_rate=_rate(rows, "schema_valid"),
            interface_success_rate=_rate(rows, "interface_valid"),
            scope_success_rate=_rate(rows, "scope_valid"),
            repair_success_rate=_rate(repair_rows, "functional_valid") if repair_rows else 1.0,
            median_tokens=round(statistics.median(tokens), 3) if tokens else "UNAVAILABLE",
            median_cost=round(statistics.median(costs), 8) if costs else "UNAVAILABLE",
            median_latency=round(statistics.median(row.wall_time_ms for row in rows), 3),
            failure_classes=dict(sorted(failures.items())),
            last_benchmark_version=benchmark_version,
            gateway_config_hash=gateway_hash,
            benchmark_suite_hash=benchmark_suite_hash,
            selection_policy_version=selection_policy_version,
            eligible=not reasons,
            ineligible_reasons=tuple(reasons),
        )
        profiles.append(replace(provisional, profile_hash=canonical_hash(provisional.as_dict(include_hash=False))))
    return tuple(profiles)


def _efficiency(value: float | str, best: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0.0
    return 1.0 if value <= 0 and best <= 0 else (best / float(value) if value > 0 else 0.0)


class ProviderSelector:
    def __init__(self, profiles: Sequence[ProviderCapabilityProfile], *, policy_version: str = SELECTION_POLICY_VERSION):
        self.profiles = tuple(profiles)
        self.policy_version = policy_version

    def select(self, task_class: str) -> ProviderSelectionDecision:
        eligible = [profile for profile in self.profiles if profile.task_class == task_class and profile.eligible]
        if not eligible:
            raise RuntimeError(f"PROVIDER_SELECTION_NEEDS_REWORK: no eligible Provider for {task_class}")
        # Reliability is a primary ordering constraint, not merely one weighted term.
        best_functional = max(row.functional_success_rate for row in eligible)
        reliable = [row for row in eligible if row.functional_success_rate == best_functional]
        if task_class == "worker.repair":
            best_repair = max(row.repair_success_rate for row in reliable)
            reliable = [row for row in reliable if row.repair_success_rate == best_repair]
        token_values = [float(row.median_tokens) for row in eligible if isinstance(row.median_tokens, (int, float))]
        cost_values = [float(row.median_cost) for row in eligible if isinstance(row.median_cost, (int, float))]
        latency_best = min(row.median_latency for row in eligible)
        token_best = min(token_values) if token_values else 0.0
        cost_best = min(cost_values) if cost_values else 0.0
        scored: list[tuple[ProviderCapabilityProfile, float]] = []
        for row in reliable:
            metrics = {
                "functional": (0.45, row.functional_success_rate),
                "repair": (0.15, row.repair_success_rate),
                "integrity": (0.15, min(row.interface_success_rate, row.scope_success_rate)),
                "tokens": (0.10, _efficiency(row.median_tokens, token_best)),
                "latency": (0.07, _efficiency(row.median_latency, latency_best)),
            }
            if cost_values and isinstance(row.median_cost, (int, float)):
                metrics["cost"] = (0.08, _efficiency(row.median_cost, cost_best))
            total_weight = sum(weight for weight, _ in metrics.values())
            score = sum(weight * value for weight, value in metrics.values()) / total_weight
            scored.append((row, round(score, 6)))
        top_score = max(score for _, score in scored)
        tied = [(row, score) for row, score in scored if top_score - score < TIE_MARGIN]
        tied.sort(key=lambda item: (
            float(item[0].median_cost) if isinstance(item[0].median_cost, (int, float)) else float("inf"),
            float(item[0].median_tokens) if isinstance(item[0].median_tokens, (int, float)) else float("inf"),
            item[0].median_latency,
            item[0].provider_id,
        ))
        winner, score = tied[0]
        ordered_scores = sorted((value for _, value in scored), reverse=True)
        gap = ordered_scores[0] - ordered_scores[1] if len(ordered_scores) > 1 else 0.0
        confidence = "HIGH" if len(eligible) >= 2 and gap >= 0.05 else ("MEDIUM" if len(eligible) >= 2 else "LOW")
        cost_text = winner.median_cost if isinstance(winner.median_cost, (int, float)) else "UNAVAILABLE"
        reason = (
            f"selected by task-specific evidence: functional={winner.functional_success_rate:.3f}, "
            f"repair={winner.repair_success_rate:.3f}, interface={winner.interface_success_rate:.3f}, "
            f"scope={winner.scope_success_rate:.3f}, median_tokens={winner.median_tokens}, "
            f"median_cost={cost_text}, median_latency_ms={winner.median_latency}"
        )
        return ProviderSelectionDecision(
            task_class=task_class,
            selected_provider=winner.provider_id,
            eligible_providers=tuple(sorted(row.provider_id for row in eligible)),
            profile_refs={row.provider_id: row.profile_hash for row in sorted(eligible, key=lambda item: item.provider_id)},
            score=score,
            confidence=confidence,
            reason=reason,
            benchmark_version=winner.last_benchmark_version,
            selection_policy_version=self.policy_version,
        )

    def freeze(self, run_id: str, task_classes: Sequence[str]) -> RunProviderRoutingSnapshot:
        decisions = [self.select(task_class) for task_class in task_classes]
        versions = {decision.benchmark_version for decision in decisions}
        if len(versions) != 1:
            raise RuntimeError("routing snapshot cannot mix benchmark versions")
        return RunProviderRoutingSnapshot(
            run_id=run_id,
            routes={decision.task_class: decision.selected_provider for decision in decisions},
            profile_hashes={decision.task_class: decision.profile_refs[decision.selected_provider] for decision in decisions},
            selection_scores={decision.task_class: decision.score for decision in decisions},
            benchmark_version=next(iter(versions)),
            selection_policy_version=self.policy_version,
        )
