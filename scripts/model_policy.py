#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any


DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_PROFILE = "balanced"

TASK_ENV_VARS = {
    "frontdesk": "CGNK_FRONTDESK_MODEL",
    "classification": "CGNK_CLASSIFICATION_MODEL",
    "planning": "CGNK_PLANNING_MODEL",
    "provider_generation": "CGNK_PROVIDER_MODEL",
    "revision": "CGNK_REVISION_MODEL",
    "repair": "CGNK_REPAIR_MODEL",
    "review": "CGNK_REVIEW_MODEL",
    "connectivity": "CGNK_CONNECTIVITY_MODEL",
}

MODEL_PROFILES: dict[str, dict[str, str]] = {
    "cheap": {
        "frontdesk": "gpt-5.4-nano",
        "classification": "gpt-5.4-nano",
        "planning": "gpt-5.4-nano",
        "provider_generation": "gpt-5.4-nano",
        "revision": "gpt-5.4-nano",
        "repair": "gpt-5.4-nano",
        "review": "gpt-5.4-nano",
        "connectivity": "gpt-5.4-nano",
    },
    "balanced": {
        "frontdesk": "gpt-5.4-nano",
        "classification": "gpt-5.4-nano",
        "planning": "gpt-5.4-nano",
        "provider_generation": "gpt-5.4-nano",
        "revision": "gpt-5.4-nano",
        "repair": "gpt-5.4-nano",
        "review": "gpt-5.4-nano",
        "connectivity": "gpt-5.4-nano",
    },
    "quality": {
        "frontdesk": "gpt-5.4-nano",
        "classification": "gpt-5.4-nano",
        "planning": "gpt-5.4-nano",
        "provider_generation": "gpt-5.4-nano",
        "revision": "gpt-5.4-nano",
        "repair": "gpt-5.4-nano",
        "review": "gpt-5.4-nano",
        "connectivity": "gpt-5.4-nano",
    },
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def current_profile() -> str:
    profile = _clean(os.environ.get("CGNK_MODEL_PROFILE")).lower()
    return profile if profile in MODEL_PROFILES else DEFAULT_PROFILE


def select_model(task: str, profile: str | None = None) -> str:
    task_name = _clean(task)
    env_name = TASK_ENV_VARS.get(task_name)
    if env_name:
        override = _clean(os.environ.get(env_name))
        if override:
            return override

    profile_name = _clean(profile).lower() if profile is not None else current_profile()
    profile_models = MODEL_PROFILES.get(profile_name, {})
    profile_model = _clean(profile_models.get(task_name))
    if profile_model:
        return profile_model

    openai_model = _clean(os.environ.get("OPENAI_MODEL"))
    if openai_model:
        return openai_model
    return DEFAULT_MODEL


def explain_model_choice(task: str) -> dict[str, Any]:
    task_name = _clean(task)
    env_name = TASK_ENV_VARS.get(task_name, "")
    override = _clean(os.environ.get(env_name)) if env_name else ""
    profile_name = current_profile()
    profile_model = _clean(MODEL_PROFILES.get(profile_name, {}).get(task_name))
    openai_model = _clean(os.environ.get("OPENAI_MODEL"))
    if override:
        source = env_name
        model = override
    elif profile_model:
        source = f"profile:{profile_name}"
        model = profile_model
    elif openai_model:
        source = "OPENAI_MODEL"
        model = openai_model
    else:
        source = "built_in_default"
        model = DEFAULT_MODEL
    return {
        "task": task_name,
        "model": model,
        "source": source,
        "profile": profile_name,
        "task_env_var": env_name,
    }


def model_policy_snapshot() -> dict[str, Any]:
    profile_name = current_profile()
    return {
        "kind": "CGNKModelPolicySnapshot",
        "profile": profile_name,
        "models": {task: select_model(task, profile_name) for task in TASK_ENV_VARS},
        "task_env_vars": dict(TASK_ENV_VARS),
        "openai_model": _clean(os.environ.get("OPENAI_MODEL")),
    }
