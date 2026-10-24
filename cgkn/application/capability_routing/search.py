from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec

from .contracts import (
    CapabilityCandidate,
    CapabilityEffect,
    CapabilitySearchRequest,
    CapabilitySearchResult,
    stable_hash,
)


SEARCH_POLICY_VERSION = "capability-search-v2"

_WORD = re.compile(r"[a-z0-9]+")
_ALIASES = {
    "answer": {"respond", "conversation", "question", "grounded"},
    "conversation": {"answer", "respond", "chat", "question"},
    "retrieve": {"search", "find", "lookup", "read"},
    "search": {"retrieve", "find", "lookup"},
    "internalize": {"ingest", "learn", "knowledge", "update"},
    "write": {"create", "generate", "modify", "patch", "save"},
    "test": {"verify", "validate", "pytest", "acceptance"},
    "execute": {"run", "command", "smoke"},
    "inspect": {"read", "list", "workspace"},
    "repair": {"patch", "fix", "correct"},
}


def _tokens(value: str) -> set[str]:
    result = set(_WORD.findall(value.lower().replace("_", " ").replace("-", " ").replace(".", " ")))
    expanded = set(result)
    for token in result:
        expanded.update(_ALIASES.get(token, ()))
    return expanded


def _tuple_metadata(metadata: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = metadata.get(name, ())
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def _effect_text(component: ComponentSpec, descriptor: CapabilityDescriptor) -> tuple[str, ...]:
    values = list(descriptor.declared_effects)
    for key, value in component.effects.items():
        values.append(f"{key}.{value}")
    return tuple(str(item).lower() for item in values)


def classify_effect(component: ComponentSpec, descriptor: CapabilityDescriptor) -> CapabilityEffect:
    effects = _effect_text(component, descriptor)
    text = " ".join(effects)
    if any(term in text for term in ("external.write", "publish", "network.write", "external_action")):
        return CapabilityEffect.EXTERNAL_ACTION
    if "knowledge.write" in text or ("knowledge" in text and "write" in text):
        return CapabilityEffect.WRITE_KNOWLEDGE
    if any(term in text for term in ("filesystem.write", "code.write", "source.write", "file.write")):
        return CapabilityEffect.WRITE_CODE
    if any(term in text for term in ("maintenance", "compact", "migrate")):
        return CapabilityEffect.MAINTENANCE
    if any(term in text for term in ("evaluate", "test.observe", "acceptance", "pytest")):
        return CapabilityEffect.EVALUATION
    if any(term.startswith(("process.execute", "system.", "shell.")) or term in {"system", "shell"} for term in effects):
        return CapabilityEffect.SYSTEM
    return CapabilityEffect.READ_ONLY


@dataclass(frozen=True)
class CapabilitySemanticRecord:
    capability_ref: str
    capability_id: str
    version: str
    purpose: str
    input_contract: tuple[str, ...]
    output_contract: tuple[str, ...]
    effect: CapabilityEffect
    required_state: tuple[str, ...]
    permissions: tuple[str, ...]
    scope: tuple[str, ...]
    limitations: tuple[str, ...]
    qualification: str
    executor_ref: str
    executor_kinds: tuple[str, ...]
    lifecycle_status: str
    observed_usage_count: int
    observed_success: int
    observed_failure: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_ref": self.capability_ref,
            "capability_id": self.capability_id,
            "version": self.version,
            "purpose": self.purpose,
            "input_contract": list(self.input_contract),
            "output_contract": list(self.output_contract),
            "effect": self.effect.value,
            "required_state": list(self.required_state),
            "permissions": list(self.permissions),
            "scope": list(self.scope),
            "limitations": list(self.limitations),
            "qualification": self.qualification,
            "executor_ref": self.executor_ref,
            "executor_kinds": list(self.executor_kinds),
            "lifecycle_status": self.lifecycle_status,
            "observed_usage_count": self.observed_usage_count,
            "observed_success": self.observed_success,
            "observed_failure": self.observed_failure,
        }

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.capability_ref,
                self.purpose,
                *self.input_contract,
                *self.output_contract,
                self.effect.value,
                *self.limitations,
                self.executor_ref,
            )
        )


def derive_record(descriptor: CapabilityDescriptor, component: ComponentSpec) -> CapabilitySemanticRecord:
    metadata = component.metadata
    provenance = descriptor.provenance
    purpose = str(
        metadata.get("purpose")
        or metadata.get("goal")
        or metadata.get("description")
        or provenance.get("purpose")
        or provenance.get("goal")
        or descriptor.capability_id.replace(".", " ")
    ).strip()
    qualified = descriptor.lifecycle_status is CapabilityLifecycle.ADMITTED and bool(descriptor.test_refs)
    return CapabilitySemanticRecord(
        descriptor.ref,
        descriptor.capability_id,
        descriptor.version,
        purpose,
        tuple(f"{port.name}:{port.artifact_type}" for port in component.input_ports),
        tuple(f"{port.name}:{port.artifact_type}" for port in component.output_ports),
        classify_effect(component, descriptor),
        _tuple_metadata(metadata, "required_state"),
        _tuple_metadata(metadata, "permissions"),
        _tuple_metadata(metadata, "scope"),
        _tuple_metadata(metadata, "limitations"),
        "QUALIFIED" if qualified else "UNQUALIFIED",
        descriptor.executor_ref,
        tuple(descriptor.allowed_executor_kinds),
        descriptor.lifecycle_status.value,
        descriptor.observed_usage_count,
        descriptor.observed_success,
        descriptor.observed_failure,
    )


def _estimate_tokens(value: Any) -> int:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return math.ceil(len(raw) / 4)


class CapabilitySearchIndex:
    """A rebuildable projection over CapabilityRegistry, never capability authority."""

    def __init__(self, records: Iterable[CapabilitySemanticRecord], authority_hash: str) -> None:
        self.records = tuple(sorted(records, key=lambda item: item.capability_ref))
        self._records_by_ref = {item.capability_ref: item for item in self.records}
        postings: dict[str, set[str]] = {}
        for record in self.records:
            for token in _tokens(record.search_text):
                postings.setdefault(token, set()).add(record.capability_ref)
        self._postings = {token: frozenset(refs) for token, refs in postings.items()}
        self.authority_hash = authority_hash
        self.index_hash = stable_hash(
            {"policy": SEARCH_POLICY_VERSION, "authority_hash": authority_hash, "records": [item.as_dict() for item in self.records]}
        )

    @classmethod
    def rebuild(cls, registry: CapabilityRegistry) -> "CapabilitySearchIndex":
        descriptors = registry.query()
        records = [derive_record(item, registry.components[item.component_ref]) for item in descriptors]
        authority_hash = stable_hash({"capabilities": [item.as_dict() for item in descriptors]})
        return cls(records, authority_hash)

    @property
    def policy_hash(self) -> str:
        return stable_hash({"version": SEARCH_POLICY_VERSION, "aliases": {key: sorted(value) for key, value in sorted(_ALIASES.items())}})

    def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResult:
        started = time.perf_counter()
        rejected: dict[str, tuple[str, ...]] = {}
        eligible: list[CapabilitySemanticRecord] = []
        for record in self.records:
            reasons = self._ineligibility(record, request)
            if reasons:
                rejected[record.capability_ref] = reasons
            else:
                eligible.append(record)

        query_tokens = _tokens(request.goal)
        if request.exact_ref:
            retrieval_refs = {request.exact_ref}
        else:
            retrieval_refs: set[str] = set()
            for token in query_tokens:
                retrieval_refs.update(self._postings.get(token, ()))
        eligible_by_ref = {item.capability_ref: item for item in eligible}
        retrieval_pool = [eligible_by_ref[ref] for ref in sorted(retrieval_refs) if ref in eligible_by_ref]
        scored = sorted(
            ((record, self._score(record, request, query_tokens)) for record in retrieval_pool),
            key=lambda item: (-item[1], item[0].capability_ref),
        )
        candidates = tuple(
            CapabilityCandidate(
                record.capability_ref,
                round(score, 6),
                record.effect,
                record.purpose,
                record.executor_ref,
                record.qualification,
                {
                    "input_contract": list(record.input_contract),
                    "output_contract": list(record.output_contract),
                    "version": record.version,
                    "permissions": list(record.permissions),
                    "scope": list(record.scope),
                    "limitations": list(record.limitations),
                },
            )
            for record, score in scored[: request.top_k]
            if score > 0 or request.exact_ref == record.capability_ref
        )
        full_payload = [item.as_dict() for item in self.records]
        topk_payload = [item.as_dict() for item in candidates]
        return CapabilitySearchResult(
            candidates,
            len(eligible),
            len(retrieval_pool),
            len(self.records),
            rejected,
            _estimate_tokens(full_payload),
            _estimate_tokens(topk_payload),
            self.index_hash,
            self.policy_hash,
            round((time.perf_counter() - started) * 1000, 6),
        )

    @staticmethod
    def _ineligibility(record: CapabilitySemanticRecord, request: CapabilitySearchRequest) -> tuple[str, ...]:
        reasons: list[str] = []
        if request.require_qualified and record.qualification != "QUALIFIED":
            reasons.append("UNQUALIFIED")
        if request.requested_version and record.version != request.requested_version:
            reasons.append("VERSION_MISMATCH")
        if request.exact_ref and record.capability_ref != request.exact_ref:
            reasons.append("IDENTITY_MISMATCH")
        required_inputs = {item.split(":", 1)[0] for item in record.input_contract}
        available = set(request.available_inputs)
        if required_inputs and not required_inputs.issubset(available):
            reasons.append("MISSING_INPUT")
        if record.effect not in set(request.allowed_effects):
            reasons.append("EFFECT_NOT_ALLOWED")
        if not set(record.permissions).issubset(set(request.permissions)):
            reasons.append("PERMISSION_DENIED")
        if not set(record.required_state).issubset(set(request.available_state)):
            reasons.append("REQUIRED_STATE_MISSING")
        if record.scope and not set(record.scope).issubset(set(request.allowed_scope)):
            reasons.append("SCOPE_DENIED")
        return tuple(reasons)

    @staticmethod
    def _score(record: CapabilitySemanticRecord, request: CapabilitySearchRequest, query_tokens: set[str]) -> float:
        identity = record.capability_ref.rsplit("@", 1)[0]
        identity_tokens = _tokens(identity)
        raw_query_tokens = set(_WORD.findall(request.goal.lower().replace("_", " ").replace("-", " ").replace(".", " ")))
        raw_identity_tokens = set(_WORD.findall(identity.lower().replace("_", " ").replace("-", " ").replace(".", " ")))
        purpose_tokens = _tokens(record.purpose)
        contract_tokens = _tokens(" ".join((*record.input_contract, *record.output_contract)))
        effect_tokens = _tokens(record.effect.value)
        score = (
            12.0 * len(raw_query_tokens & raw_identity_tokens)
            + 4.0 * len(query_tokens & identity_tokens)
            + 4.0 * len(query_tokens & purpose_tokens)
            + 2.0 * len(query_tokens & contract_tokens)
            + 1.0 * len(query_tokens & effect_tokens)
        )
        normalized_goal = re.sub(r"[^a-z0-9.@_-]+", "", request.goal.lower())
        normalized_ref = record.capability_ref.lower()
        if request.exact_ref == record.capability_ref:
            score += 1000.0
        elif normalized_goal in {normalized_ref, normalized_ref.rsplit("@", 1)[0]}:
            score += 500.0
        if record.observed_usage_count:
            score += record.observed_success / record.observed_usage_count
        return score

