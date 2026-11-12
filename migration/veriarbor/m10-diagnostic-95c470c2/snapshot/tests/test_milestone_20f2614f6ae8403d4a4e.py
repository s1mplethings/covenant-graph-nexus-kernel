import importlib.util
import os
import sys

import pytest


API_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "milestones",
    "milestone_20f2614f6ae8403d4a4e",
    "api.py",
)


def _load_api():
    spec = importlib.util.spec_from_file_location(
        "milestone_20f2614f6ae8403d4a4e_api", API_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api = _load_api()


def test_milestone_id():
    assert api.MILESTONE_ID == "M1"


def test_create_returns_project(tmp_path):
    result = api.handle(str(tmp_path), {"op": "project.create", "name": "Alpha"})
    assert isinstance(result, dict)
    assert result.get("name") == "Alpha"
    assert isinstance(result.get("id"), str)
    assert result["id"] != ""


def test_get_returns_created_project(tmp_path):
    data_dir = str(tmp_path)
    created = api.handle(data_dir, {"op": "project.create", "name": "Beta"})
    fetched = api.handle(data_dir, {"op": "project.get", "project_id": created["id"]})
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Beta"


def test_list_returns_all_projects(tmp_path):
    data_dir = str(tmp_path)
    a = api.handle(data_dir, {"op": "project.create", "name": "One"})
    b = api.handle(data_dir, {"op": "project.create", "name": "Two"})
    listed = api.handle(data_dir, {"op": "project.list"})
    projects = listed["projects"] if isinstance(listed, dict) else listed
    ids = {p["id"] for p in projects}
    assert a["id"] in ids
    assert b["id"] in ids
    assert len(projects) == 2


def test_empty_name_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        api.handle(str(tmp_path), {"op": "project.create", "name": ""})


def test_missing_id_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        api.handle(str(tmp_path), {"op": "project.get", "project_id": "does-not-exist"})


def test_isolation_between_data_dirs(tmp_path):
    dir_a = str(tmp_path / "a")
    dir_b = str(tmp_path / "b")
    os.makedirs(dir_a, exist_ok=True)
    os.makedirs(dir_b, exist_ok=True)
    api.handle(dir_a, {"op": "project.create", "name": "OnlyA"})
    listed_b = api.handle(dir_b, {"op": "project.list"})
    projects_b = listed_b["projects"] if isinstance(listed_b, dict) else listed_b
    assert projects_b == []


def test_persistence_across_reload(tmp_path):
    data_dir = str(tmp_path)
    created = api.handle(data_dir, {"op": "project.create", "name": "Persisted"})
    reloaded = _load_api()
    fetched = reloaded.handle(data_dir, {"op": "project.get", "project_id": created["id"]})
    assert fetched["name"] == "Persisted"


def test_unicode_name_preserved(tmp_path):
    data_dir = str(tmp_path)
    name = "\u9879\u76ee \u00e9\u00e8 \u4e16\u754c \U0001f680"
    created = api.handle(data_dir, {"op": "project.create", "name": name})
    fetched = api.handle(data_dir, {"op": "project.get", "project_id": created["id"]})
    assert fetched["name"] == name


def test_unknown_op_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        api.handle(str(tmp_path), {"op": "project.unknown"})
