from __future__ import annotations

from dataclasses import dataclass, asdict

from .status import EvidenceStatus


@dataclass(frozen=True)
class ArtifactEnvelope:
    kind: str
    schema_version: str
    run_id: str
    candidate_id: str
    candidate_hash: str
    commit_sha: str
    producer: str
    created_at: str
    status: EvidenceStatus
    artifact_hash: str

    def as_json(self) -> dict[str, str]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload
