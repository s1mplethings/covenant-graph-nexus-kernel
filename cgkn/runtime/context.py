from __future__ import annotations

import json
from typing import Any

from cgkn.artifacts.models import ArtifactRef
from cgkn.artifacts.store import ArtifactStore


def _project(content: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {key: content[key] for key in fields if key in content} if fields else dict(content)


def _shrink(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."
    if isinstance(value, list):
        return [_shrink(item, max(16, limit // max(1, len(value)))) for item in value[:16]]
    if isinstance(value, dict):
        return {key: _shrink(item, max(16, limit // max(1, len(value)))) for key, item in value.items()}
    return value


def build_context_pack(
    active_node: dict[str, Any],
    module_contract: dict[str, Any],
    input_artifact_refs: dict[str, ArtifactRef],
    store: ArtifactStore,
    policy: dict[str, Any],
    decision_ledger: dict[str, Any] | None = None,
    raw_source_chars: int = 0,
) -> dict[str, Any]:
    settings = module_contract.get("context", {})
    required = settings.get("requiredArtifactPorts") or [
        port for port, spec in module_contract.get("ports", {}).get("input", {}).items() if spec.get("required", False)
    ]
    optional = settings.get("optionalArtifactPorts", [])
    allowed_ports = list(dict.fromkeys([*required, *optional]))
    artifacts: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    for port in allowed_ports:
        ref = input_artifact_refs.get(port)
        if not ref:
            continue
        spec = module_contract.get("ports", {}).get("input", {}).get(port, {})
        projection = list(spec.get("projection", []))
        artifact = store.resolve_artifact_ref(ref)
        artifacts[port] = {
            "artifactRef": ref.as_dict(),
            "content": _project(artifact.content, projection),
        }
        trace.append({"port": port, "artifactRef": ref.as_dict(), "projection": projection})
    value: dict[str, Any] = {
        "activeNode": active_node["id"],
        "moduleContract": {
            "id": module_contract["id"],
            "version": module_contract["version"],
            "ports": module_contract["ports"],
            "effects": module_contract["effects"],
        },
        "policy": {"id": policy.get("id"), "version": policy.get("version"), "effect_constraints": policy.get("effect_constraints", [])},
        "artifacts": artifacts,
    }
    if settings.get("includeDecisionLedger", False):
        value["decisionLedger"] = (decision_ledger or {}).get("decisions", [])
    max_chars = int(settings.get("maxChars", 6000))
    prompt = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    shrink_stage = 0
    while len(prompt) > max_chars and shrink_stage < 5:
        shrink_stage += 1
        for port in list(optional):
            if port in value["artifacts"]:
                del value["artifacts"][port]
                prompt = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if len(prompt) <= max_chars:
                    break
        if len(prompt) > max_chars:
            for row in value["artifacts"].values():
                row["content"] = _shrink(row["content"], max(32, max_chars // max(2, len(value["artifacts"]) + 1) // shrink_stage))
            prompt = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars]
    artifact_chars = len(prompt)
    return {
        "kind": "ArtifactContextPack",
        "activeNode": active_node["id"],
        "inputArtifactRefs": [item.as_dict() for item in input_artifact_refs.values()],
        "trace": trace,
        "context": value,
        "promptText": prompt,
        "metrics": {
            "contextChars": artifact_chars,
            "tokenEstimate": (artifact_chars + 3) // 4,
            "raw_source_chars": int(raw_source_chars),
            "artifact_context_chars": artifact_chars,
            "compression_ratio": round(artifact_chars / raw_source_chars, 4) if raw_source_chars else None,
            "maxChars": max_chars,
            "shrinkStage": shrink_stage,
        },
    }
