from __future__ import annotations

import json
import pathlib
from dataclasses import replace
from typing import Any, Mapping, Sequence

from .contracts import ProviderCapabilityProfile, canonical_hash


def profile_from_dict(value: Mapping[str, Any]) -> ProviderCapabilityProfile:
    profile = ProviderCapabilityProfile(
        provider_id=str(value["provider_id"]),
        actual_model=str(value["actual_model"]),
        task_class=str(value["task_class"]),
        samples=int(value["samples"]),
        functional_success_rate=float(value["functional_success_rate"]),
        schema_success_rate=float(value["schema_success_rate"]),
        interface_success_rate=float(value["interface_success_rate"]),
        scope_success_rate=float(value["scope_success_rate"]),
        repair_success_rate=float(value["repair_success_rate"]),
        median_tokens=value["median_tokens"],
        median_cost=value["median_cost"],
        median_latency=float(value["median_latency"]),
        failure_classes=dict(value.get("failure_classes", {})),
        last_benchmark_version=str(value["last_benchmark_version"]),
        gateway_config_hash=str(value["gateway_config_hash"]),
        benchmark_suite_hash=str(value["benchmark_suite_hash"]),
        selection_policy_version=str(value["selection_policy_version"]),
        eligible=bool(value["eligible"]),
        ineligible_reasons=tuple(value.get("ineligible_reasons", ())),
        profile_hash=str(value.get("profile_hash", "")),
    )
    expected = canonical_hash(profile.as_dict(include_hash=False))
    if profile.profile_hash != expected:
        raise ValueError("provider profile hash mismatch")
    return profile


class ProviderProfileCache:
    def __init__(self, path: pathlib.Path | str):
        self.path = pathlib.Path(path)

    def load(self) -> tuple[ProviderCapabilityProfile, ...]:
        if not self.path.is_file():
            return ()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("kind") != "ProviderCapabilityProfileCache" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported provider profile cache")
        return tuple(profile_from_dict(row) for row in value.get("profiles", ()))

    def find(self, key: tuple[str, str, str, str, str, str]) -> ProviderCapabilityProfile | None:
        return next((profile for profile in self.load() if profile.cache_key == key), None)

    def write(self, profiles: Sequence[ProviderCapabilityProfile]) -> pathlib.Path:
        ordered = sorted(profiles, key=lambda row: row.cache_key)
        value = {
            "kind": "ProviderCapabilityProfileCache",
            "schema_version": "1.0",
            "profiles": [row.as_dict() for row in ordered],
            "contains_credentials": False,
        }
        value["cache_hash"] = canonical_hash(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return self.path
