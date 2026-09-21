from __future__ import annotations

from collections import defaultdict
from typing import Any


class EffectConstraintViolation(RuntimeError):
    pass


class EffectCounter:
    def __init__(self, constraints: list[dict[str, Any]]):
        self.constraints = constraints
        self.counts: dict[tuple[str, str, str], int] = defaultdict(int)

    def consume(self, effect: str, amount: int, *, node_id: str, phase: str = "", turn: str = "", run: str = "run") -> None:
        if amount <= 0:
            return
        scope_ids = {"node": node_id, "phase": phase or node_id, "turn": turn or run, "run": run}
        for constraint in self.constraints:
            if constraint.get("effect") != effect:
                continue
            scope = str(constraint["scope"])
            key = (effect, scope, scope_ids[scope])
            proposed = self.counts[key] + amount
            if proposed > int(constraint["max"]):
                raise EffectConstraintViolation(
                    f"effect {effect} exceeds {scope} maximum {constraint['max']} at {scope_ids[scope]}"
                )
            self.counts[key] = proposed

    def consume_declared(self, effects: dict[str, Any], *, node_id: str, phase: str = "", run: str = "run") -> None:
        amounts = {
            "network": int(bool(effects.get("network"))),
            "provider_call": int(bool(effects.get("provider_call"))),
            "fs_read": len(effects.get("fs_read", [])),
            "fs_write": len(effects.get("fs_write", [])),
            "db_write": int(effects.get("db_write", 0) or 0),
        }
        for effect, amount in amounts.items():
            self.consume(effect, amount, node_id=node_id, phase=phase, run=run)
