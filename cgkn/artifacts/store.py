from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Iterable

from .models import ArtifactInstance, ArtifactRef
from .types import ArtifactTypeRegistry, ArtifactValidationError


class ArtifactStore:
    """Local immutable artifact history plus a mutable status/index projection."""

    def __init__(self, run_dir: pathlib.Path, registry: ArtifactTypeRegistry):
        self.run_dir = pathlib.Path(run_dir).resolve()
        self.registry = registry
        self.artifacts_dir = self.run_dir / "artifacts"
        self.index_path = self.run_dir / "artifact_index.json"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save_index({"kind": "ArtifactIndex", "schemaVersion": "1", "artifacts": []})

    def _load_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _save_index(self, value: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        temp = self.index_path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.index_path)

    def _path(self, artifact_id: str) -> pathlib.Path:
        if not artifact_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in artifact_id):
            raise ArtifactValidationError(f"unsafe artifact instance id: {artifact_id!r}")
        return self.artifacts_dir / f"{artifact_id}.json"

    def allocate_id(self, artifact_type: str) -> str:
        slug = artifact_type.split("@", 1)[0].removeprefix("artifact.").replace("_", "-").replace(".", "-")
        existing = {row["artifactInstanceId"] for row in self._load_index()["artifacts"]}
        sequence = 1
        while f"ai.{slug}.{sequence:03d}" in existing:
            sequence += 1
        return f"ai.{slug}.{sequence:03d}"

    def validate_artifact(self, artifact: ArtifactInstance) -> None:
        self.registry.validate_content(artifact.artifact_type, artifact.content)
        if artifact.content_hash != artifact.ref.content_hash:
            raise ArtifactValidationError("artifact content hash is inconsistent")
        for input_ref in artifact.provenance.input_artifact_refs:
            resolved = self.resolve_artifact_ref(input_ref)
            if not self.verify_artifact_hash(resolved.ref):
                raise ArtifactValidationError(f"input artifact hash is invalid: {input_ref.artifact_instance_id}")

    def write_artifact(self, artifact: ArtifactInstance) -> ArtifactRef:
        self.validate_artifact(artifact)
        path = self._path(artifact.id)
        if path.exists():
            raise ArtifactValidationError(f"artifact instance already exists: {artifact.id}")
        index = self._load_index()
        rows = index["artifacts"]
        if any(row["artifactInstanceId"] == artifact.id for row in rows):
            raise ArtifactValidationError(f"artifact ref is not unique: {artifact.id}")
        if artifact.supersedes:
            if not any(row["artifactInstanceId"] == artifact.supersedes for row in rows):
                raise ArtifactValidationError(f"superseded artifact does not exist: {artifact.supersedes}")
            self._set_status_in_memory(index, artifact.supersedes, "superseded")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(artifact.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
        rows.append(
            {
                **artifact.ref.as_dict(),
                "producer": artifact.producer.as_dict(),
                "createdAt": artifact.created_at,
                "status": artifact.status,
                "supersedes": artifact.supersedes,
                "consumers": [],
                "path": path.relative_to(self.run_dir).as_posix(),
            }
        )
        self._save_index(index)
        return artifact.ref

    def read_artifact(self, artifact_id: str) -> ArtifactInstance:
        path = self._path(artifact_id)
        if not path.is_file():
            raise ArtifactValidationError(f"artifact instance not found: {artifact_id}")
        instance = ArtifactInstance.from_dict(json.loads(path.read_text(encoding="utf-8")))
        row = self._row(artifact_id)
        instance.status = str(row["status"])
        return instance

    def list_artifacts(self, artifact_type: str | None = None, status: str | None = None) -> list[ArtifactInstance]:
        result = []
        for row in self._load_index()["artifacts"]:
            if artifact_type and row["artifactType"] != artifact_type:
                continue
            if status and row["status"] != status:
                continue
            result.append(self.read_artifact(row["artifactInstanceId"]))
        return result

    def resolve_artifact_ref(self, value: ArtifactRef | dict[str, Any] | str) -> ArtifactInstance:
        ref = ArtifactRef.from_dict(value) if isinstance(value, dict) else value
        artifact = self.read_artifact(ref.artifact_instance_id if isinstance(ref, ArtifactRef) else str(ref))
        if isinstance(ref, ArtifactRef):
            if artifact.artifact_type != ref.artifact_type or artifact.content_hash != ref.content_hash:
                raise ArtifactValidationError(f"artifact ref identity mismatch: {ref.artifact_instance_id}")
        return artifact

    def verify_artifact_hash(self, value: ArtifactRef | dict[str, Any] | str) -> bool:
        try:
            artifact = self.resolve_artifact_ref(value)
        except (ArtifactValidationError, ValueError, KeyError, json.JSONDecodeError):
            return False
        from .hash import content_hash

        return artifact.content_hash == content_hash(artifact.content)

    def find_produced_by_node(self, node_id: str, output_port: str | None = None) -> list[ArtifactInstance]:
        matches = []
        for row in self._load_index()["artifacts"]:
            producer = row.get("producer", {})
            if producer.get("nodeId") != node_id:
                continue
            if output_port is not None and producer.get("outputPort", "") != output_port:
                continue
            matches.append(self.read_artifact(row["artifactInstanceId"]))
        return matches

    def latest_produced_by_node(self, node_id: str, output_port: str, *, fresh_only: bool = True) -> ArtifactInstance | None:
        matches = self.find_produced_by_node(node_id, output_port)
        if fresh_only:
            matches = [item for item in matches if item.status == "fresh"]
        return matches[-1] if matches else None

    def find_consumers(self, value: ArtifactRef | str) -> list[str]:
        artifact_id = value.artifact_instance_id if isinstance(value, ArtifactRef) else str(value)
        return list(self._row(artifact_id).get("consumers", []))

    def register_consumer(self, value: ArtifactRef | str, node_id: str) -> None:
        artifact_id = value.artifact_instance_id if isinstance(value, ArtifactRef) else str(value)
        index = self._load_index()
        row = self._row_in(index, artifact_id)
        if node_id not in row["consumers"]:
            row["consumers"].append(node_id)
            row["consumers"].sort()
            self._save_index(index)

    def set_status(self, artifact_id: str, status: str) -> None:
        if status not in {"fresh", "stale", "invalid", "superseded"}:
            raise ArtifactValidationError(f"invalid artifact status: {status}")
        index = self._load_index()
        self._set_status_in_memory(index, artifact_id, status)
        self._save_index(index)

    def _set_status_in_memory(self, index: dict[str, Any], artifact_id: str, status: str) -> None:
        self._row_in(index, artifact_id)["status"] = status

    def _row(self, artifact_id: str) -> dict[str, Any]:
        return self._row_in(self._load_index(), artifact_id)

    @staticmethod
    def _row_in(index: dict[str, Any], artifact_id: str) -> dict[str, Any]:
        for row in index["artifacts"]:
            if row["artifactInstanceId"] == artifact_id:
                return row
        raise ArtifactValidationError(f"artifact instance not indexed: {artifact_id}")

    # Contract spelling aliases retained for machine clients using the v0.3 API names.
    writeArtifact = write_artifact
    readArtifact = read_artifact
    listArtifacts = list_artifacts
    resolveArtifactRef = resolve_artifact_ref
    verifyArtifactHash = verify_artifact_hash
    findProducedByNode = find_produced_by_node
    findConsumers = find_consumers
