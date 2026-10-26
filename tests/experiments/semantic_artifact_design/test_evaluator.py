from experiments.semantic_artifact_design.common.evaluator import score, select


def row(design="C", cli=3, repair="PASS", hidden=1.0):
    return {"design": design, "cli_single": "PASS", "repair": repair, "cli_repeat": f"{cli}/3", "cli_success_count": cli, "cli_run_count": 3,
            "success_rate": 1.0, "hidden_acceptance_rate": hidden, "interface_violations": 0, "accepted_breaking_changes": 0,
            "agent_calls": 4, "worker_calls": 10, "provider_calls": 14, "tokens": 100000, "wall_time_ms": 600000,
            "repair_rounds": 1, "whole_replans": 0, "manual_edits": 0, "average_context_chars": 1000,
            "schema_pass": True, "fake_pass": True, "code_complexity": {"core_types": 4, "schema_count": 10}}


def test_qualification_is_hard_gated_not_best_effort():
    qualified = score(row())
    assert qualified["qualified"] is True and qualified["score"] <= 100
    assert score(row(cli=1))["qualified"] is False
    assert score(row(repair="FAIL"))["qualified"] is False
    assert score(row(hidden=0.75))["qualified"] is False


def test_no_qualified_design_selects_none():
    result = select([row("A", cli=0, repair="FAIL"), row("B", cli=1, repair="FAIL")])
    assert result["winner"] == "NONE"
