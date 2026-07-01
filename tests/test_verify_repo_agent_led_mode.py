from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_verify_repo_defaults_to_agent_led_mode() -> None:
    text = (ROOT / "scripts" / "verify_repo.ps1").read_text(encoding="utf-8", errors="replace")

    assert '[string]$Mode = "agent-led"' in text
    assert 'scripts/run_agent_led_verify.py' in text
    assert 'scripts/run_formal_live_delivery_closure.py' in text
    assert '$Mode -eq "closure"' in text
