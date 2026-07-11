from __future__ import annotations

import pathlib
from typing import Any

try:
    from agent_scope_contract import check_scope_write
    from agent_tree_contracts import append_jsonl, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_scope_contract import check_scope_write
    from scripts.agent_tree_contracts import append_jsonl, write_json


def enforce_leaf_scope(
    *,
    contract: dict[str, Any],
    candidate_files: dict[str, str],
    project_dir: str | pathlib.Path | None = None,
    out_dir: str | pathlib.Path | None = None,
    write_allowed: bool = True,
) -> dict[str, Any]:
    attempted = sorted(candidate_files)
    scope = check_scope_write(contract, attempted)
    allowed_files = [path for path in attempted if path not in set(scope["violations"])]
    blocked_files = list(scope["violations"])
    written_files: list[str] = []
    if write_allowed and project_dir is not None:
        root = pathlib.Path(project_dir)
        for rel in allowed_files:
            target = (root / rel).resolve()
            root_resolved = root.resolve()
            if not str(target).lower().startswith(str(root_resolved).lower()):
                blocked_files.append(rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(candidate_files[rel], encoding="utf-8")
            written_files.append(rel)
            if out_dir is not None:
                append_jsonl(
                    pathlib.Path(out_dir) / "file_write_log.jsonl",
                    {"agent_id": contract.get("agent_id", ""), "path": rel, "status": "written"},
                )
    result = {
        "agent_id": contract.get("agent_id", ""),
        "ok": not blocked_files,
        "allowed_files": allowed_files,
        "blocked_files": blocked_files,
        "written_files": written_files,
        "attempted_files": attempted,
    }
    if out_dir is not None:
        write_json(pathlib.Path(out_dir) / "scope_enforcement_result.json", result)
    return result
