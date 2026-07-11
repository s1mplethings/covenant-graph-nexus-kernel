from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generated_project_architecture_contract


def test_local_model_project_requires_adapter_config_and_limit(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main>app</main>", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('api')", encoding="utf-8")
    result = generated_project_architecture_contract.evaluate_project(tmp_path, {"mode": "local_model"})
    assert result["verdict"] in {"NEEDS_REWORK", "FAIL"}
    assert "model_adapter" in result["missing"]
    assert "model_config_documented" in result["missing"]


def test_local_model_project_with_boundaries_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "contracts").mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<main>app</main>", encoding="utf-8")
    (tmp_path / "frontend" / "api_client.js").write_text("export const api = '/api';", encoding="utf-8")
    (tmp_path / "backend" / "app.py").write_text("from model_adapter import infer\n", encoding="utf-8")
    (tmp_path / "backend" / "model_adapter.py").write_text("MODEL_PATH=''; LOCAL_MODEL_ENDPOINT=''\n", encoding="utf-8")
    (tmp_path / "backend" / "storage.py").write_text("DB='sqlite'\n", encoding="utf-8")
    (tmp_path / "contracts" / "api_schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".env.example").write_text("MODEL_PATH=\nLOCAL_MODEL_ENDPOINT=\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("缺少模型文件时不能宣称真实推理通过。\n", encoding="utf-8")
    result = generated_project_architecture_contract.evaluate_project(tmp_path, {"mode": "local_model"})
    assert result["verdict"] == "PASS"


def test_cgkn_api_config_leak_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main>app</main>", encoding="utf-8")
    (tmp_path / "app.py").write_text("CGKN_OPENAI_API_KEY='secret'\n", encoding="utf-8")
    result = generated_project_architecture_contract.evaluate_project(tmp_path, {"mode": "none"})
    assert "cgkn_provider_config_leaked" in result["missing"]
