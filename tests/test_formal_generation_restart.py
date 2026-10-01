from scripts import codex_conversation


def test_terminal_failures_require_a_fresh_production_run() -> None:
    for status in ("REWORK_BLOCKED", "blocked", "FAILED", "error"):
        assert codex_conversation.formal_generation_requires_new_run(status)


def test_waiting_and_success_states_do_not_start_a_fresh_run() -> None:
    for status in (
        "waiting_surrogate_response",
        "waiting_requirement_replan",
        "running",
        "DELIVERED",
        "DELIVERED_WITH_WARNINGS",
    ):
        assert not codex_conversation.formal_generation_requires_new_run(status)
