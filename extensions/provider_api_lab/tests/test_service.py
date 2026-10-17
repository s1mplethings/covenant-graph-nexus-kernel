from __future__ import annotations

import json
from pathlib import Path

from cgkn_provider_lab.models import ComparisonOptions, ProviderConfig, ProviderResult
from cgkn_provider_lab.secrets import SecretManager
from cgkn_provider_lab.service import ProviderComparisonService


class EchoAdapter:
    def invoke(self, provider, credential, prompt, options):
        return ProviderResult(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            model=provider.model,
            status="ok",
            text=f"{provider.provider_id}:{prompt}",
            latency_ms=1,
            total_tokens=2,
        )


def provider(provider_id: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        display_name=provider_id.title(),
        base_url="https://example.com/v1",
        model="model-a",
        secret_backend="session",
        secret_ref=provider_id,
    )


def test_compare_preserves_selection_order() -> None:
    manager = SecretManager.create_default()
    items = [provider("beta"), provider("alpha")]
    for item in items:
        manager.set_for_provider(item, f"secret-{item.provider_id}")
    service = ProviderComparisonService(manager, {"openai_chat": EchoAdapter()})
    results = service.compare(items, "prompt", ComparisonOptions(max_concurrency=2))
    assert [result.provider_id for result in results] == ["beta", "alpha"]


def test_export_contains_no_credential_value_or_reference(tmp_path: Path) -> None:
    item = provider("alpha")
    manager = SecretManager.create_default()
    manager.set_for_provider(item, "credential-value-that-must-not-export")
    service = ProviderComparisonService(manager, {"openai_chat": EchoAdapter()})
    result = ProviderResult(
        provider_id="alpha",
        display_name="Alpha",
        model="model-a",
        status="error",
        text="answer",
        error="upstream reflected credential-value-that-must-not-export",
    )
    output = tmp_path / "result.json"
    service.export_results(
        output,
        [item],
        "prompt contains credential-value-that-must-not-export",
        ComparisonOptions(),
        [result],
    )
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert "secret_ref" not in payload["providers"][0]
    assert "secret_backend" not in payload["providers"][0]
    assert "session" not in text
    assert "credential-value-that-must-not-export" not in text
    assert "[REDACTED]" in text
