from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import canonical_hash


@dataclass(frozen=True)
class LatencySnapshot:
    key: str
    successful_seconds: tuple[float, ...]
    first_progress_seconds: tuple[float, ...]
    idle_gaps_seconds: tuple[float, ...]
    hard_limit_terminations: int
    transport_failures: int
    profile_version: str = "1.0"

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "successful_seconds": list(self.successful_seconds),
                "first_progress_seconds": list(self.first_progress_seconds), "idle_gaps_seconds": list(self.idle_gaps_seconds),
                "hard_limit_terminations": self.hard_limit_terminations, "transport_failures": self.transport_failures,
                "profile_version": self.profile_version}

    def historical_adjustment(self, *, base: int, hard_limit: int) -> int:
        if len(self.successful_seconds) < 3:
            return 0
        values = sorted(self.successful_seconds)
        p90 = values[max(0, math.ceil(len(values) * 0.9) - 1)]
        return max(0, min(hard_limit - base, math.ceil(p90 * 1.2) - base))


class ProviderLatencyProfileStore:
    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        self.path = pathlib.Path(path).resolve() if path else None
        self._data: dict[str, dict[str, Any]] = {}
        if self.path and self.path.is_file():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = dict(loaded.get("profiles", {}))

    @staticmethod
    def key(provider_id: str, actual_model: str, task_class: str, policy_id: str) -> str:
        return "|".join((provider_id, actual_model, task_class, policy_id))

    def freeze(self, provider_id: str, actual_model: str, task_class: str, policy_id: str) -> LatencySnapshot:
        key = self.key(provider_id, actual_model, task_class, policy_id)
        row = dict(self._data.get(key, {}))
        return LatencySnapshot(key, tuple(row.get("successful_seconds", ())), tuple(row.get("first_progress_seconds", ())),
                               tuple(row.get("idle_gaps_seconds", ())), int(row.get("hard_limit_terminations", 0)),
                               int(row.get("transport_failures", 0)))

    def record(self, snapshot: LatencySnapshot, *, success_seconds: float | None = None,
               first_progress_seconds: float | None = None, idle_gap_seconds: float | None = None,
               hard_limit: bool = False, transport_failure: bool = False) -> None:
        row = dict(self._data.get(snapshot.key, {}))
        for field, value in (("successful_seconds", success_seconds), ("first_progress_seconds", first_progress_seconds), ("idle_gaps_seconds", idle_gap_seconds)):
            values = list(row.get(field, ()))
            if value is not None:
                values.append(float(value))
            row[field] = values[-100:]
        row["hard_limit_terminations"] = int(row.get("hard_limit_terminations", 0)) + int(hard_limit)
        row["transport_failures"] = int(row.get("transport_failures", 0)) + int(transport_failure)
        self._data[snapshot.key] = row
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            value = {"kind": "ProviderLatencyProfiles", "schema_version": "1.0", "profiles": self._data, "contains_credentials": False}
            self.path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

