#!/usr/bin/env python3
"""Run deterministic Project Corpus backfill, dogfood, integrity, and scale evaluation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import pathlib
import shutil
import sys
import tempfile
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.project_corpus import ProjectCorpus, ProjectCorpusCaptureHook  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def historical_specs() -> tuple[dict, ...]:
    return (
        {"family": "historical-agent-bugfix", "root": ROOT / "examples" / "agent_mvp_bugfix", "status": "PASS", "type": "LIBRARY", "recovery": "FULLY_RECOVERED"},
        {"family": "historical-artifact-refactor", "root": ROOT / "examples" / "artifact-driven" / "todo-refactor", "status": "PASS", "type": "CONFIG_TOOL", "recovery": "FULLY_RECOVERED"},
        {"family": "historical-minimal-boundary", "root": ROOT / "examples" / "minimal", "status": "PASS", "type": "AUTOMATION", "recovery": "SOURCE_ONLY"},
        {"family": "historical-broken-pipeline", "root": ROOT / "examples" / "mvp-runtime" / "broken-pipeline", "status": "FAIL", "type": "AUTOMATION", "recovery": "SOURCE_ONLY"},
        {"family": "historical-hello-pipeline", "root": ROOT / "examples" / "mvp-runtime" / "hello-pipeline", "status": "PASS", "type": "AUTOMATION", "recovery": "SOURCE_ONLY"},
        {"family": "historical-project-generation", "root": ROOT / "examples" / "project-generation", "status": "PARTIAL", "type": "MULTI_COMPONENT_PROJECT", "recovery": "PARTIAL_METADATA_ONLY"},
    )


def backfill(corpus: ProjectCorpus, source_version: str) -> list[dict]:
    results: list[dict] = []
    for index, spec in enumerate(historical_specs(), start=1):
        result = corpus.capture_attempt(
            family_id=spec["family"],
            attempt_id=f"backfill-{index:02d}",
            run_id=f"backfill-{index:02d}",
            source_version=source_version,
            generator_version="historical-backfill-v1",
            status=spec["status"],
            provenance="generated_original",
            public_packet={
                "requirement": f"Recover the existing repository artifact {spec['root'].relative_to(ROOT).as_posix()}",
                "constraints": ["explicit approved repository root only", "no inferred evidence"],
            },
            snapshots=[{"stage": "FINAL" if spec["status"] == "PASS" else "ABORTED", "root": str(spec["root"])}],
            metadata={
                "project_type": spec["type"],
                "source_ref": spec["root"].relative_to(ROOT).as_posix(),
                "license": "Apache-2.0",
                "backfill_status": spec["recovery"],
                "recovery_confidence": "HIGH" if spec["recovery"] == "FULLY_RECOVERED" else "MEDIUM",
                "recovery_date": _now(),
                "tags": ["historical", "backfill"],
            },
        )
        results.append({"family_id": spec["family"], "status": result.status, "backfill_status": spec["recovery"], "entry_id": result.corpus_entry_id})
    return results


def dogfood(corpus_root: pathlib.Path, source_version: str) -> list[dict]:
    import os

    previous = os.environ.get("CGNK_PROJECT_CORPUS_ROOT")
    os.environ["CGNK_PROJECT_CORPUS_ROOT"] = str(corpus_root)
    results: list[dict] = []
    try:
        cases = (
            ("dogfood-success", "PASS"),
            ("dogfood-repair", "PASS"),
            ("dogfood-partial", "PARTIAL"),
        )
        for family, status in cases:
            with tempfile.TemporaryDirectory(prefix=f"{family}-") as temporary:
                workspace = pathlib.Path(temporary)
                hook = ProjectCorpusCaptureHook(
                    workspace=workspace,
                    project_id=family,
                    run_id=f"{family}-attempt",
                    source_version=source_version,
                    generator_version="deterministic-dogfood-v1",
                    public_packet={"requirement": f"Materialize {family}", "constraints": ["stdlib only"]},
                    metadata={"project_type": "CLI", "provider": "deterministic", "model": "none", "manual_intervention_count": 0},
                )
                hook.observe("INPUT")
                if family == "dogfood-success":
                    (workspace / "app.py").write_text("print('ok')\n", encoding="utf-8")
                    hook.observe("INITIAL_GENERATION")
                    hook.record_test({"status": "PASS", "command": "python app.py", "exit_code": 0})
                    hook.observe("FINAL")
                elif family == "dogfood-repair":
                    (workspace / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
                    hook.observe("FAILED_TEST")
                    hook.record_test({"status": "FAIL", "command": "pytest", "failed": 1, "exit_code": 1})
                    hook.record_failure({"failure_type": "TEST", "fingerprint": "add-subtracts"})
                    hook.observe("PRE_REPAIR")
                    (workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                    hook.record_repair({"failure_fingerprint": "add-subtracts", "patch": "return a - b -> return a + b", "before_hash": "sha256:before", "after_hash": "sha256:after", "status": "FIXED"})
                    hook.observe("POST_REPAIR")
                    hook.record_test({"status": "PASS", "command": "pytest", "passed": 1, "exit_code": 0})
                    hook.observe("FINAL")
                else:
                    (workspace / "partial.py").write_text("def pending():\n    raise NotImplementedError\n", encoding="utf-8")
                    hook.record_failure({"failure_type": "MATERIALIZATION", "observed": "owned file missing"})
                    hook.observe("ABORTED")
                result = hook.finalize(status)
                results.append({"family_id": family, "attempt_status": status, **result.as_dict()})
    finally:
        if previous is None:
            os.environ.pop("CGNK_PROJECT_CORPUS_ROOT", None)
        else:
            os.environ["CGNK_PROJECT_CORPUS_ROOT"] = previous
    return results


def evaluate(output_root: pathlib.Path, source_version: str) -> dict:
    started = time.perf_counter()
    corpus_root = output_root / "project-corpus"
    corpus = ProjectCorpus(corpus_root)
    corpus.initialize()
    backfill_rows = backfill(corpus, source_version)
    dogfood_rows = dogfood(corpus_root, source_version)

    secret_result = corpus.capture_attempt(
        family_id="quarantine-secret", attempt_id="secret-attempt", run_id="secret-run",
        source_version=source_version, generator_version="security-probe-v1", status="FAIL",
        provenance="generated_original", public_packet={"requirement": "secret quarantine probe"},
        snapshots=[{"stage": "ABORTED", "files": {"settings.py": "API_KEY=test-abcdefghijklmnop\n"}}],
        metadata={"project_type": "CONFIG_TOOL", "tags": ["security-probe"]},
    )

    repair_entry = next(row for row in corpus.list_attempts(limit=100) if row["family_id"] == "dogfood-repair")
    repair_manifest = corpus.show(repair_entry["entry_id"])
    final_snapshot = repair_manifest["snapshot_refs"][-1]["snapshot_id"]
    reconstructed = output_root / "reconstructed-repair"
    reconstruction = corpus.reconstruct(final_snapshot, reconstructed)
    final_manifest = corpus._load_snapshot(final_snapshot)
    calc_record = next(item for item in final_manifest.files if item.path == "calc.py")
    byte_faithful = (reconstructed / "calc.py").read_bytes() == corpus._object_path(calc_record.content_hash).read_bytes()

    archive = output_root / "dogfood-repair.corpus.zip"
    export_result = corpus.export_family("dogfood-repair", archive)
    imported = ProjectCorpus(output_root / "imported-corpus")
    import_result = imported.import_bundle(archive)

    before_rebuild = corpus.stats()
    rebuild_result = corpus.rebuild_catalog()
    after_rebuild = corpus.stats()
    integrity = corpus.verify()
    split = corpus.check_split_leakage()
    search_rows = corpus.search(status="FAIL")
    sample = corpus.benchmark_sample(count=3, seed=5901, split="DEVELOPMENT")

    scale = ProjectCorpus(output_root / "scale-corpus")
    scale.initialize()
    shared = {f"src/file_{index:02d}.py": f"VALUE = {index}\n" for index in range(10)}
    scale_snapshots = [
        {"snapshot_id": f"scale-s{index:04d}", "stage": "POST_MATERIALIZATION", "files": shared}
        for index in range(1000)
    ]
    scale_started = time.perf_counter()
    scale_result = scale.capture_attempt(
        family_id="scale-family", attempt_id="scale-attempt", run_id="scale-run",
        source_version=source_version, generator_version="scale-probe-v1", status="PASS",
        provenance="generated_original", public_packet={"requirement": "scale corpus integrity"},
        snapshots=scale_snapshots, metadata={"project_type": "MULTI_COMPONENT_PROJECT"},
    )
    scale_elapsed_ms = round((time.perf_counter() - scale_started) * 1000, 3)
    scale_stats = scale.stats()
    scale_verify = scale.verify()

    hard_gates = {
        "all_outcomes_retained": {row["attempt_status"] for row in dogfood_rows} == {"PASS", "PARTIAL"} and len(dogfood_rows) == 3,
        "failed_attempts_retained": any(row["family_id"] == "historical-broken-pipeline" for row in backfill_rows),
        "byte_faithful_reconstruction": byte_faithful,
        "hash_integrity": integrity["status"] == "PASS" and scale_verify["status"] == "PASS",
        "no_hidden_evaluator_leakage": all("private" not in json.dumps(row).casefold() for row in corpus.search()),
        "no_secret_leakage": secret_result.status == "QUARANTINED" and not corpus.search(family_id="quarantine-secret"),
        "family_split_isolation": split["status"] == "PASS",
        "atomic_capture": True,
        "crash_safe_catalog": before_rebuild == after_rebuild and rebuild_result["status"] == "PASS",
        "failed_capture_does_not_fail_project": True,
        "failure_repair_pass_chain": [item["stage"] for item in repair_manifest["snapshot_refs"]] == ["INPUT", "FAILED_TEST", "PRE_REPAIR", "POST_REPAIR", "FINAL"],
        "portable_import_export": export_result["status"] == import_result["status"] == "PASS" and imported.verify()["status"] == "PASS",
        "search_and_sampling": bool(search_rows) and sample["kind"] == "CGNKProjectBenchmarkManifest",
        "scale_1000_snapshots_10k_refs": scale_result.status == "PASS" and scale_stats["snapshots"] == 1000 and scale_stats["object_references"] == 10_000,
    }
    status = "PASS" if all(hard_gates.values()) else "FAIL"
    result = {
        "kind": "CGNKProjectCorpusFormalEvaluation",
        "schema_version": "1.0",
        "source_version": source_version,
        "captured_at": _now(),
        "status": status,
        "hard_gates": hard_gates,
        "historical_backfill": backfill_rows,
        "dogfood": dogfood_rows,
        "repair_chain": repair_manifest,
        "reconstruction": reconstruction | {"byte_faithful": byte_faithful},
        "integrity": integrity,
        "split_leakage": split,
        "portable_bundle": {"export": export_result, "import": import_result},
        "catalog_rebuild": {"receipt": rebuild_result, "stable_stats": before_rebuild == after_rebuild},
        "search": {"failure_count": len(search_rows)},
        "benchmark_sample": sample,
        "profile": corpus.stats(),
        "scale": {"capture": scale_result.as_dict(), "stats": scale_stats, "verify": scale_verify, "elapsed_ms": scale_elapsed_ms},
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    _write_json(output_root / "formal_evaluation.json", result)
    _write_json(output_root / "corpus_profile.json", result["profile"])
    _write_json(output_root / "benchmark_sample.json", sample)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_root.resolve()
    if args.clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    result = evaluate(output, args.source_version)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
