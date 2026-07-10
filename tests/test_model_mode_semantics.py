from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import model_mode_semantics


def parse(text: str) -> dict:
    return model_mode_semantics.parse_model_mode_semantics(text, {})


def test_walk_local_model_targets_project_not_cgkn_backend() -> None:
    result = parse("走本地模型 + 开始做吧")
    assert result["target_project_model"]["mode"] == "local_model"
    assert result["target_project_model"]["config_needed"] is True
    assert result["cgkn_generation_backend_constraint"]["mode"] == "none"
    assert result["cgkn_generation_backend_constraint"]["no_api"] is False


def test_project_inside_local_model_targets_project() -> None:
    result = parse("项目里面用本地模型")
    assert result["target_project_model"]["mode"] == "local_model"
    assert result["cgkn_generation_backend_constraint"]["mode"] == "none"


def test_backend_connects_local_model_targets_project() -> None:
    result = parse("后端接本地模型")
    assert result["target_project_model"]["mode"] == "local_model"
    assert result["cgkn_generation_backend_constraint"]["mode"] == "none"


def test_no_external_inference_targets_project() -> None:
    result = parse("不要用外部接口做推理")
    assert result["target_project_model"]["mode"] == "local_model"
    assert result["cgkn_generation_backend_constraint"]["mode"] == "none"


def test_generation_code_no_api_constrains_cgkn_backend() -> None:
    result = parse("你们生成代码不要走 API")
    assert result["cgkn_generation_backend_constraint"]["mode"] == "local"
    assert result["cgkn_generation_backend_constraint"]["no_api"] is True


def test_cgkn_itself_must_use_local_model_constrains_backend() -> None:
    result = parse("CGKN 自己也必须用本地模型生成")
    assert result["cgkn_generation_backend_constraint"]["mode"] == "local"
    assert result["cgkn_generation_backend_constraint"]["no_api"] is True


def test_apply_writes_separate_whiteboard_fields() -> None:
    session = {"whiteboard": {"project_summary": "demo"}}
    model_mode_semantics.apply_model_mode_semantics(session, "走本地模型 + 开始做吧", configured_backend_mode="api", configured_model="gpt-test")
    assert session["whiteboard"]["target_project_architecture"]["model_mode"] == "local_model"
    assert session["whiteboard"]["cgkn_execution"]["generation_backend"] == "api"
    assert session["whiteboard"]["cgkn_execution"]["platform_generation_constraint"] == "none"
