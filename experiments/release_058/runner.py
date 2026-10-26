"""Fair B0/B1/B2 runner for CGNK Essential Workload V1."""

from __future__ import annotations

import json
import pathlib
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from cgnk_knowledge import (
    SegmentedKnowledgeStore,
    internalize_evidence,
    load_project_knowledge,
    new_project_knowledge_pack,
    retrieve_relevant_knowledge,
    save_project_knowledge,
)

from .essential_workload import BASELINES, Episode, ScenarioChain, SourceFact, canonical_hash


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "evidence_ids", "action", "state_refs", "reused_capability_ids"],
    "properties": {
        "answer": {"type": "string"},
        "evidence_ids": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "action": {"enum": ["ANSWER", "REPAIR", "REUSE", "COMPOSE", "ABSTAIN"]},
        "state_refs": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "reused_capability_ids": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    },
}

SYSTEM_PROMPT = (
    "Complete one bounded episode using only the public task and supplied project context. "
    "Prefer current facts unless the task explicitly asks for history. Cite exact supplied source IDs. "
    "Preserve stated interfaces, localize repairs, reuse existing capabilities, and return only the schema."
)


class Completion(Protocol):
    text: str
    model: str
    request_id: str
    usage: Mapping[str, Any]
    attempts: int


CompleteEpisode = Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], Completion]


@dataclass
class _RouteState:
    baseline: str
    root: pathlib.Path
    sources: list[SourceFact]
    pack: dict[str, Any] | None = None
    persistence_path: pathlib.Path | None = None
    previous_context_ids: tuple[str, ...] = ()
    checkpoint_count: int = 0


def _source_statuses(sources: list[SourceFact]) -> list[dict[str, Any]]:
    superseded = {source_id for row in sources for source_id in row.supersedes}
    return [row.public_dict() | {"status": "superseded" if row.source_id in superseded else "current"} for row in sources]


def _flat_state(sources: list[SourceFact]) -> dict[str, Any]:
    rows = _source_statuses(sources)
    current_by_subject: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["status"] == "current":
            current_by_subject[row["subject_ref"]] = row
    return {
        "kind": "FlatProjectStateV1",
        "current_state": [current_by_subject[key] for key in sorted(current_by_subject)],
        "recent_changes": [
            {"source_id": row["source_id"], "subject_ref": row["subject_ref"], "version": row["version"], "supersedes": row["supersedes"]}
            for row in rows[-8:]
        ],
        "history_index": [
            {"source_id": row["source_id"], "subject_ref": row["subject_ref"], "version": row["version"], "status": row["status"]}
            for row in rows
        ],
        "source_store": rows,
    }


def _direct_context(state: _RouteState) -> dict[str, Any]:
    return {"kind": "DirectWorkspaceSourcesV1", "source_store": _source_statuses(state.sources)}


def _knowledge_item(source: SourceFact, family: str) -> dict[str, Any]:
    tags = tuple(filter(None, (*source.subject_ref.replace(".", " ").split(), family.casefold())))
    evidence: dict[str, Any] = {
        "content": source.content,
        "item_type": "research_finding",
        "scope": "project",
        "source_ref": source.source_id,
        "subject_ref": source.subject_ref,
        "branch_ref": family.casefold(),
        "source_version": source.version,
        "tags": list(tags),
        "importance": "high",
        "need_state": "needed_now",
    }
    if source.source_kind == "summary":
        evidence["tags"].extend(["summary", "lossy-summary"])
        evidence["evidence_kind"] = "derived"
    return evidence


def _apply_additions(state: _RouteState, family: str, additions: tuple[SourceFact, ...]) -> None:
    state.sources.extend(additions)
    if state.baseline != "B2_CGNK_CURRENT":
        return
    if state.pack is None:
        state.pack = new_project_knowledge_pack(state.root.name)
    for source in additions:
        result = internalize_evidence(state.pack, _knowledge_item(source, family))
        state.pack = result["pack"]
        assert state.persistence_path is not None
        save_project_knowledge(state.persistence_path, state.pack, mutation=result.get("persistence_mutation"))


def _restart(state: _RouteState) -> dict[str, Any]:
    if state.baseline == "B2_CGNK_CURRENT":
        assert state.persistence_path is not None and state.pack is not None
        receipt = SegmentedKnowledgeStore(state.persistence_path).create_checkpoint()
        state.pack = load_project_knowledge(state.persistence_path)
        state.checkpoint_count += 1
        return {
            "kind": "CGNKRestartReceipt", "checkpoint_status": receipt["status"],
            "load_status": state.pack._load_receipt.get("checkpoint_status"),
            "sequence": receipt["covered_sequence"],
        }
    path = state.root / "flat-route-state.json"
    payload = [row.public_dict() for row in state.sources]
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    state.sources = [SourceFact(**(dict(row) | {"supersedes": tuple(row.get("supersedes", ())) })) for row in json.loads(path.read_text(encoding="utf-8"))]
    return {"kind": "DirectRestartReceipt", "status": "PASS", "source_count": len(state.sources)}


def _cgnk_context(state: _RouteState, episode: Episode) -> tuple[dict[str, Any], tuple[str, ...]]:
    if state.pack is None:
        state.pack = new_project_knowledge_pack(state.root.name)
    result = retrieve_relevant_knowledge(state.pack, {
        "goal": episode.task,
        "include_reference": True,
        "include_archived": episode.needs_history,
        "include_superseded": episode.needs_history,
        "require_relevance": True,
        "max_items": 8,
    })
    selected: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for item in result["selected_items"]:
        source_refs = [str(row) for row in item.get("source_refs", ())]
        source_id = source_refs[0] if source_refs else str(item.get("id", ""))
        selected_ids.append(source_id)
        selected.append({
            "source_id": source_id,
            "subject_ref": item.get("subject_ref"),
            "version": item.get("source_version"),
            "content": item.get("content"),
            "status": item.get("status", "active"),
            "source_kind": item.get("evidence_kind", "raw"),
        })
    statuses = {row["source_id"]: row for row in _source_statuses(state.sources)}
    direct_ids = {row.source_id for row in episode.additions} | set(state.previous_context_ids)
    for source_id in sorted(direct_ids):
        row = statuses.get(source_id)
        if row is None or source_id in selected_ids:
            continue
        if row["status"] == "superseded" and not episode.needs_history:
            continue
        selected_ids.append(source_id)
        selected.append({
            "source_id": source_id, "subject_ref": row["subject_ref"],
            "version": row["version"], "content": row["content"],
            "status": row["status"], "source_kind": row["source_kind"],
        })
    state.previous_context_ids = tuple(selected_ids)
    context = {
        "kind": "CGNKLocalizedContextV1",
        "selected_evidence": selected,
        "retrieval_receipt": result["metrics"],
        "project_state": {
            "knowledge_revision": state.pack.get("knowledge_revision", 0),
            "checkpoint_count": state.checkpoint_count,
        },
    }
    return context, tuple(selected_ids)


def build_execution_packet(state: _RouteState, chain: ScenarioChain, episode: Episode) -> tuple[dict[str, Any], tuple[str, ...]]:
    if state.baseline == "B0_DIRECT_CHEAP":
        context = _direct_context(state)
        ids = tuple(row.source_id for row in state.sources)
    elif state.baseline == "B1_DIRECT_CHEAP_WITH_FLAT_STATE":
        context = _flat_state(state.sources)
        ids = tuple(row.source_id for row in state.sources)
    else:
        context, ids = _cgnk_context(state, episode)
    return {
        "scenario": {"scenario_id": chain.scenario_id, "family": chain.family, "domain": chain.domain},
        "episode": episode.public_task(),
        "project_context": context,
    }, ids


def evaluate_episode(episode: Episode, answer: Mapping[str, Any], available_ids: tuple[str, ...]) -> dict[str, Any]:
    text = str(answer.get("answer", "")).casefold().replace("+", " plus ")
    evidence_ids = tuple(str(row) for row in answer.get("evidence_ids", ()))
    capability_ids = tuple(
        value.removeprefix("capability.")
        for row in answer.get("reused_capability_ids", ())
        if (value := str(row))
    )
    expected = all(term.casefold() in text for term in episode.expected_terms)
    forbidden = not any(term.casefold() in text for term in episode.forbidden_terms)
    provenance = (
        set(episode.required_evidence_ids) <= set(evidence_ids)
        and set(evidence_ids) <= set(available_ids)
    )
    action = str(answer.get("action", "")) == episode.expected_action
    capability = set(episode.expected_capability_ids) <= set(capability_ids)
    success = expected and forbidden and provenance and action and capability
    return {
        "success": success, "expected_terms_present": expected,
        "forbidden_terms_absent": forbidden, "provenance_correct": provenance,
        "action_correct": action, "capability_reuse_correct": capability,
        "failure_classes": [
            code for condition, code in (
                (expected, "ANSWER_INCORRECT"), (forbidden, "STALE_STATE"),
                (provenance, "PROVENANCE_ERROR"), (action, "ACTION_ERROR"),
                (capability, "CAPABILITY_REUSE_ERROR"),
            ) if not condition
        ],
    }


def _attempts(value: Any) -> int:
    attempts = getattr(value, "attempts", 1)
    return len(attempts) if isinstance(attempts, (list, tuple)) else int(attempts or 1)


def run_chain(
    chain: ScenarioChain,
    baseline: str,
    root: pathlib.Path,
    complete: CompleteEpisode,
    *,
    model_config: Mapping[str, Any],
) -> dict[str, Any]:
    if baseline not in BASELINES:
        raise ValueError(f"unsupported baseline: {baseline}")
    run_id = f"{chain.scenario_id.casefold()}-{baseline.casefold()}-{uuid.uuid4().hex[:10]}"
    route_root = root / run_id
    route_root.mkdir(parents=True, exist_ok=False)
    state = _RouteState(baseline, route_root, [], persistence_path=route_root / "knowledge")
    rows: list[dict[str, Any]] = []
    previous_context_ids: set[str] = set()
    started_chain = time.perf_counter()
    for number, episode in enumerate(chain.episodes, 1):
        restart_receipt = _restart(state) if episode.restart_before else None
        _apply_additions(state, chain.family, episode.additions)
        packet, available_ids = build_execution_packet(state, chain, episode)
        context_value = packet["project_context"]
        context_raw = json.dumps(context_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        current_context_ids = set(available_ids)
        repeated_ids = previous_context_ids & current_context_ids
        previous_context_ids = current_context_ids
        row: dict[str, Any] = {
            "scenario_id": chain.scenario_id, "family": chain.family, "domain": chain.domain,
            "episode_id": episode.episode_id, "episode_number": number, "baseline": baseline,
            "context_chars": len(context_raw), "context_source_count": len(available_ids),
            "available_source_ids": list(available_ids),
            "repeated_context_source_count": len(repeated_ids),
            "restart": episode.restart_before, "restart_receipt": restart_receipt,
            "gold_visible_to_executor": False,
        }
        started = time.perf_counter()
        try:
            completion = complete(run_id, episode.episode_id, packet, model_config)
            answer = json.loads(completion.text)
            assessment = evaluate_episode(episode, answer, available_ids)
            usage = dict(getattr(completion, "usage", {}) or {})
            row.update(assessment | {
                "status": "PASS" if assessment["success"] else "FAIL",
                "answer": answer,
                "model": str(getattr(completion, "model", model_config.get("model", ""))),
                "request_id": str(getattr(completion, "request_id", "")),
                "transport_attempts": _attempts(completion),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "cached_tokens": usage.get("cached_tokens") or dict(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "usage_status": "PROVIDER_REPORTED" if usage else "UNKNOWN",
            })
        except Exception as exc:
            row.update({
                "status": "ERROR", "success": False, "failure_classes": ["PROVIDER_OR_SCHEMA_FAILURE"],
                "error_type": type(exc).__name__, "error": str(exc)[:500],
                "input_tokens": None, "output_tokens": None, "cached_tokens": None,
                "usage_status": "UNKNOWN_AFTER_TRANSPORT_FAILURE",
            })
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        rows.append(row)
    chain_success = all(bool(row["success"]) for row in rows)
    return {
        "kind": "CGNKEssentialChainRun", "schema_version": "1.0", "run_id": run_id,
        "scenario_id": chain.scenario_id, "split": chain.split, "family": chain.family,
        "domain": chain.domain, "baseline": baseline, "chain_success": chain_success,
        "episode_successes": sum(bool(row["success"]) for row in rows),
        "episode_count": len(rows), "logical_calls": len(rows),
        "transport_attempts": sum(int(row.get("transport_attempts") or 0) for row in rows),
        "context_chars": sum(int(row["context_chars"]) for row in rows),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
        "rework_count": sum(int(row["repeated_context_source_count"]) for row in rows),
        "restart_recovery": all(bool(row["success"]) for row in rows if row["restart"]),
        "provenance_accuracy": statistics.fmean(bool(row.get("provenance_correct")) for row in rows),
        "state_consistency": statistics.fmean(not bool(set(row.get("failure_classes", ())) & {"STALE_STATE", "ANSWER_INCORRECT"}) for row in rows),
        "repair_convergence": all(bool(row["success"]) for row in rows if "repair" in chain.family.casefold()),
        "capability_reuse": all(bool(row.get("capability_reuse_correct")) for row in rows if "capability" in chain.family.casefold()),
        "wall_time_ms": round((time.perf_counter() - started_chain) * 1000, 3),
        "episodes": rows,
    }


def summarize_runs(runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_baseline: dict[str, Any] = {}
    for baseline in BASELINES:
        subset = [row for row in runs if row["baseline"] == baseline]
        if not subset:
            continue
        by_baseline[baseline] = {
            "chain_successes": sum(bool(row["chain_success"]) for row in subset),
            "chain_count": len(subset),
            "episode_successes": sum(int(row["episode_successes"]) for row in subset),
            "episode_count": sum(int(row["episode_count"]) for row in subset),
            "context_chars": sum(int(row["context_chars"]) for row in subset),
            "input_tokens": sum(int(row["input_tokens"]) for row in subset),
            "output_tokens": sum(int(row["output_tokens"]) for row in subset),
            "rework_count": sum(int(row["rework_count"]) for row in subset),
            "provenance_accuracy": statistics.fmean(float(row["provenance_accuracy"]) for row in subset),
            "state_consistency": statistics.fmean(float(row["state_consistency"]) for row in subset),
        }
    paired: dict[str, Counter[str]] = {}
    by_scenario = {str(row["scenario_id"]): {} for row in runs}
    for row in runs:
        by_scenario[str(row["scenario_id"])][str(row["baseline"])] = bool(row["chain_success"])
    for direct in BASELINES[:2]:
        counts: Counter[str] = Counter()
        for outcomes in by_scenario.values():
            if direct not in outcomes or "B2_CGNK_CURRENT" not in outcomes:
                continue
            d, c = outcomes[direct], outcomes["B2_CGNK_CURRENT"]
            counts["BOTH_PASS" if d and c else "DIRECT_ONLY" if d else "CGNK_ONLY" if c else "BOTH_FAIL"] += 1
        paired[f"{direct}_VS_B2_CGNK_CURRENT"] = counts
    return {
        "kind": "CGNKEssentialWorkloadSummary", "schema_version": "1.0",
        "run_count": len(runs), "by_baseline": by_baseline,
        "paired_classification": {key: dict(value) for key, value in paired.items()},
        "result_hash": canonical_hash(runs),
    }
