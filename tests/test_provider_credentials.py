from __future__ import annotations

import os
import pathlib
import tempfile
from unittest import mock

from scripts import check_connectivity, provider_credentials


RELEVANT_ENV = {
    "CGKN_OPENAI_API_KEY_OVERRIDE",
    "CGKN_OPENAI_BASE_URL_OVERRIDE",
    "CGKN_OPENAI_API_KEY",
    "CGKN_OPENAI_BASE_URL",
    "CGNK_OPENAI_API_KEY",
    "CGNK_OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "QWEN_API_KEY",
    "QWEN_BASE_URL",
    "CGKN_LOCAL_NOTES_PATH",
}


def clean_process_env(**values: str):
    environment = {key: value for key, value in os.environ.items() if key not in RELEVANT_ENV}
    environment.update(values)
    return mock.patch.dict(os.environ, environment, clear=True)


def test_user_canonical_key_beats_stale_process_values() -> None:
    registry = {
        ("CGKN_OPENAI_API_KEY", "User"): "dummy-new-user-key-123456",
        ("CGKN_OPENAI_BASE_URL", "User"): "https://new.example/v1",
        ("OPENAI_API_KEY", "User"): "dummy-old-user-key-123456",
        ("OPENAI_BASE_URL", "User"): "https://old.example/v1",
    }

    with clean_process_env(
        CGKN_OPENAI_API_KEY="dummy-old-process-key-123456",
        OPENAI_API_KEY="dummy-old-process-key-123456",
    ), mock.patch.object(
        check_connectivity,
        "_windows_env_value",
        side_effect=lambda name, target: registry.get((name, target), ""),
    ):
        creds = check_connectivity._resolve_api_credentials()

    assert creds["api_key"] == "dummy-new-user-key-123456"
    assert creds["api_key_source"] == "CGKN_OPENAI_API_KEY(User)"
    assert "CGKN_OPENAI_API_KEY" in creds["api_key_conflict_sources"]
    assert "OPENAI_API_KEY(User)" in creds["api_key_conflict_sources"]
    assert creds["base_url"] == "https://new.example/v1"


def test_explicit_process_override_beats_user_canonical_key() -> None:
    with clean_process_env(CGKN_OPENAI_API_KEY_OVERRIDE="dummy-one-run-override-123456"), mock.patch.object(
        check_connectivity,
        "_windows_env_value",
        side_effect=lambda name, target: "dummy-user-key-123456" if (name, target) == ("CGKN_OPENAI_API_KEY", "User") else "",
    ):
        creds = check_connectivity._resolve_api_credentials()

    assert creds["api_key"] == "dummy-one-run-override-123456"
    assert creds["api_key_source"] == "CGKN_OPENAI_API_KEY_OVERRIDE"
    assert creds["api_key_conflict_sources"] == ["CGKN_OPENAI_API_KEY(User)"]


def test_local_notes_never_load_api_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        notes = pathlib.Path(tmp) / "NOTES.md"
        notes.write_text("provider `https://provider.example/v1`\nsecret `sk-old-secret-123456789`\n", encoding="utf-8")
        with clean_process_env(CGKN_LOCAL_NOTES_PATH=str(notes)):
            defaults = check_connectivity._load_local_notes_defaults()

    assert defaults == {"base_url": "https://provider.example/v1"}


def test_replace_user_credentials_clears_legacy_values_and_scrubs_notes() -> None:
    applied: list[dict[str, str | None]] = []
    previous = {name: "old-value" for name in provider_credentials.MANAGED_USER_NAMES}

    with mock.patch.object(provider_credentials, "_read_user_values", return_value=previous), mock.patch.object(
        provider_credentials,
        "_apply_user_values",
        side_effect=lambda values: applied.append(dict(values)),
    ), mock.patch.object(
        provider_credentials,
        "scrub_legacy_note_keys",
        return_value=True,
    ), mock.patch.object(
        provider_credentials,
        "_broadcast_environment_change",
    ), mock.patch.object(
        check_connectivity,
        "_resolve_api_credentials",
        return_value={"base_url": "https://provider.example/v1"},
    ), clean_process_env():
        result = provider_credentials.replace_user_credentials("dummy-new-key-123456789")

    assert applied == [
        {
            "CGKN_OPENAI_API_KEY": "dummy-new-key-123456789",
            "CGKN_OPENAI_BASE_URL": "https://provider.example/v1",
            "CGNK_OPENAI_API_KEY": None,
            "OPENAI_API_KEY": None,
            "CGNK_OPENAI_BASE_URL": None,
            "OPENAI_BASE_URL": None,
        }
    ]
    assert result["status"] == "replaced"
    assert result["legacy_notes_scrubbed"] is True


def test_scrub_legacy_note_keys_removes_secret_without_removing_notes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        notes = pathlib.Path(tmp) / "NOTES.md"
        notes.write_text("keep this\nold: `sk-old-secret-123456789`\n", encoding="utf-8")

        changed = provider_credentials.scrub_legacy_note_keys(notes)
        text = notes.read_text(encoding="utf-8")

    assert changed is True
    assert "keep this" in text
    assert "sk-old-secret" not in text
    assert "[removed-api-key]" in text
