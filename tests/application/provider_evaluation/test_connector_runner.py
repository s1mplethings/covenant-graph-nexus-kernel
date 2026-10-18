from __future__ import annotations

import pathlib

from scripts.run_provider_benchmarks import _connector_registry


ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_connector_registry_identity_is_credential_free_and_stable() -> None:
    registry, config_hash, models, modes = _connector_registry(
        ["deepseek", "grok"],
        ROOT / "config/provider_connections",
    )
    assert registry.provider_ids == frozenset({"deepseek", "grok"})
    assert config_hash.startswith("sha256:")
    assert models == {"deepseek": "deepseek-flash", "grok": "grok-4.7"}
    assert modes == {
        "deepseek": "PROMPT_JSON_LOCAL_VALIDATE",
        "grok": "NATIVE_JSON_SCHEMA",
    }
