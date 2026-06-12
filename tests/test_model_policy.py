from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import model_policy


def _clear_env(monkeypatch) -> None:
    for name in list(model_policy.TASK_ENV_VARS.values()) + ["CGNK_MODEL_PROFILE", "OPENAI_MODEL"]:
        monkeypatch.delenv(name, raising=False)


def test_default_profile_is_balanced(monkeypatch) -> None:
    _clear_env(monkeypatch)
    assert model_policy.current_profile() == "balanced"


def test_balanced_defaults(monkeypatch) -> None:
    _clear_env(monkeypatch)
    assert model_policy.select_model("frontdesk") == "gpt-4.1-mini"
    assert model_policy.select_model("provider_generation") == "gpt-4.1-mini"
    assert model_policy.select_model("connectivity") == "gpt-4.1-mini"
    assert model_policy.select_model("repair") == "gpt-4.1"
    assert model_policy.select_model("review") == "gpt-4.1"


def test_task_specific_env_override_wins(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CGNK_REPAIR_MODEL", "repair-test-model")
    monkeypatch.setenv("OPENAI_MODEL", "global-test-model")
    assert model_policy.select_model("repair") == "repair-test-model"


def test_openai_model_fallback_for_unknown_task(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_MODEL", "global-test-model")
    assert model_policy.select_model("unknown_task") == "global-test-model"


def test_quality_profile_provider_is_stronger(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CGNK_MODEL_PROFILE", "quality")
    assert model_policy.select_model("planning") == "gpt-4.1"
    assert model_policy.select_model("provider_generation") == "gpt-4.1"


def test_explain_model_choice_reports_source(monkeypatch) -> None:
    _clear_env(monkeypatch)
    info = model_policy.explain_model_choice("connectivity")
    assert info["model"] == "gpt-4.1-mini"
    assert info["source"] == "profile:balanced"
