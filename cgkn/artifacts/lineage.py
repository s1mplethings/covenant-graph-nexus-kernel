from __future__ import annotations

from typing import Any

from .models import ArtifactRef
from .store import ArtifactStore


def build_lineage(store: ArtifactStore, value: ArtifactRef | str) -> dict[str, Any]:
    artifact = store.resolve_artifact_ref(value)
    seen: set[str] = set()

    def walk(current) -> dict[str, Any]:
        if current.id in seen:
            return {"artifactRef": current.ref.as_dict(), "cycle": True, "inputs": []}
        seen.add(current.id)
        return {
            "artifactRef": current.ref.as_dict(),
            "status": current.status,
            "producer": current.producer.as_dict(),
            "inputs": [walk(store.resolve_artifact_ref(ref)) for ref in current.provenance.input_artifact_refs],
        }

    return walk(artifact)


def render_lineage(tree: dict[str, Any]) -> str:
    lines: list[str] = []

    def walk(node: dict[str, Any], prefix: str, last: bool) -> None:
        ref = node["artifactRef"]
        label = f"{ref['artifactInstanceId']} [{ref['artifactType']}] ({node.get('status', 'unknown')})"
        lines.append((prefix + ("└─ " if prefix else "") + label) if prefix else label)
        children = node.get("inputs", [])
        for index, child in enumerate(children):
            child_last = index == len(children) - 1
            branch = "   " if last else "│  "
            walk(child, prefix + branch, child_last)

    walk(tree, "", True)
    return "\n".join(lines)
