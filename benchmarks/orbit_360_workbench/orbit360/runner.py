from __future__ import annotations

import pathlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .contracts import (
    CHECKPOINT_KIND,
    RUN_REPORT_KIND,
    SCHEMA_VERSION,
    OrbitError,
    add_hash,
    canonical_hash,
    read_json,
    verify_hash,
    write_json,
)
from .workspace import load_workspace


def execute_unit(descriptor: dict[str, Any], dependency_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dependency_hashes = {name: dependency_results[name]["result_sha256"] for name in descriptor["dependencies"]}
    dependency_value = sum(int(dependency_results[name]["value"]) for name in descriptor["dependencies"])
    core = {
        "unit_id": descriptor["id"],
        "descriptor_sha256": descriptor["unit_sha256"],
        "dependency_result_sha256": dependency_hashes,
        "value": (int(descriptor["weight"]) + int(descriptor["index"]) + dependency_value) % 1_000_003,
    }
    return add_hash(core, "result_sha256")


def valid_result(result: Any, descriptor: dict[str, Any], results: dict[str, dict[str, Any]]) -> bool:
    if not isinstance(result, dict) or not verify_hash(result, "result_sha256"):
        return False
    if result.get("unit_id") != descriptor.get("id") or result.get("descriptor_sha256") != descriptor.get("unit_sha256"):
        return False
    expected_dependencies = {}
    for dependency in descriptor["dependencies"]:
        dependency_result = results.get(str(dependency))
        if not isinstance(dependency_result, dict) or not verify_hash(dependency_result, "result_sha256"):
            return False
        expected_dependencies[str(dependency)] = dependency_result["result_sha256"]
    if result.get("dependency_result_sha256") != expected_dependencies:
        return False
    dependency_results = {str(name): results[str(name)] for name in descriptor["dependencies"]}
    return result == execute_unit(descriptor, dependency_results)


def load_checkpoint(root: pathlib.Path, plan: dict[str, Any]) -> dict[str, Any]:
    path = root / "checkpoint.json"
    if not path.is_file():
        return {
            "kind": CHECKPOINT_KIND,
            "schema_version": SCHEMA_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "results": {},
        }
    checkpoint = read_json(path)
    if checkpoint.get("kind") != CHECKPOINT_KIND or checkpoint.get("schema_version") != SCHEMA_VERSION:
        raise OrbitError("Unsupported checkpoint contract")
    if checkpoint.get("plan_sha256") != plan.get("plan_sha256") or not isinstance(checkpoint.get("results"), dict):
        raise OrbitError("Checkpoint plan binding is invalid")
    return checkpoint


def run_workspace(root: pathlib.Path, workers: int = 8) -> dict[str, Any]:
    if not 1 <= workers <= 32:
        raise OrbitError("workers must be between 1 and 32")
    root, plan, descriptors = load_workspace(root)
    checkpoint = load_checkpoint(root, plan)
    results: dict[str, dict[str, Any]] = dict(checkpoint["results"])
    executed: list[str] = []
    reused: list[str] = []
    for layer in range(int(plan["layer_count"])):
        layer_ids = [str(item["id"]) for item in plan["units"] if int(item["layer"]) == layer]
        pending = []
        for unit_name in layer_ids:
            if valid_result(results.get(unit_name), descriptors[unit_name], results):
                reused.append(unit_name)
            else:
                results.pop(unit_name, None)
                pending.append(unit_name)
        dependency_snapshot = dict(results)
        with ThreadPoolExecutor(max_workers=min(workers, len(pending) or 1)) as pool:
            futures = {
                unit_name: pool.submit(execute_unit, descriptors[unit_name], dependency_snapshot)
                for unit_name in pending
            }
            for unit_name in layer_ids:
                if unit_name in futures:
                    results[unit_name] = futures[unit_name].result()
                    executed.append(unit_name)
        checkpoint["results"] = results
        write_json(root / "checkpoint.json", checkpoint)
    ordered_results = [results[str(item["id"])] for item in plan["units"]]
    report = add_hash(
        {
            "kind": RUN_REPORT_KIND,
            "schema_version": SCHEMA_VERSION,
            "workflow_state": "completed",
            "formal_evidence_status": "NOT_EVALUATED",
            "note": "Benchmark support evidence only; this report cannot authorize CGKN packaging or delivery.",
            "plan_sha256": plan["plan_sha256"],
            "unit_count": plan["unit_count"],
            "layer_count": plan["layer_count"],
            "workers": workers,
            "executed_count": len(executed),
            "reused_count": len(reused),
            "executed_units": executed,
            "reused_units": reused,
            "results_sha256": canonical_hash(ordered_results),
        },
        "report_sha256",
    )
    write_json(root / "run_report.json", report)
    return report


def workspace_status(root: pathlib.Path) -> dict[str, Any]:
    root, plan, descriptors = load_workspace(root)
    checkpoint = load_checkpoint(root, plan)
    results = checkpoint["results"]
    valid = 0
    for item in plan["units"]:
        name = str(item["id"])
        if valid_result(results.get(name), descriptors[name], results):
            valid += 1
    report_path = root / "run_report.json"
    last_report = read_json(report_path) if report_path.is_file() else {}
    return {
        "ok": True,
        "workspace": str(root),
        "unit_count": plan["unit_count"],
        "valid_checkpoint_results": valid,
        "last_executed_count": last_report.get("executed_count"),
        "last_reused_count": last_report.get("reused_count"),
        "formal_evidence_status": "NOT_EVALUATED",
    }
