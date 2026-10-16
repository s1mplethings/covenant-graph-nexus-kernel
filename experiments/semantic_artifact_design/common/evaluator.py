from __future__ import annotations

from typing import Any, Mapping


def score(row: Mapping[str, Any]) -> dict[str, Any]:
    cli_rate = int(row["cli_success_count"]) / max(3, int(row["cli_run_count"]))
    repair_pass = row["repair"] == "PASS"
    functional = round(20 * cli_rate + 10 * int(repair_pass) + 5 * float(row["hidden_acceptance_rate"]), 2)
    interface = max(0, 20 - 5 * int(row["interface_violations"]) - 20 * int(row["accepted_breaking_changes"]))
    calls = int(row["provider_calls"]); tokens = int(row["tokens"]); wall = int(row["wall_time_ms"])
    efficiency = (5 if calls <= 20 else 3 if calls <= 35 else 1) + (5 if tokens <= 200000 else 3 if tokens <= 400000 else 1) + (3 if wall <= 1_200_000 else 1) + (1 if int(row["agent_calls"]) <= 16 else 0) + (1 if int(row["repair_rounds"]) <= 8 else 0)
    locality = 4 * int(int(row["whole_replans"]) == 0) + 3 * int(repair_pass) + 2 * int(int(row["worker_calls"]) <= 20) + int(int(row["repair_rounds"]) <= 8)
    robustness = 5 * int(bool(row["schema_pass"])) + 5 * int(bool(row["fake_pass"]))
    complexity = row["code_complexity"]
    core_types = int(complexity["core_types"])
    generality = (3 if core_types <= 4 else 1) + (2 if int(complexity["schema_count"]) <= 12 else 0) + ({"A": 2, "B": 4, "C": 4}[str(row["design"])]) + (1 if str(row["design"]) == "C" else 0)
    components = {"functional_reliability": functional, "interface_stability": interface, "efficiency": efficiency,
                  "repair_locality": locality, "schema_robustness": robustness, "generality_complexity": generality}
    disqualifications = []
    if not row["schema_pass"]: disqualifications.append("schema validation or determinism failed")
    if int(row["accepted_breaking_changes"]): disqualifications.append("breaking interface change was accepted")
    if int(row["whole_replans"]): disqualifications.append("repair performed a whole-project replan")
    if int(row["manual_edits"]): disqualifications.append("candidate received manual edits")
    if int(row["cli_success_count"]) < 2 or int(row["cli_run_count"]) < 3: disqualifications.append("CLI repeatability below 2/3")
    if not repair_pass: disqualifications.append("seeded repair did not PASS")
    if float(row["hidden_acceptance_rate"]) < 1.0: disqualifications.append("hidden acceptance was not PASS for every successful-target run")
    return dict(row) | {"score_components": components, "score": round(sum(components.values()), 2),
                        "qualified": not disqualifications, "disqualifications": disqualifications}


def select(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [score(row) for row in rows]
    eligible = sorted((row for row in scored if row["qualified"]), key=lambda item: (-float(item["score"]), str(item["design"])))
    return {"designs": scored, "winner": eligible[0]["design"] if eligible else "NONE", "runner_up": eligible[1]["design"] if len(eligible) > 1 else "NONE"}
