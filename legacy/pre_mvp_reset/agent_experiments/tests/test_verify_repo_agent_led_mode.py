from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_verify_repo_defaults_to_agent_led_mode() -> None:
    text = (ROOT / "scripts" / "verify_repo.ps1").read_text(encoding="utf-8", errors="replace")

    assert '[string]$Mode = "agent-led"' in text
    assert 'scripts/run_agent_led_verify.py' in text
    assert 'scripts/run_formal_live_delivery_closure.py' in text
    assert '$Mode -eq "closure"' in text


def test_verify_repo_quick_profile_reuses_profile_runner() -> None:
    text = (ROOT / "scripts" / "verify_repo.ps1").read_text(encoding="utf-8", errors="replace")

    assert '[string]$Profile = ""' in text
    assert "scripts/run_test_profile.py --profile $Profile" in text
    assert "$profileTimeout = if ($Timeout -eq 900) { 300 } else { $Timeout }" in text
