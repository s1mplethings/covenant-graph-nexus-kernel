from __future__ import annotations

from statistics import mean
from typing import Any, Mapping


def aggregate(design: str, receipts: list[Mapping[str, Any]], complexity: Mapping[str, int], *, schema_pass: bool, fake_pass: bool) -> dict[str, Any]:
    cli = [item for item in receipts if item.get("profile") == "repeat" and item.get("case_id") == "cli_csv_cleaner"]
    single = [item for item in receipts if item.get("profile") == "live-single"]
    repair = [item for item in receipts if item.get("profile") == "live-repair"]
    relevant = cli + repair
    def total(key: str) -> int:
        return sum(int(item.get(key, 0)) for item in relevant)
    hidden_pass = sum(item.get("hidden_acceptance") == "PASS" for item in relevant)
    return {"design": design, "cli_single": single[-1].get("final_status", "NOT_EVALUATED") if single else "NOT_EVALUATED",
            "repair": repair[-1].get("final_status", "NOT_EVALUATED") if repair else "NOT_EVALUATED",
            "cli_repeat": f"{sum(item.get('final_status') == 'PASS' for item in cli)}/{len(cli)}" if cli else "NOT_EVALUATED",
            "cli_success_count": sum(item.get("final_status") == "PASS" for item in cli), "cli_run_count": len(cli),
            "success_rate": (sum(item.get("final_status") == "PASS" for item in relevant) / len(relevant)) if relevant else 0.0,
            "hidden_acceptance_rate": hidden_pass / len(relevant) if relevant else 0.0,
            "interface_violations": total("interface_violations"), "accepted_breaking_changes": total("accepted_breaking_changes"),
            "agent_calls": total("agent_calls"), "worker_calls": total("worker_calls"), "provider_calls": total("provider_calls"),
            "tokens": total("tokens"), "wall_time_ms": total("wall_time_ms"), "repair_rounds": total("repair_rounds"),
            "whole_replans": total("whole_replans"), "manual_edits": total("manual_edits"),
            "average_context_chars": int(mean([int(item.get("context_chars", 0)) for item in relevant])) if relevant else 0,
            "schema_pass": schema_pass, "fake_pass": fake_pass, "code_complexity": dict(complexity)}
