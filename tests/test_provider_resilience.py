from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import provider_resilience


def config(backup_enabled: bool = False) -> dict:
    return {
        "providers": [
            {"name": "primary", "base_url": "", "models": {"small": "small", "large": "large"}, "quota_required": True},
            {"name": "backup", "base_url": "", "models": {"small": "backup-small", "large": "backup-large"}, "enabled": backup_enabled},
        ]
    }


def test_provider_quota_blocks_live_commercial_run() -> None:
    result = provider_resilience.provider_preflight(config(), probe=lambda provider: {"name": provider["name"], "status": provider_resilience.PROVIDER_QUOTA_EXCEEDED})

    assert result["status"] == "fail"
    assert result["verdict"] == provider_resilience.PROVIDER_QUOTA_EXCEEDED
    assert result["metadata"]["live_generation_allowed"] is False
    assert result["metadata"]["commercial_blocker"] == "provider_quota"


def test_provider_backup_selected_when_primary_quota_exceeded() -> None:
    def probe(provider: dict) -> dict:
        status = provider_resilience.PROVIDER_QUOTA_EXCEEDED if provider["name"] == "primary" else provider_resilience.PROVIDER_OK
        return {"name": provider["name"], "status": status}

    result = provider_resilience.provider_preflight(config(backup_enabled=True), probe=probe)

    assert result["status"] == "pass"
    assert result["metadata"]["selected_provider"]["name"] == "backup"
    assert result["metadata"]["fallback_used"] is True
    assert result["metadata"]["live_generation_allowed"] is True


def test_backup_provider_selected_when_configured_and_primary_quota_exceeded() -> None:
    def probe(provider: dict) -> dict:
        if provider["name"] == "primary":
            return {"name": "primary", "status": provider_resilience.PROVIDER_QUOTA_EXCEEDED}
        return {"name": "backup", "status": provider_resilience.PROVIDER_OK}

    result = provider_resilience.provider_preflight(config(backup_enabled=True), probe=probe)

    assert result["status"] == "pass"
    assert result["metadata"]["selected_provider"]["name"] == "backup"
    assert result["metadata"]["commercial_blocker"] == ""


def test_provider_transport_unstable_is_retryable_but_not_semantic_failure() -> None:
    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        raise TimeoutError("timeout")

    result = provider_resilience.retryable_provider_call(flaky, attempts=2, delay_seconds=0)

    assert result["status"] == "warning"
    assert result["verdict"] == provider_resilience.PROVIDER_TRANSPORT_UNSTABLE
    assert result["metadata"]["retryable"] is True
    assert calls["count"] == 2


def test_provider_health_report_written() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = pathlib.Path(temp_dir) / "provider_health_report.json"
        report = provider_resilience.provider_preflight(config(backup_enabled=True), probe=lambda provider: {"name": provider["name"], "status": provider_resilience.PROVIDER_OK})
        provider_resilience.write_health_report(report, path)

        loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded["metadata"]["selected_provider"]["name"] == "primary"


def test_provider_preflight_uses_live_connectivity_quota_report() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = pathlib.Path(temp_dir) / "connectivity_check_result.json"
        path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "api": {"live": True, "ok": False, "error": 'HTTP 403: {"error":"Key usage limit exceeded"}'},
                }
            ),
            encoding="utf-8",
        )
        cfg = {
            "providers": [
                {
                    "name": "primary",
                    "base_url": "",
                    "models": {"small": "small", "large": "large"},
                    "quota_required": True,
                    "connectivity_report": str(path),
                }
            ]
        }

        result = provider_resilience.provider_preflight(cfg)

    assert result["verdict"] == provider_resilience.PROVIDER_QUOTA_EXCEEDED
    assert result["metadata"]["live_generation_allowed"] is False


def test_primary_preflight_uses_canonical_provider_credentials(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        provider_resilience.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "configured-canonical-key", "base_url": "https://provider.example/v1"},
    )

    cfg = config()
    cfg["providers"][0]["connectivity_report"] = str(
        ROOT / "examples" / "test_results" / "nonexistent_connectivity_report.json"
    )

    result = provider_resilience.provider_preflight(cfg)

    assert result["verdict"] == provider_resilience.PROVIDER_OK
    assert result["metadata"]["live_generation_allowed"] is True
