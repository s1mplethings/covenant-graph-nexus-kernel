from __future__ import annotations

from typing import Any, Mapping

from cgkn.orchestration.tree_edits import TreeEdit


def parse_tree_edit(value: Mapping[str, Any]) -> TreeEdit:
    allowed = {"edit_id", "operation", "node_id", "payload", "provenance"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("unknown tree edit fields: " + ",".join(sorted(unknown)))
    return TreeEdit(edit_id=str(value["edit_id"]), operation=str(value["operation"]), node_id=str(value.get("node_id", "")), payload=dict(value.get("payload", {})), provenance=dict(value.get("provenance", {})))
