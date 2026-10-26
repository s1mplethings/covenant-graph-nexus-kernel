from __future__ import annotations

from typing import Any, Mapping


def markdown(comparison: Mapping[str, Any]) -> str:
    headers = ["Design", "CLI single", "Repair", "CLI repeat", "Success Rate", "Interface Violations", "Accepted Breaking Changes", "Agent Calls", "Worker Calls", "Provider Calls", "Tokens", "Wall Time", "Repair Rounds", "Whole Replans", "Code Complexity", "Schema Count", "Score", "Qualified", "Disqualification Reason"]
    lines = ["# Semantic Artifact Design Comparison", "", "| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in comparison["designs"]:
        values = [row["design"], row["cli_single"], row["repair"], row["cli_repeat"], f"{row['success_rate']:.2%}", row["interface_violations"], row["accepted_breaking_changes"], row["agent_calls"], row["worker_calls"], row["provider_calls"], row["tokens"], row["wall_time_ms"], row["repair_rounds"], row["whole_replans"], row["code_complexity"]["core_types"], row["code_complexity"]["schema_count"], row["score"], row["qualified"], "; ".join(row["disqualifications"])]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(["", f"Winner: **{comparison['winner']}**", f"Runner-up: **{comparison['runner_up']}**", ""])
    return "\n".join(lines)
