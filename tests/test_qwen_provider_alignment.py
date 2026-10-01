from __future__ import annotations

import os
from unittest import mock

from scripts import check_connectivity


def test_shared_qwen_user_contract_beats_legacy_cgkn_account() -> None:
    registry = {
        ("QWEN_API_KEY", "User"): "placeholder-attune-qwen",
        ("QWEN_BASE_URL", "User"): "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ("CGKN_OPENAI_API_KEY", "User"): "placeholder-quota-key",
        ("CGKN_OPENAI_BASE_URL", "User"): "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        check_connectivity,
        "_windows_env_value",
        side_effect=lambda name, target: registry.get((name, target), ""),
    ):
        resolved = check_connectivity._resolve_api_credentials()

    assert resolved["api_key"] == "placeholder-attune-qwen"
    assert resolved["api_key_source"] == "QWEN_API_KEY(User)"
    assert resolved["base_url_source"] == "QWEN_BASE_URL(User)"
    assert "CGKN_OPENAI_API_KEY(User)" in resolved["api_key_conflict_sources"]


def test_missing_shared_and_compatibility_keys_fails_closed() -> None:
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        check_connectivity,
        "_windows_env_value",
        return_value="",
    ):
        resolved = check_connectivity._resolve_api_credentials()

    assert resolved["api_key"] == ""
    assert resolved["api_key_source"] == ""
