from __future__ import annotations

from typing import Any, Iterable

from cgkn.artifacts.hash import content_hash
from cgkn.artifacts.models import ArtifactRef


def execution_fingerprint(
    module_ref: str,
    module_config: dict[str, Any],
    input_artifact_refs: Iterable[ArtifactRef],
    prompt_version: str | None,
    policy_ref: str,
) -> str:
    return content_hash(
        {
            "moduleRef": module_ref,
            "moduleConfig": module_config,
            "inputArtifactHashes": sorted(ref.content_hash for ref in input_artifact_refs),
            "promptVersion": prompt_version,
            "relevantPolicyVersion": policy_ref,
        }
    )
