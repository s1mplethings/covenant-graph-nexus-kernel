from __future__ import annotations

from typing import Any, Iterable

from cgkn.artifacts.models import ArtifactRef
from cgkn.artifacts.store import ArtifactStore


def evaluate_delivery_readiness(store: ArtifactStore, required: Iterable[ArtifactRef]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(ref: ArtifactRef) -> None:
        if ref.artifact_instance_id in visited:
            return
        visited.add(ref.artifact_instance_id)
        try:
            artifact = store.resolve_artifact_ref(ref)
        except ValueError as exc:
            diagnostics.append({"code": "CGKN_REQUIRED_ARTIFACT_MISSING", "message": str(exc)})
            return
        if artifact.status != "fresh":
            diagnostics.append(
                {
                    "code": "CGKN_REQUIRED_ARTIFACT_STALE",
                    "artifactRef": ref.as_dict(),
                    "status": artifact.status,
                }
            )
        if not store.verify_artifact_hash(ref):
            diagnostics.append({"code": "CGKN_ARTIFACT_HASH_INVALID", "artifactRef": ref.as_dict()})
        for upstream in artifact.provenance.input_artifact_refs:
            visit(upstream)

    for artifact_ref in required:
        visit(artifact_ref)
    return {
        "evidenceStatus": "NEEDS_REWORK" if diagnostics else "PASS",
        "lineageComplete": not diagnostics,
        "diagnostics": diagnostics,
    }
