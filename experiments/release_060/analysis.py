"""Deterministic stratified analysis for ITER-060 receipts."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
import pathlib
from statistics import mean
from typing import Any, Iterable, Mapping

from .contracts import ArchitectureBaseline, canonical_hash
from .specs import development_families, formal_families


VERDICTS = {"PROVEN", "PROVEN_DIRECTIONALLY", "NEUTRAL", "HARMFUL", "NOT_NEEDED_AT_TESTED_SCALE", "INSUFFICIENT_EVIDENCE"}


def _metric(row: Mapping[str, Any]) -> dict[str, Any]:
    calls = list(row.get("call_records") or ())
    usage = dict(row.get("usage_totals") or {})
    tokens = usage.get("total_tokens")
    return {
        "success": int(row.get("status") == "PASS"),
        "calls": int(row.get("provider_calls", 0)),
        "tokens": int(tokens) if isinstance(tokens, int) else None,
        "cost_usd": float(row["estimated_cost_usd"]) if row.get("estimated_cost_usd") is not None else None,
        "duration_ms": int(row.get("duration_ms", 0)),
        "repair_calls": sum(call.get("purpose") == "PUBLIC_REPAIR" for call in calls),
        "failed_calls": sum(call.get("status") != "COMPLETED" for call in calls),
        "input_chars": sum(int(call.get("request_chars", 0)) for call in calls),
        "max_input_chars": max((int(call.get("request_chars", 0)) for call in calls), default=0),
        "context_growth_chars": max(0, max((int(call.get("request_chars", 0)) for call in calls), default=0) - min((int(call.get("request_chars", 0)) for call in calls), default=0)),
    }


def _aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows); metrics = [_metric(row) for row in values]
    successes = sum(item["success"] for item in metrics)
    def avg(key: str) -> float | None:
        observed = [item[key] for item in metrics if item[key] is not None]
        return round(mean(observed), 6) if observed else None
    total_cost = sum(item["cost_usd"] or 0 for item in metrics)
    return {
        "attempts": len(values), "successes": successes,
        "success_rate": round(successes / len(values), 6) if values else None,
        "average_calls": avg("calls"), "average_tokens": avg("tokens"),
        "average_cost_usd": avg("cost_usd"), "cost_per_success_usd": round(total_cost / successes, 8) if successes else None,
        "average_duration_ms": avg("duration_ms"), "average_repair_calls": avg("repair_calls"),
        "average_failed_calls": avg("failed_calls"), "average_input_chars": avg("input_chars"),
        "average_max_input_chars": avg("max_input_chars"), "average_context_growth_chars": avg("context_growth_chars"),
    }


def _best_routes(rows: list[dict[str, Any]]) -> list[str]:
    if not rows: return []
    best_success = max(float(row["success_rate"] or 0) for row in rows)
    quality = [row for row in rows if float(row["success_rate"] or 0) == best_success]
    known = [row for row in quality if row.get("cost_per_success_usd") is not None]
    if not known: return [str(row["baseline"]) for row in quality]
    best_cost = min(float(row["cost_per_success_usd"]) for row in known)
    return [str(row["baseline"]) for row in known if float(row["cost_per_success_usd"]) == best_cost]


def _verdict(success_left: float, success_right: float, cost_left: float | None, cost_right: float | None) -> str:
    if success_left > success_right:
        return "PROVEN_DIRECTIONALLY"
    if success_left < success_right:
        return "HARMFUL"
    if cost_left is not None and cost_right is not None:
        if cost_left <= cost_right * 0.9: return "PROVEN_DIRECTIONALLY"
        if cost_left >= cost_right * 1.1: return "HARMFUL"
    return "NEUTRAL"


def analyze(receipts: Iterable[Mapping[str, Any]], *, source_version: str = "") -> dict[str, Any]:
    rows = [dict(row) for row in receipts if not source_version or row.get("source_version") == source_version]
    families = {item.family_id: item for item in development_families() + formal_families()}
    if not rows: raise ValueError("analysis requires at least one receipt")
    enriched = []
    for row in rows:
        family = families[str(row["family_id"])]
        enriched.append(row | {"complexity": family.complexity, "project_type": family.project_type, "raw_complexity": dict(family.raw_complexity)})
    complexity_rows = []
    for tier in ("LOW", "MEDIUM", "HIGH"):
        for baseline in ArchitectureBaseline:
            selected = [row for row in enriched if row["complexity"] == tier and row["baseline"] == baseline.value]
            complexity_rows.append({"complexity": tier, "baseline": baseline.value, **_aggregate(selected)})
    frontier = []
    for tier in ("LOW", "MEDIUM", "HIGH"):
        selected = [row for row in complexity_rows if row["complexity"] == tier]
        frontier.append({"complexity": tier, "best_or_pareto": _best_routes(selected), "routes": selected})
    type_rows = []
    for project_type in sorted({row["project_type"] for row in enriched}):
        candidates = []
        for baseline in ArchitectureBaseline:
            selected = [row for row in enriched if row["project_type"] == project_type and row["baseline"] == baseline.value]
            candidates.append({"project_type": project_type, "baseline": baseline.value, **_aggregate(selected)})
        type_rows.append({"project_type": project_type, "best_or_pareto": _best_routes(candidates), "routes": candidates})
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched: by_family[str(row["family_id"])].append(row)
    discordant = []
    for family_id, group in sorted(by_family.items()):
        statuses = {str(row["baseline"]): str(row["status"]) for row in group}
        if len(set(statuses.values())) > 1:
            discordant.append({"family_id": family_id, "complexity": group[0]["complexity"], "project_type": group[0]["project_type"], "statuses": statuses})
    baseline_summary = {baseline.value: _aggregate(row for row in enriched if row["baseline"] == baseline.value) for baseline in ArchitectureBaseline}
    b0=baseline_summary[ArchitectureBaseline.DIRECT_CHEAP.value]; b1=baseline_summary[ArchitectureBaseline.DIRECT_CHEAP_FLAT_STATE.value]; b2=baseline_summary[ArchitectureBaseline.MINIMAL_CGNK.value]; b3=baseline_summary[ArchitectureBaseline.FULL_CGNK.value]
    claims = {
        "DIRECT_LOW_COMPLEXITY_BENEFIT": _claim_low(complexity_rows),
        "MINIMAL_CGNK_BENEFIT": _verdict(float(b2["success_rate"] or 0), float(b1["success_rate"] or 0), b2["cost_per_success_usd"], b1["cost_per_success_usd"]),
        "FULL_CGNK_BENEFIT": _verdict(float(b3["success_rate"] or 0), float(b2["success_rate"] or 0), b3["cost_per_success_usd"], b2["cost_per_success_usd"]),
        "EVIDENCE_STATE_BENEFIT": _verdict(float(b2["success_rate"] or 0), float(b1["success_rate"] or 0), b2["cost_per_success_usd"], b1["cost_per_success_usd"]),
        "DAG_BENEFIT": _verdict(float(b3["success_rate"] or 0), float(b2["success_rate"] or 0), b3["cost_per_success_usd"], b2["cost_per_success_usd"]),
        "REPAIR_ORCHESTRATION_BENEFIT": _repair_claim(enriched),
        "CAPABILITY_REUSE_BENEFIT": "INSUFFICIENT_EVIDENCE",
        "COMPLEXITY_FRONTIER": "PROVEN_DIRECTIONALLY" if len({tuple(item["best_or_pareto"]) for item in frontier}) > 1 else "INSUFFICIENT_EVIDENCE",
        "CORPUS_DIVERSITY_STATUS": "PROVEN" if len(by_family) >= 24 and len({row["project_type"] for row in enriched}) >= 8 and len({row["complexity"] for row in enriched}) == 3 else "PROVEN_DIRECTIONALLY" if len(by_family) >= 12 else "INSUFFICIENT_EVIDENCE",
    }
    assert set(claims.values()) <= VERDICTS
    failures = Counter()
    for row in enriched:
        if row["status"] == "PASS": continue
        public = list(row.get("public_results") or ())
        failure = str(public[-1].get("failure_class") if public else row.get("status") or "UNKNOWN")
        failures[failure or "UNKNOWN"] += 1
    result = {
        "kind": "CGNKITER060Analysis", "schema_version": "1.0", "source_version": source_version,
        "attempt_count": len(enriched), "family_count": len(by_family), "baseline_summary": baseline_summary,
        "complexity_frontier": frontier, "project_type_matrix": type_rows, "discordant_families": discordant,
        "failure_classes": dict(sorted(failures.items())), "claim_ledger": claims,
        "corpus_profile": {"families": len(by_family), "attempts": len(enriched), "splits": dict(Counter(row["split"] for row in enriched)), "complexities": dict(Counter(row["complexity"] for row in enriched)), "project_types": dict(Counter(row["project_type"] for row in enriched)), "statuses": dict(Counter(row["status"] for row in enriched))},
    }
    result["analysis_hash"] = canonical_hash(result)
    return result


def _claim_low(rows: list[dict[str, Any]]) -> str:
    low = {row["baseline"]: row for row in rows if row["complexity"] == "LOW"}
    direct = low.get(ArchitectureBaseline.DIRECT_CHEAP.value)
    if not direct: return "INSUFFICIENT_EVIDENCE"
    others = [row for key, row in low.items() if key != ArchitectureBaseline.DIRECT_CHEAP.value]
    if all(float(direct["success_rate"] or 0) >= float(row["success_rate"] or 0) for row in others) and all(direct["cost_per_success_usd"] is not None and row["cost_per_success_usd"] is not None and direct["cost_per_success_usd"] <= row["cost_per_success_usd"] for row in others): return "PROVEN_DIRECTIONALLY"
    return "NEUTRAL"


def _repair_claim(rows: list[dict[str, Any]]) -> str:
    repair = [row for row in rows if int(row["raw_complexity"].get("repair_rounds", 0)) > 0]
    if len({row["family_id"] for row in repair}) < 2: return "INSUFFICIENT_EVIDENCE"
    b2=_aggregate(row for row in repair if row["baseline"] == ArchitectureBaseline.MINIMAL_CGNK.value)
    b3=_aggregate(row for row in repair if row["baseline"] == ArchitectureBaseline.FULL_CGNK.value)
    return _verdict(float(b3["success_rate"] or 0), float(b2["success_rate"] or 0), b3["cost_per_success_usd"], b2["cost_per_success_usd"])


def write_analysis_assets(result: Mapping[str, Any], output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("complexity_frontier.json", result["complexity_frontier"]), ("project_type_matrix.json", result["project_type_matrix"]),
        ("failure_analysis.json", {"failure_classes": result["failure_classes"], "discordant_families": result["discordant_families"]}),
        ("corpus_profile.json", result["corpus_profile"]), ("claim_ledger.json", result["claim_ledger"]), ("main_results.json", result),
    ):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with (output / "main_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("complexity","baseline","attempts","successes","success_rate","average_calls","average_tokens","cost_per_success_usd","average_duration_ms","average_repair_calls","average_context_growth_chars"))
        writer.writeheader()
        for item in result["complexity_frontier"]:
            for row in item["routes"]: writer.writerow({key: row.get(key) for key in writer.fieldnames})
    directions = ["# CGNK Modification Direction", "", "Decisions are evidence-bound recommendations; no production default changes are made in ITER-060.", ""]
    claims = result["claim_ledger"]
    directions += [
        f"- Direct path → `{claims['DIRECT_LOW_COMPLEXITY_BENEFIT']}` → retain as the simple-project candidate.",
        f"- Evidence/state substrate → `{claims['EVIDENCE_STATE_BENEFIT']}` → retain, simplify, or strengthen only in the next iteration.",
        f"- CapabilityTree/ExecutionDAG → `{claims['DAG_BENEFIT']}` → keep optional unless formal HIGH evidence proves necessity.",
        f"- Full repair orchestration → `{claims['REPAIR_ORCHESTRATION_BENEFIT']}` → do not promote without repair-heavy benefit.",
        "- Capability reuse → `INSUFFICIENT_EVIDENCE` → design a separate cross-family reuse study before claiming benefit.",
    ]
    (output / "modification_direction.md").write_text("\n".join(directions) + "\n", encoding="utf-8")
    candidates = {"kind":"CGNKFutureProjectProblemCandidates","schema_version":"1.0","candidates":[
        {"id":"CROSS_FAMILY_REUSE","reason":"Capability reuse is not identified by within-family generation."},
        {"id":"NATURAL_MULTI_ROUND_REPAIR","reason":"Increase repair-path density without hidden failure hints."},
        {"id":"LONGER_RESTART_CHAIN","reason":"Separate state/evidence benefit from model context capacity."},
        {"id":"DEPENDENCY_CONTRACT_CHANGE","reason":"Test localized invalidation under public interface evolution."},
    ]}
    candidates["index_hash"] = canonical_hash(candidates)
    (output / "future_project_problem_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, sort_keys=True, indent=2)+"\n",encoding="utf-8")
    frontier = list(result["complexity_frontier"])
    distinct = len({tuple(item["best_or_pareto"]) for item in frontier}) > 1
    high_discordant = [item for item in result["discordant_families"] if item["complexity"] == "HIGH"]
    b3_only = [
        item for item in high_discordant
        if item["statuses"].get(ArchitectureBaseline.FULL_CGNK.value) == "PASS"
        and any(status != "PASS" for key, status in item["statuses"].items() if key != ArchitectureBaseline.FULL_CGNK.value)
    ]
    boundary = {
        "kind":"CGNKArchitectureBoundaryMap","schema_version":"1.0",
        "boundaries":[{"complexity":item["complexity"],"minimum_supported_routes":item["best_or_pareto"],"evidence":"paired formal family outcomes plus cost-per-success tie-break"} for item in frontier],
        "router_reopen_evidence":"YES" if distinct else "NO",
        "full_orchestration":"KEEP_OPTIONAL" if b3_only or result["claim_ledger"]["REPAIR_ORCHESTRATION_BENEFIT"] in {"PROVEN","PROVEN_DIRECTIONALLY"} else "NOT_NEEDED_AT_TESTED_SCALE",
        "full_cgnk_simplification_candidate":"YES" if result["claim_ledger"]["FULL_CGNK_BENEFIT"] in {"NEUTRAL","HARMFUL","NOT_NEEDED_AT_TESTED_SCALE"} else "NO",
        "evidence_limit":"No production default or Router change is authorized by this research release.",
    }
    boundary["map_hash"] = canonical_hash(boundary)
    (output/"architecture_boundary_map.json").write_text(json.dumps(boundary,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    recommendation = ["# Next Iteration Recommendation","",f"Formal architecture boundary status: {result['claim_ledger']['COMPLEXITY_FRONTIER']}.",""]
    if boundary["full_cgnk_simplification_candidate"] == "YES":
        recommendation.append("Study a simplification candidate that keeps evidence/state primitives and makes full orchestration optional; do not change the current default until a separately preregistered validation passes.")
    else:
        recommendation.append("Retain full orchestration as an optional path and run a focused high-complexity repair/restart replication before any admission policy change.")
    recommendation += ["", "Capability reuse remains separately unproven and needs a cross-family reuse experiment. Multi-Agent and Architecture Router remain out of scope."]
    (output/"next_iteration_recommendation.md").write_text("\n".join(recommendation)+"\n",encoding="utf-8")
    _write_technical_report(result, boundary, output/"technical_report.md")


def _write_technical_report(result: Mapping[str, Any], boundary: Mapping[str, Any], path: pathlib.Path) -> None:
    profile=result["corpus_profile"]; claims=result["claim_ledger"]
    sections = [
        ("Abstract", f"ITER-060 compares four architecture levels across {profile['families']} generated-original project families and {profile['attempts']} isolated attempts. Findings are directional and bound to the frozen route and corpus."),
        ("Motivation", "Earlier task studies did not locate a stable point at which full orchestration became necessary. This study moves the unit of evaluation from isolated answers to evolving projects."),
        ("Previous Evidence", "ITER-056 through ITER-059 motivated a project-first ablation and a write-only formal Project Corpus."),
        ("Research Questions", "The preregistered questions cover success degradation, evidence/state value, DAG value, repair, restart, provenance, reuse, and the minimum necessary architecture."),
        ("Project Corpus", f"The analyzed corpus slice contains {profile['families']} families and {profile['attempts']} baseline attempts; complete local snapshots are not redistributed."),
        ("Complexity Definition", "LOW, MEDIUM, and HIGH labels are accompanied by raw file, module, dependency, episode, state, version, repair, capability, and knowledge-source metrics."),
        ("Project Families", f"Project-type counts: {json.dumps(profile['project_types'], sort_keys=True)}."),
        ("Experimental Design", "Family-paired baselines run in isolated workspaces. Development and formal holdout families are disjoint and all outcomes are retained."),
        ("Baselines", "B0 is Direct Cheap, B1 adds fair flat state, B2 adds minimal evidence/state/recovery structure, and B3 uses the frozen Blueprint plus current Tree/DAG runtime."),
        ("Direct Cheap", f"Aggregate: {json.dumps(result['baseline_summary'][ArchitectureBaseline.DIRECT_CHEAP.value], sort_keys=True)}."),
        ("Flat-State Direct", f"Aggregate: {json.dumps(result['baseline_summary'][ArchitectureBaseline.DIRECT_CHEAP_FLAT_STATE.value], sort_keys=True)}."),
        ("Minimal CGNK", f"Aggregate: {json.dumps(result['baseline_summary'][ArchitectureBaseline.MINIMAL_CGNK.value], sort_keys=True)}."),
        ("Full CGNK", f"Aggregate: {json.dumps(result['baseline_summary'][ArchitectureBaseline.FULL_CGNK.value], sort_keys=True)}."),
        ("Fairness", "Provider, expected model, temperature, schema foundation, evaluator, tool access, budgets, OS, and acceptance are shared. Architectural context is the intended treatment."),
        ("Low Complexity", _frontier_text(result,"LOW")),
        ("Medium Complexity", _frontier_text(result,"MEDIUM")),
        ("High Complexity", _frontier_text(result,"HIGH")),
        ("Project Type Results", "Eight type-stratified matrices are recorded; no global route is inferred when type cells disagree."),
        ("Success", f"Status counts: {json.dumps(profile['statuses'], sort_keys=True)}."),
        ("Context Growth", "Per-attempt input characters and maximum-minus-minimum context growth are reported alongside tokens, rather than treated as quality proxies."),
        ("Rework", "Public-repair calls are counted as rework; failed calls remain cost-bearing when usage is reported."),
        ("Repair", f"Repair orchestration verdict: {claims['REPAIR_ORCHESTRATION_BENEFIT']}."),
        ("State Errors", "State-heavy episodes use real restart boundaries. Failures are classified at the public evaluator without hidden feedback."),
        ("Provenance", "Provenance-sensitive families require deterministic version/checksum evidence and remain generated-original research artifacts."),
        ("Capability Reuse", f"Verdict: {claims['CAPABILITY_REUSE_BENEFIT']}; within-family repeated capability refs cannot establish cross-family reuse."),
        ("Cost", "Cost uses the frozen official DeepSeek price snapshot and is reported per attempt and per successful attempt."),
        ("Latency", "Wall time and Provider elapsed time are retained; infrastructure failures are not relabeled as task failures."),
        ("Discordant Cases", f"There are {len(result['discordant_families'])} family-level discordances requiring architecture-aware interpretation."),
        ("Provider Nondeterminism", "Temperature zero does not imply deterministic sampling. Findings use paired families and do not overclaim statistical significance."),
        ("Complexity Frontier", f"Verdict: {claims['COMPLEXITY_FRONTIER']}; map hash {boundary['map_hash']}."),
        ("Architecture Boundary", f"Router reopen evidence is {boundary['router_reopen_evidence']} and full orchestration status is {boundary['full_orchestration']}."),
        ("Corpus Expansion", f"Diversity verdict: {claims['CORPUS_DIVERSITY_STATUS']}. Complete source and failure snapshots stay local-only."),
        ("Failure Mining", f"Failure classes: {json.dumps(result['failure_classes'], sort_keys=True)}."),
        ("Modification Direction", "Each recommendation maps observed evidence to retain, simplify, keep-optional, or separately study; ITER-060 performs no post-formal architecture rewrite."),
        ("Negative Results", "Neutral, harmful, and not-needed findings are retained and reported with the same prominence as positive findings."),
        ("Threats to Validity", "The study uses one cheap model route, generated-original Python projects, small cells, and bounded episodes; results may not generalize beyond the tested frontier."),
        ("Security / Leakage", "Formal Corpus reads are disabled, hidden cases stay in private packets, project execution network is disabled, and absolute paths are redacted before Provider repair prompts."),
        ("Limitations", "No strong-model reference, public benchmark, Multi-Agent, Router, or cross-family capability-reuse treatment is included."),
        ("Future Project Problem Benchmark", "Future candidates target cross-family reuse, natural multi-round repair, longer restart chains, and public dependency-contract changes."),
        ("Conclusion", f"The evidence-bound next step follows claim ledger {canonical_hash(claims)}; no production default is changed in this release."),
    ]
    lines=["# CGNK Project Complexity Frontier: When Does Agent Architecture Start to Help?",""]
    for index,(title,body) in enumerate(sections,1): lines += [f"## {index}. {title}","",body,""]
    path.write_text("\n".join(lines),encoding="utf-8")


def _frontier_text(result: Mapping[str, Any], tier: str) -> str:
    row=next(item for item in result["complexity_frontier"] if item["complexity"]==tier)
    routes=", ".join(row["best_or_pareto"]) or "none"
    return f"Best/Pareto route set: {routes}. Full metrics are recorded in complexity_frontier.json."
