from __future__ import annotations

import ast

from _helpers import assert_project_hygiene, project_root, request, server


def test_layering_runtime_and_persistence(tmp_path):
    root = project_root(); assert_project_hygiene()
    domain_files = [path for path in root.rglob("*.py") if "domain" in path.stem.lower() or "domain" in [part.lower() for part in path.parts]]
    assert domain_files
    for path in domain_files:
        imports = {str(node.module or "") for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)}
        assert not any("http" in item or "api" in item for item in imports)
    with server("job_api", tmp_path) as port:
        status, created, _ = request(port, "POST", "/api/jobs", {"title": "ship"}); assert status in {200, 201}
        job_id = str(created["id"])
        status, rows, _ = request(port, "GET", "/api/jobs"); assert status == 200 and any(str(row["id"]) == job_id for row in rows)
        status, row, _ = request(port, "GET", f"/api/jobs/{job_id}"); assert status == 200 and row["status"] not in {"completed", "done"}
        status, row, _ = request(port, "POST", f"/api/jobs/{job_id}/complete"); assert status == 200 and row["status"] in {"completed", "done"}
        status, _, _ = request(port, "POST", f"/api/jobs/{job_id}/complete"); assert status in {400, 409, 422}
        status, _, _ = request(port, "GET", "/api/jobs/not-found"); assert status == 404
    with server("job_api", tmp_path) as port:
        status, row, _ = request(port, "GET", f"/api/jobs/{job_id}"); assert status == 200 and row["status"] in {"completed", "done"}
