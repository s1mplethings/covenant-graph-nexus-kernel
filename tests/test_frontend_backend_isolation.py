from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.codex_conversation as bridge
from scripts import model_mode_semantics


def test_target_project_architecture_enters_combined_requirement_without_overwriting_cgkn_backend() -> None:
    session = bridge.default_session("isolation")
    session["whiteboard"]["project_summary"] = "本地项目生成系统"
    model_mode_semantics.apply_model_mode_semantics(
        session,
        "走本地模型 + 开始做吧",
        configured_backend_mode="api",
        configured_model="gpt-test",
    )

    requirement = bridge.combined_requirement(session)

    assert session["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
    assert session["whiteboard"]["cgkn_execution"]["generation_backend"] == "api"
    assert "目标项目模型架构要求" in requirement
    assert "model_mode: local_model" in requirement
    assert "generation_backend: api" in requirement


def test_platform_generation_constraint_is_separate_from_target_project_model() -> None:
    session = bridge.default_session("isolation")
    session["whiteboard"]["project_summary"] = "本地项目生成系统"
    model_mode_semantics.apply_model_mode_semantics(
        session,
        "你们生成代码不要走 API，项目里面用本地模型",
        configured_backend_mode="api",
        configured_model="gpt-test",
    )

    whiteboard = session["whiteboard"]
    assert whiteboard["target_project_architecture"]["model_mode"] == "local_model"
    assert whiteboard["cgkn_execution"]["platform_generation_constraint"] == "local"
    assert whiteboard["cgkn_execution"]["platform_no_api"] is True
