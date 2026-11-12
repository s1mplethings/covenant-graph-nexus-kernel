"""Project Workspace module (M1).

Provides persistent, isolated project management via handle(data_dir, request).
"""

import json
import os
import uuid

MILESTONE_ID = "M1"

_STORE_FILENAME = "projects.json"


def _store_path(data_dir):
    return os.path.join(data_dir, _STORE_FILENAME)


def _load(data_dir):
    path = _store_path(data_dir)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    data = json.loads(content)
    if not isinstance(data, list):
        return []
    return data


def _save(data_dir, projects):
    os.makedirs(data_dir, exist_ok=True)
    path = _store_path(data_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    op = request.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("request must contain a non-empty 'op' string")

    if op == "project.create":
        name = request.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("project name must be a non-empty string")
        projects = _load(data_dir)
        project_id = uuid.uuid4().hex
        record = {"id": project_id, "name": name}
        projects.append(record)
        _save(data_dir, projects)
        return {"id": project_id, "name": name}

    if op == "project.get":
        project_id = request.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_id must be a non-empty string")
        projects = _load(data_dir)
        for record in projects:
            if record.get("id") == project_id:
                return {"id": record["id"], "name": record["name"]}
        raise ValueError("project not found: %s" % project_id)

    if op == "project.list":
        projects = _load(data_dir)
        items = [{"id": r["id"], "name": r["name"]} for r in projects]
        return {"items": items}

    raise ValueError("unknown operation: %s" % op)
