"""Frozen CGNK Essential Workload V1 scenario definitions.

The executor-facing projection deliberately excludes every evaluator field.
All three baselines receive the same public sources, state transitions, and
task sequence. Only their state/evidence organization differs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


BASELINES = ("B0_DIRECT_CHEAP", "B1_DIRECT_CHEAP_WITH_FLAT_STATE", "B2_CGNK_CURRENT")
FAMILIES = (
    "W1_STATE_CONTINUITY",
    "W2_EVIDENCE_PROVENANCE",
    "W3_KNOWLEDGE_UPDATE_SUPERSESSION",
    "W4_REPAIR_CONTINUITY",
    "W5_CAPABILITY_REUSE_COMPOSITION",
    "W6_MIXED_LONG_HORIZON_PROJECT",
)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SourceFact:
    source_id: str
    subject_ref: str
    version: str
    content: str
    supersedes: tuple[str, ...] = ()
    source_kind: str = "raw"

    def public_dict(self) -> dict[str, Any]:
        return asdict(self) | {"supersedes": list(self.supersedes)}


@dataclass(frozen=True)
class Episode:
    episode_id: str
    task: str
    additions: tuple[SourceFact, ...]
    expected_terms: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    expected_action: str = "ANSWER"
    expected_capability_ids: tuple[str, ...] = ()
    restart_before: bool = False
    needs_history: bool = False
    metric_tags: tuple[str, ...] = ()

    def public_task(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "task": self.task,
            "restart_before": self.restart_before,
            "allowed_actions": ["ANSWER", "REPAIR", "REUSE", "COMPOSE", "ABSTAIN"],
        }


@dataclass(frozen=True)
class ScenarioChain:
    scenario_id: str
    split: str
    family: str
    domain: str
    episodes: tuple[Episode, ...]

    def public_manifest(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id, "split": self.split,
            "family": self.family, "domain": self.domain,
            "episodes": [episode.public_task() for episode in self.episodes],
        }

    def frozen_manifest(self) -> dict[str, Any]:
        return asdict(self)


_DOMAINS = (
    "code_config", "structured_data", "document", "logs", "local_automation",
    "knowledge_research", "file_processing", "small_project_maintenance",
)


def _fact(prefix: str, suffix: str, subject: str, version: int, content: str, *, supersedes: tuple[str, ...] = (), kind: str = "raw") -> SourceFact:
    return SourceFact(f"{prefix}.{suffix}", subject, str(version), content, supersedes, kind)


def _state_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix, port1, port2 = f"S{index}.STATE", 8000 + index, 9000 + index
    p1 = _fact(prefix, "PORT.V1", "service.port", 1, f"Service port is {port1}.")
    owner = _fact(prefix, "OWNER.V1", "service.owner", 1, f"Service owner is team-{index}.")
    p2 = _fact(prefix, "PORT.V2", "service.port", 2, f"Current service port is {port2}.", supersedes=(p1.source_id,))
    return ScenarioChain(f"{split[:3].upper()}-W1-{index:02d}", split, FAMILIES[0], domain, (
        Episode("E1", "Record and report the current service port.", (p1,), (str(port1),), (p1.source_id,), metric_tags=("state",)),
        Episode("E2", "Report the current service owner.", (owner,), (f"team-{index}",), (owner.source_id,), metric_tags=("state",)),
        Episode("E3", "After restart, report both the current port and owner.", (), (str(port1), f"team-{index}"), (p1.source_id, owner.source_id), restart_before=True, metric_tags=("state", "restart")),
        Episode("E4", "A newer configuration is now authoritative. Report only the current port.", (p2,), (str(port2),), (p2.source_id,), forbidden_terms=(str(port1),), metric_tags=("state", "supersession")),
        Episode("E5", "Report the historical port and the current port, with sources for both versions.", (), (str(port1), str(port2)), (p1.source_id, p2.source_id), needs_history=True, metric_tags=("state", "history")),
    ))


def _provenance_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix = f"S{index}.PROV"
    raw = _fact(prefix, "RAW", "trace.record", 1, f"Raw record R{index} ended with bytes 0D 0A (CRLF).")
    summary = _fact(prefix, "SUMMARY", "trace.record.summary", 1, f"Summary: record R{index} parsed successfully.", kind="summary")
    order = _fact(prefix, "ORDER", "trace.order", 1, f"Trace T{index}: sequence 41 beta; sequence 42 alpha.")
    negative = _fact(prefix, "NEGATIVE", "retry.policy", 1, "HTTP 400 is never retryable; only 429 and 503 may retry.")
    version = _fact(prefix, "VERSION", "release.version", 2, f"Release document version is {index}.2 and supersedes {index}.1.")
    return ScenarioChain(f"{split[:3].upper()}-W2-{index:02d}", split, FAMILIES[1], domain, (
        Episode("E1", f"What exact byte terminator followed record R{index}? Do not rely on a high-level summary.", (raw, summary), ("CRLF",), (raw.source_id,), forbidden_terms=(summary.source_id,), metric_tags=("provenance", "summary_trap")),
        Episode("E2", f"Which event arrived first for trace T{index}?", (order,), ("beta",), (order.source_id,), metric_tags=("provenance", "ordering")),
        Episode("E3", "Is HTTP 400 retryable? State the negative rule.", (negative,), ("never", "400"), (negative.source_id,), metric_tags=("provenance", "negative_evidence")),
        Episode("E4", "After restart, report the exact release document version.", (version,), (f"{index}.2",), (version.source_id,), restart_before=True, metric_tags=("provenance", "version")),
        Episode("E5", f"State both the exact terminator for R{index} and the first event for T{index}, citing each raw source.", (), ("CRLF", "beta"), (raw.source_id, order.source_id), metric_tags=("provenance", "composition")),
    ))


def _update_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix = f"S{index}.UPDATE"
    p1 = _fact(prefix, "PORT.V1", "app.port", 1, f"App port is {7000 + index}.")
    p2 = _fact(prefix, "PORT.V2", "app.port", 2, f"App port is {7100 + index}.", supersedes=(p1.source_id,))
    t1 = _fact(prefix, "TIMEOUT.V1", "app.timeout", 1, f"Request timeout is {20 + index} seconds.")
    t2 = _fact(prefix, "TIMEOUT.V2", "app.timeout", 2, f"Request timeout is {30 + index} seconds.", supersedes=(t1.source_id,))
    return ScenarioChain(f"{split[:3].upper()}-W3-{index:02d}", split, FAMILIES[2], domain, (
        Episode("E1", "Report the initial app port.", (p1,), (str(7000 + index),), (p1.source_id,), metric_tags=("update",)),
        Episode("E2", "Apply the authoritative port update and report the current port only.", (p2,), (str(7100 + index),), (p2.source_id,), forbidden_terms=(str(7000 + index),), metric_tags=("update", "supersession")),
        Episode("E3", "Report the initial request timeout.", (t1,), (str(20 + index),), (t1.source_id,), metric_tags=("update",)),
        Episode("E4", "After restart and a timeout update, report the current timeout only.", (t2,), (str(30 + index),), (t2.source_id,), forbidden_terms=(str(20 + index),), restart_before=True, metric_tags=("update", "restart")),
        Episode("E5", "Report the complete current app endpoint settings: current port and current timeout.", (), (str(7100 + index), str(30 + index)), (p2.source_id, t2.source_id), forbidden_terms=(str(7000 + index), str(20 + index)), metric_tags=("update", "current_truth")),
    ))


def _repair_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix, fn = f"S{index}.REPAIR", f"normalize_{index}"
    baseline = _fact(prefix, "BASELINE", "repair.baseline", 1, f"Committed baseline exposes {fn}(value); its signature must remain unchanged.")
    fail1 = _fact(prefix, "FAIL1", "repair.failure", 1, f"Test failure: {fn} drops a leading plus sign. Owner is normalize.py.")
    fix1 = _fact(prefix, "FIX1", "repair.receipt", 1, f"Repair receipt: preserve {fn}(value), keep the leading plus, and rerun normalize tests only.")
    fail2 = _fact(prefix, "FAIL2", "repair.failure", 2, f"Second failure: {fn} now duplicates internal spaces. The leading-plus test remains passing.")
    fix2 = _fact(prefix, "FIX2", "repair.receipt", 2, f"Second repair collapses internal spaces without changing {fn}(value) or the plus fix.")
    return ScenarioChain(f"{split[:3].upper()}-W4-{index:02d}", split, FAMILIES[3], domain, (
        Episode("E1", "Identify the preserved repair baseline and interface.", (baseline,), (fn, "unchanged"), (baseline.source_id,), metric_tags=("repair", "baseline")),
        Episode("E2", "Choose the smallest repair for the observed failure.", (fail1,), (fn, "plus", "normalize.py"), (baseline.source_id, fail1.source_id), expected_action="REPAIR", metric_tags=("repair", "localization")),
        Episode("E3", "Record the first repair and name only the tests that must rerun.", (fix1,), ("normalize", "only"), (fix1.source_id,), expected_action="REPAIR", restart_before=True, metric_tags=("repair", "restart")),
        Episode("E4", "A second failure appeared. Preserve the first fix and localize the next change.", (fail2,), ("space", "plus", fn), (fail2.source_id, fix1.source_id), expected_action="REPAIR", metric_tags=("repair", "continuity")),
        Episode("E5", "The repairs are complete. State the converged behavior and preserved public interface.", (fix2,), ("space", "plus", fn), (fix1.source_id, fix2.source_id), expected_action="ANSWER", needs_history=True, metric_tags=("repair", "convergence")),
    ))


def _capability_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix = f"S{index}.CAP"
    cap_a, cap_b = f"text.clean.{index}@1", f"csv.emit.{index}@1"
    a = _fact(prefix, "A", f"capability.{cap_a}", 1, f"Capability {cap_a} trims and normalizes text; parameters include lowercase=false.")
    b = _fact(prefix, "B", f"capability.{cap_b}", 1, f"Capability {cap_b} emits ordered CSV rows from normalized records.")
    receipt = _fact(prefix, "REUSE", "capability.receipt", 1, f"Validated reuse receipt: {cap_a} and {cap_b} compose without a new capability.")
    return ScenarioChain(f"{split[:3].upper()}-W5-{index:02d}", split, FAMILIES[4], domain, (
        Episode("E1", "Select the existing capability that trims and normalizes text.", (a,), (cap_a,), (a.source_id,), expected_action="REUSE", expected_capability_ids=(cap_a,), metric_tags=("capability", "reuse")),
        Episode("E2", "Reuse the text capability with lowercase disabled; do not create a new capability.", (), (cap_a, "lowercase"), (a.source_id,), expected_action="REUSE", expected_capability_ids=(cap_a,), metric_tags=("capability", "parameterize")),
        Episode("E3", "Select the existing capability that emits ordered CSV rows.", (b,), (cap_b,), (b.source_id,), expected_action="REUSE", expected_capability_ids=(cap_b,), metric_tags=("capability", "reuse")),
        Episode("E4", "Compose normalization and CSV emission; name both existing capabilities.", (receipt,), (cap_a, cap_b), (a.source_id, b.source_id, receipt.source_id), expected_action="COMPOSE", expected_capability_ids=(cap_a, cap_b), restart_before=True, metric_tags=("capability", "composition")),
        Episode("E5", "A repeat request changes only the delimiter. Reuse the same composition and avoid a false capability gap.", (), (cap_a, cap_b, "delimiter"), (a.source_id, b.source_id), expected_action="REUSE", expected_capability_ids=(cap_a, cap_b), metric_tags=("capability", "false_gap")),
    ))


def _mixed_chain(index: int, split: str, domain: str) -> ScenarioChain:
    prefix, cap = f"S{index}.MIX", f"log.parse.{index}@1"
    goal = _fact(prefix, "GOAL", "project.goal", 1, f"Maintain service-{index}; preserve its parser API and produce an evidence-backed incident note.")
    old = _fact(prefix, "PORT.V1", "service.port", 1, f"service-{index} listened on {6000 + index}.")
    new = _fact(prefix, "PORT.V2", "service.port", 2, f"service-{index} now listens on {6100 + index}.", supersedes=(old.source_id,))
    capability = _fact(prefix, "CAP", f"capability.{cap}", 1, f"Existing capability {cap} parses local service logs while preserving raw line references.")
    failure = _fact(prefix, "FAIL", "project.failure", 1, f"Acceptance failure: incident note still names stale port {6000 + index}; parser API tests pass.")
    raw = _fact(prefix, "RAW", "incident.raw", 1, f"Raw incident line: service-{index} accepted connection on {6100 + index} at sequence 77.")
    repaired = _fact(prefix, "REPAIRED", "project.repair.receipt", 1, f"Repair complete: incident note now uses port {6100 + index}; parser API remains unchanged.")
    return ScenarioChain(f"{split[:3].upper()}-W6-{index:02d}", split, FAMILIES[5], domain, (
        Episode("E1", "State the project goal and interface constraint.", (goal, old), (f"service-{index}", "parser API"), (goal.source_id,), metric_tags=("mixed", "state")),
        Episode("E2", "Apply the current port update and report only the current port.", (new,), (str(6100 + index),), (new.source_id,), forbidden_terms=(str(6000 + index),), metric_tags=("mixed", "update")),
        Episode("E3", "Reuse the existing log parser capability for the incident.", (capability, raw), (cap, "raw"), (capability.source_id, raw.source_id), expected_action="REUSE", expected_capability_ids=(cap,), restart_before=True, metric_tags=("mixed", "capability", "restart")),
        Episode("E4", "Localize the acceptance failure without changing the passing parser API.", (failure,), ("incident note", str(6100 + index), "parser API"), (failure.source_id, new.source_id), expected_action="REPAIR", metric_tags=("mixed", "repair")),
        Episode("E5", "The repair is complete. Answer with the final evidence-backed incident statement, current port, and exact sequence.", (repaired,), (str(6100 + index), "77"), (new.source_id, raw.source_id), expected_action="ANSWER", metric_tags=("mixed", "provenance")),
    ))


_BUILDERS = (_state_chain, _provenance_chain, _update_chain, _repair_chain, _capability_chain, _mixed_chain)


def _chains(split: str, variants: range) -> tuple[ScenarioChain, ...]:
    rows: list[ScenarioChain] = []
    for family_index, builder in enumerate(_BUILDERS):
        for variant in variants:
            index = family_index * 10 + variant
            rows.append(builder(index, split, _DOMAINS[(index - 1) % len(_DOMAINS)]))
    return tuple(rows)


def development_chains() -> tuple[ScenarioChain, ...]:
    return _chains("development", range(1, 3))


def formal_chains() -> tuple[ScenarioChain, ...]:
    return _chains("formal", range(3, 6))


def workload_manifest() -> dict[str, Any]:
    development, formal = development_chains(), formal_chains()
    frozen = [row.frozen_manifest() for row in (*development, *formal)]
    return {
        "kind": "CGNKEssentialWorkloadV1", "schema_version": "1.0",
        "development_chain_count": len(development), "formal_chain_count": len(formal),
        "total_chain_count": len(frozen),
        "development_episode_count": sum(len(row.episodes) for row in development),
        "formal_episode_count": sum(len(row.episodes) for row in formal),
        "families": list(FAMILIES), "baselines": list(BASELINES),
        "chains": frozen, "manifest_hash": canonical_hash(frozen),
    }
