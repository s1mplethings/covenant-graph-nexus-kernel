from __future__ import annotations

import json
from pathlib import Path

import pytest

from cgkn_provider_lab.models import ConfigurationError, ProviderConfig
from cgkn_provider_lab.storage import ProviderConfigStore


def provider(provider_id: str = "alpha") -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        display_name=provider_id.title(),
        base_url="https://example.com/v1",
        model="model-a",
        secret_backend="environment",
        secret_ref=f"{provider_id.upper()}_API_KEY",
    )


def test_store_round_trip_is_metadata_only(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    store = ProviderConfigStore(path)
    store.save([provider("beta"), provider("alpha")])
    text = path.read_text(encoding="utf-8")
    assert "actual-secret" not in text
    assert [item.provider_id for item in store.load()] == ["alpha", "beta"]


def test_store_rejects_embedded_key(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        **provider().to_dict(),
                        "api_key": "leak",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="plaintext credential"):
        ProviderConfigStore(path).load()


def test_store_rejects_duplicate_ids(tmp_path: Path) -> None:
    store = ProviderConfigStore(tmp_path / "providers.json")
    with pytest.raises(ConfigurationError, match="unique"):
        store.save([provider(), provider()])
