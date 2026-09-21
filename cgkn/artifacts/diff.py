from __future__ import annotations

from typing import Any


def artifact_diff(old: Any, new: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"added": [], "removed": [], "changed": []}

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() - right.keys()):
                result["removed"].append({"path": f"{path}/{key}", "value": left[key]})
            for key in sorted(right.keys() - left.keys()):
                result["added"].append({"path": f"{path}/{key}", "value": right[key]})
            for key in sorted(left.keys() & right.keys()):
                walk(left[key], right[key], f"{path}/{key}")
            return
        if isinstance(left, list) and isinstance(right, list):
            common = min(len(left), len(right))
            for index in range(common):
                walk(left[index], right[index], f"{path}/{index}")
            for index in range(common, len(left)):
                result["removed"].append({"path": f"{path}/{index}", "value": left[index]})
            for index in range(common, len(right)):
                result["added"].append({"path": f"{path}/{index}", "value": right[index]})
            return
        if left != right:
            result["changed"].append({"path": path or "/", "old": left, "new": right})

    walk(old, new, "")
    return result
