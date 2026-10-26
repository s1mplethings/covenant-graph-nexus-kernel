#!/usr/bin/env python3
"""Reproducible ITER-056 retrieval and capability-search profiler."""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import inspect
import json
import pathlib
import pstats
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from benchmarks.knowledge_persistence_scaling import runner as knowledge_benchmark  # noqa: E402
from cgkn.application.capability_routing.benchmarks import run_search_discovery  # noqa: E402
from cgkn.application.conversation import ConversationRequest, ConversationService  # noqa: E402
from cgnk_knowledge import retrieve_relevant_knowledge  # noqa: E402


ITERATION = "ITER-CGNK-CORE-OPTIMIZATION-ACADEMIC-RELEASE-056"
PROFILE_VERSION = "1.0"


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def percentile(values: Iterable[float], quantile: float) -> float | None:
    return knowledge_benchmark.percentile(values, quantile)


def _identity() -> dict[str, str]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

    runtime_paths = (
        ROOT / "src" / "cgnk_knowledge" / "retrieve.py",
        ROOT / "src" / "cgnk_knowledge" / "store.py",
        ROOT / "cgkn" / "application" / "conversation" / "service.py",
        ROOT / "cgkn" / "application" / "capability_routing" / "search.py",
    )
    runtime_hash = stable_hash({
        path.relative_to(ROOT).as_posix(): path.read_text("utf-8") for path in runtime_paths
    })
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "runtime_source_hash": runtime_hash,
    }


def _top_profile_rows(profile: cProfile.Profile, limit: int = 15) -> list[dict[str, Any]]:
    stats = pstats.Stats(profile)
    rows = []
    for (filename, line, function), values in stats.stats.items():
        primitive_calls, total_calls, total_time, cumulative_time, _ = values
        normalized = filename.replace("\\", "/")
        if "/cgnk_knowledge/" not in normalized and "/conversation/" not in normalized:
            continue
        rows.append({
            "function": f"{pathlib.Path(filename).name}:{line}:{function}",
            "primitive_calls": primitive_calls,
            "total_calls": total_calls,
            "self_ms": round(total_time * 1000, 3),
            "cumulative_ms": round(cumulative_time * 1000, 3),
        })
    return sorted(rows, key=lambda row: (-row["cumulative_ms"], row["function"]))[:limit]


def profile_knowledge_scale(size: int, repeats: int) -> dict[str, Any]:
    if size < 10:
        raise ValueError("knowledge scale must be at least 10")
    process = psutil.Process()
    gc.collect()
    rss_before = process.memory_info().rss
    branches = min(size, knowledge_benchmark.branch_count_for(size))
    started_cpu = time.process_time()
    started = time.perf_counter()
    base_size = max(100, size)
    pack = knowledge_benchmark.generate_corpus(base_size, min(base_size, branches), "uniform")
    if size < base_size:
        pack["all_items"] = pack["all_items"][:size]
        pack["knowledge_revision"] = size
        pack = knowledge_benchmark.rebuild_pack_indexes(pack)
    build_ms = (time.perf_counter() - started) * 1000
    build_cpu_ms = (time.process_time() - started_cpu) * 1000
    rss_after_build = process.memory_info().rss
    cases = knowledge_benchmark.query_cases(size, branches, "uniform")
    if size < 100:
        applicable = {
            "bottom_up_raw_detail", "two_node_composition", "superseded_fact",
            "contradiction", "stale_summary_raw_fallback", "no_evidence",
        }
        cases = [case for case in cases if case["name"] in applicable]

    profile = cProfile.Profile()
    profile.enable()
    evaluation = knowledge_benchmark.evaluate_queries(pack, cases, repeats=repeats)
    profile.disable()

    conversation = ConversationService(None)
    context_latencies: list[float] = []
    context_chars: list[int] = []
    raw_expansions: list[int] = []
    for _ in range(repeats):
        for query in ("ident-000010", "exact detail-block-000000", "conflict-block-000000"):
            started = time.perf_counter()
            _, receipt = conversation._retrieve(ConversationRequest(query), pack)
            context_latencies.append((time.perf_counter() - started) * 1000)
            context_chars.append(int(receipt["context_chars"]))
            raw_expansions.append(int(receipt["raw_expansion_count"]))
    rss_after = process.memory_info().rss
    return {
        "size": size,
        "branches": branches,
        "applicable_query_case_count": len(cases),
        "corpus_build_ms": round(build_ms, 3),
        "corpus_build_cpu_ms": round(build_cpu_ms, 3),
        "rss_before_bytes": rss_before,
        "rss_after_build_bytes": rss_after_build,
        "rss_after_profile_bytes": rss_after,
        "rss_growth_bytes": max(0, rss_after - rss_before),
        "retrieval": evaluation,
        "context_assembly": {
            "latency_ms": {
                "p50": percentile(context_latencies, 0.5),
                "p95": percentile(context_latencies, 0.95),
            },
            "context_chars_p50": percentile(context_chars, 0.5),
            "raw_expansion_max": max(raw_expansions),
            "provider_calls": 0,
            "model_tokens": 0,
        },
        "hotspots": _top_profile_rows(profile),
    }


def run_profile(knowledge_sizes: Iterable[int], capability_scales: Iterable[int], repeats: int) -> dict[str, Any]:
    identity = _identity()
    knowledge_rows = []
    for size in knowledge_sizes:
        knowledge_rows.append(profile_knowledge_scale(int(size), repeats))
        gc.collect()
    capability = run_search_discovery(tuple(int(size) for size in capability_scales))
    body = {
        "kind": "CGKNRelease056Profile",
        "schema_version": "1.0",
        "iteration": ITERATION,
        "profile_version": PROFILE_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_identity": identity,
        "environment": {
            "python": sys.version,
            "platform": sys.platform,
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "memory_total_bytes": psutil.virtual_memory().total,
        },
        "knowledge": knowledge_rows,
        "capability_search": capability,
        "provider_calls": 0,
        "model_tokens": 0,
    }
    return body | {"receipt_hash": stable_hash(body)}


def _csv_ints(value: str) -> tuple[int, ...]:
    rows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not rows:
        raise argparse.ArgumentTypeError("at least one integer is required")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-sizes", type=_csv_ints, default=(10, 100, 1000, 10_000, 100_000, 250_000))
    parser.add_argument("--capability-scales", type=_csv_ints, default=(100, 500, 1000, 5000))
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    result = run_profile(args.knowledge_sizes, args.capability_scales, args.repeats)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or not args.output:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
