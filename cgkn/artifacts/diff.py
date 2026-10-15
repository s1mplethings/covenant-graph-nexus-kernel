from __future__ import annotations

import copy
from typing import Any

from .hash import canonical_json


def artifact_diff(old: Any, new: Any) -> dict[str, list[dict[str, Any]]]:
    # Reject values that cannot participate in stable artifact identity.
    canonical_json(old)
    canonical_json(new)
    result: dict[str, list[dict[str, Any]]] = {"added": [], "removed": [], "changed": []}

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() - right.keys()):
                result["removed"].append({"path": f"{path}/{key}", "value": copy.deepcopy(left[key])})
            for key in sorted(right.keys() - left.keys()):
                result["added"].append({"path": f"{path}/{key}", "value": copy.deepcopy(right[key])})
            for key in sorted(left.keys() & right.keys()):
                walk(left[key], right[key], f"{path}/{key}")
            return
        if isinstance(left, list) and isinstance(right, list):
            common = min(len(left), len(right))
            for index in range(common):
                walk(left[index], right[index], f"{path}/{index}")
            for index in range(common, len(left)):
                result["removed"].append({"path": f"{path}/{index}", "value": copy.deepcopy(left[index])})
            for index in range(common, len(right)):
                result["added"].append({"path": f"{path}/{index}", "value": copy.deepcopy(right[index])})
            return
        if left != right:
            result["changed"].append({"path": path or "/", "old": copy.deepcopy(left), "new": copy.deepcopy(right)})

    walk(old, new, "")
    return result
