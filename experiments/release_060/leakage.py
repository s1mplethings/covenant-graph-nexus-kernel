"""Family-level leakage checks for the frozen ITER-060 specifications."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .contracts import ProjectFamilySpec, canonical_hash


def _terms(value: str) -> set[str]:
    return {item.casefold() for item in re.findall(r"[A-Za-z0-9_]+", value) if len(item) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0


def check_family_leakage(families: Iterable[ProjectFamilySpec], *, similarity_limit: float = 0.82) -> dict[str, Any]:
    rows = tuple(families)
    findings: list[dict[str, Any]] = []
    public_hashes: dict[str, str] = {}
    path_sets: dict[str, set[str]] = {}
    for item in rows:
        if item.public_hash in public_hashes:
            findings.append({"kind": "same_task_hash", "left": public_hashes[item.public_hash], "right": item.family_id})
        public_hashes[item.public_hash] = item.family_id
        # Full logical paths carry the family package namespace.  Matching
        # basenames such as main.py are a scaffold convention, not lineage.
        path_sets[item.family_id] = set(item.expected_artifacts)
    development = tuple(item for item in rows if item.split == "DEVELOPMENT")
    formal = tuple(item for item in rows if item.split == "FORMAL_HOLDOUT")
    for dev in development:
        for holdout in formal:
            similarity = _jaccard(_terms(dev.public_goal), _terms(holdout.public_goal))
            if similarity >= similarity_limit:
                findings.append({"kind": "high_goal_similarity", "left": dev.family_id, "right": holdout.family_id, "ratio": round(similarity, 6)})
            shared = path_sets[dev.family_id] & path_sets[holdout.family_id]
            ratio = len(shared) / max(1, min(len(path_sets[dev.family_id]), len(path_sets[holdout.family_id])))
            # Common packaging filenames are not source lineage.  Source paths
            # include unique package roots and therefore cannot leak here.
            non_packaging = shared - {"README.md", "pyproject.toml", "__init__.py", "__main__.py"}
            if ratio >= 0.9 and non_packaging:
                findings.append({"kind": "high_shared_file_ratio", "left": dev.family_id, "right": holdout.family_id, "ratio": round(ratio, 6)})
    result = {
        "kind": "CGNKITER060FamilyLeakageReceipt",
        "schema_version": "1.0",
        "development_families": len(development),
        "formal_families": len(formal),
        "corpus_read_enabled": False,
        "findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }
    result["receipt_hash"] = canonical_hash(result)
    return result


def model_packet(family: ProjectFamilySpec, episode_index: int) -> dict[str, Any]:
    """Return the only family material that an executor may receive."""

    if episode_index < 0 or episode_index >= len(family.episodes):
        raise IndexError("episode index out of range")
    public = family.public_dict()
    public["episodes"] = [item.public_dict() for item in family.episodes[: episode_index + 1]]
    packet = {
        "family": public,
        "current_episode": family.episodes[episode_index].public_dict(),
        "corpus_search": "DISABLED",
        "private_evaluator": "WITHHELD",
    }
    encoded = str(packet).casefold()
    if "private_cases" in encoded or family.private_hash.casefold() in encoded:
        raise RuntimeError("private evaluator leakage")
    return packet
