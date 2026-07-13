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
    assert '"repo_default", "quick", "regression", "longrun", "provider", "e2e", "full_all", "all"' in text


def test_profile_runner_separates_repo_default_from_full_all() -> None:
    text = (ROOT / "scripts" / "run_test_profile.py").read_text(encoding="utf-8", errors="replace")

    assert '"repo_default": ""' in text
    assert '"full_all": ""' in text
    assert 'PROFILE_ALIASES = {"all": "full_all", "default": "repo_default"}' in text
    assert 'if profile == "full_all":' in text
    assert 'command.append("--run-profile-marked")' in text
