from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.cgnk_slim_rule_guard as guard


def _checks_by_name() -> dict[str, dict]:
    result = guard.run_checks(strict=False)
    return {check["name"]: check for check in result["checks"]}


def test_cgnk_slim_rule_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/cgnk_slim_rule_guard.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "PASS"


def test_all_hard_checks_pass_on_repo() -> None:
    result = guard.run_checks(strict=False)
    failing = [check["name"] for check in result["checks"] if not check["ok"]]
    assert result["ok"], failing


def test_generation_confirmation_forbidden_terms() -> None:
    # The forbidden list must cover every legacy/support generation entrypoint.
    for term in (
        "generate_project.py",
        "run_local_pipeline",
        "run_generation_subprocess",
        "run_generation_job",
        "run_agent_generation_job",
        "simulator",
    ):
        assert term in guard.FORBIDDEN_CONFIRMATION_TERMS, term

    checks = _checks_by_name()
    name = "generation confirmation dispatch stays thin"
    assert name in checks
    assert checks[name]["ok"]


def test_driver_check_present_and_ok() -> None:
    checks = _checks_by_name()
    name = "default generation dispatch marks api_provider_project_generation driver"
    assert name in checks
    assert checks[name]["ok"]


def test_delivery_gate_checks_present_and_ok() -> None:
    checks = _checks_by_name()
    for fn in ("send_delivery_from_manifest", "send_evidence_checkpoint"):
        name = f"{fn} delivers only through gate and emit"
        assert name in checks, name
        assert checks[name]["ok"], name


def test_legacy_marking_checks_present_and_ok() -> None:
    checks = _checks_by_name()
    bridge_name = "legacy wrapper functions in the bridge are marked LEGACY ONLY"
    assert bridge_name in checks
    assert checks[bridge_name]["ok"]
    # File-level legacy markers (present only when the wrapper files exist).
    for path, _markers in guard.LEGACY_WRAPPER_FILES:
        if (ROOT / path).exists():
            name = f"{path} is marked legacy-only"
            assert name in checks, name
            assert checks[name]["ok"], name


def test_public_suffix_whitelist_check() -> None:
    # Internal/text suffixes must never overlap the public media/package whitelist.
    assert not (set(guard.PUBLIC_SUFFIXES) & set(guard.INTERNAL_SUFFIXES))
    for suffix in (".md", ".json", ".jsonl", ".txt", ".log", ".yaml", ".yml", ".toml", ".ini"):
        assert suffix in guard.INTERNAL_SUFFIXES, suffix

    checks = _checks_by_name()
    name = "public delivery suffix whitelist is media/package only"
    assert name in checks
    assert checks[name]["ok"]


def test_provider_route_check_is_scoped_to_function_bodies() -> None:
    # The provider route check must read only the two provider job bodies,
    # not the whole bridge file.
    bridge = guard.read_text("scripts/telegram_live_bridge.py")
    body = guard.function_body(bridge, "run_provider_generation_job")
    assert "def run_provider_generation_job" in body
    assert "def run_agent_generation_job" not in body  # stops at next top-level def

    checks = _checks_by_name()
    name = "provider route is behind validation packager and gate"
    assert name in checks
    assert checks[name]["ok"]


def test_project_team_checks_present_and_ok() -> None:
    checks = _checks_by_name()
    for name in (
        "project team manager modules exist",
        "telegram default session carries active project state",
        "customer intents include project revision request",
        "telegram revision branch delegates out of bridge",
        "revision manifest records previous manifest",
        "revision delivery contract names packager and public gate",
        "revision failure does not promote current",
        "revision provider job is implemented",
        "revision execution keeps delivery contract",
        "revision docs declare phase 2 execution contract",
        "telegram bridge does not call provider revision job",
        "model defaults are centralized for bridge and connectivity",
        "local studio routes through MainAgentManager only",
        "model policy exposes required task profiles",
    ):
        assert name in checks, name
        assert checks[name]["ok"], name


def test_strict_mode_reports_existing_bloat_as_warning() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/cgnk_slim_rule_guard.py", "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "WARN:" in result.stdout


def test_strict_mode_fails_when_warnings_present() -> None:
    strict = guard.run_checks(strict=True)
    if strict["warnings"]:
        assert strict["ok"] is False
