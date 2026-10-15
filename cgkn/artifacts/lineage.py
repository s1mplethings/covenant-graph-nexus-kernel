from __future__ import annotations

from typing import Any

from .models import ArtifactRef
from .store import ArtifactStore
from .types import ArtifactValidationError


def build_lineage(store: ArtifactStore, value: ArtifactRef | str) -> dict[str, Any]:
    artifact = store.resolve_artifact_ref(value)
    active: set[str] = set()

    def walk(current) -> dict[str, Any]:
        if current.id in active:
            raise ArtifactValidationError(f"artifact lineage cycle detected: {current.id}")
        active.add(current.id)
        result = {
            "artifactRef": current.ref.as_dict(),
            "status": current.status,
            "producer": current.producer.as_dict(),
            "inputs": [walk(store.resolve_artifact_ref(ref)) for ref in sorted(current.provenance.input_artifact_refs, key=lambda item: item.artifact_instance_id)],
        }
        active.remove(current.id)
        return result

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
