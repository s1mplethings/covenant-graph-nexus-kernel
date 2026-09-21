from __future__ import annotations

from typing import Any

from cgkn.artifacts.models import ArtifactRef
from cgkn.artifacts.store import ArtifactStore
from cgkn.compiler.artifact_graph import ArtifactGraph


class ArtifactInvalidator:
    def __init__(self, store: ArtifactStore, graph: ArtifactGraph):
        self.store = store
        self.graph = graph

    def affected_nodes(self, value: ArtifactRef | str) -> list[str]:
        artifact = self.store.resolve_artifact_ref(value)
        producer = artifact.producer.node_id
        if producer in self.graph.node_consumers:
            return self.graph.descendants(producer)
        direct = self.store.find_consumers(artifact.ref)
        result: list[str] = []
        for node in direct:
            if node not in result:
                result.append(node)
            for descendant in self.graph.descendants(node):
                if descendant not in result:
                    result.append(descendant)
        return result

    def invalidate(self, value: ArtifactRef | str, *, dry_run: bool = False) -> dict[str, Any]:
        artifact = self.store.resolve_artifact_ref(value)
        affected = self.affected_nodes(artifact.ref)
        old_artifact = self.store.read_artifact(artifact.supersedes) if artifact.supersedes else artifact
        replacement = artifact if artifact.supersedes else next(
            (item for item in self.store.list_artifacts(artifact.artifact_type) if item.supersedes == artifact.id),
            None,
        )
        explanations = []
        for node in affected:
            outputs = [item for item in self.store.find_produced_by_node(node) if item.status == "fresh"]
            explanations.append(
                {
                    "node": node,
                    "reason": "upstream_artifact_changed",
                    "changedInputs": [
                        {
                            "artifactRef": artifact.ref.as_dict(),
                            "oldHash": old_artifact.content_hash,
                            "newHash": replacement.content_hash if replacement else artifact.content_hash,
                        }
                    ],
                    "invalidatedOutputs": [item.ref.as_dict() for item in outputs],
                }
            )
            if not dry_run:
                for output in outputs:
                    self.store.set_status(output.id, "stale")
        return {
            "kind": "ArtifactInvalidationReport",
            "dryRun": dry_run,
            "sourceArtifact": artifact.ref.as_dict(),
            "affectedNodes": affected,
            "explanations": explanations,
        }
