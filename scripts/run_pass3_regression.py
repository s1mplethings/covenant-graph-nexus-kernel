#!/usr/bin/env python3
"""Run a frozen Provider-free regression with durable raw and per-node evidence."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import source_identity


SECRET_ENV_NAMES = {
    "OPENAI_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "CGKN_OPENAI_API_KEY",
    "CGNK_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "QWEN_BASE_URL",
    "OPENAI_BASE_URL",
    "CGKN_OPENAI_BASE_URL",
    "CGNK_OPENAI_BASE_URL",
}

PASS3_TARGETED = [
    "tests/test_function_stress_runner.py",
    "tools/cgkn-agent-kit/tests/test_agent_kit.py",
    "tests/test_pass2_operational_closure.py",
    "tests/test_kernel_contract.py::KernelContractTests::test_generation_wait_cancel_and_context_preflight_preserve_authority",
]

OLD_NODEID_MIGRATIONS = {
    "tests/test_compose_local_pipeline.py::ComposeLocalPipelineTests::test_full_agent_route_compiles_without_unbound_control_inputs":
        "tests/test_compose_local_pipeline.py::ComposeLocalPipelineTests::test_current_component_route_compiles_without_legacy_fixed_modules",
    "tests/test_formal_provider_fallback.py::test_provider_text_uses_compact_reasoning_none_qwen_leaf_payload":
        "tests/test_formal_provider_fallback.py::test_provider_text_uses_reasoning_none_qwen_leaf_payload",
    "tests/test_product_design_depth_rule_guard.py::test_product_design_depth_rule_guard_passes":
        "tests/test_product_design_depth_rule_guard.py::test_product_design_depth_rule_guard_reports_dirty_boundary_separately",
    "tests/test_formal_provider_fallback.py::test_high_complexity_javascript_leaf_auto_expands_into_real_modules":
        "tests/test_formal_provider_fallback.py::test_high_complexity_javascript_leaf_preserves_product_defined_module_path",
    "tests/test_run_local_pipeline_usage.py::RunLocalPipelineUsageTests::test_transport_error_upgrades_model_without_consuming_semantic_attempt":
        "tests/test_run_local_pipeline_usage.py::RunLocalPipelineUsageTests::test_transport_retry_preserves_semantic_repair_capability_model",
    "tests/test_provider_post_build_finalize.py::ProviderPostBuildFinalizeTests::test_post_build_finalize_repair_uses_final_candidate_hash":
        "tests/test_provider_post_build_finalize.py::ProviderPostBuildFinalizeTests::test_post_build_finalize_does_not_mutate_failed_provider_candidate",
    "tests/test_run_local_pipeline_usage.py::RunLocalPipelineUsageTests::test_split_file_checkpoint_and_resume":
        "tests/test_run_local_pipeline_usage.py::RunLocalPipelineUsageTests::test_split_provider_job_checkpoint_and_resume",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _old_failure_nodeids(inventory_path: pathlib.Path) -> list[str]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for run in inventory.get("runs", []):
        if run.get("id") == "isolated_failed_set":
            return [OLD_NODEID_MIGRATIONS.get(str(item), str(item)) for item in run.get("failed_nodeids", [])]
    raise ValueError("isolated_failed_set nodeids not found")


def _junit_counts(path: pathlib.Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    keys = ("tests", "failures", "errors", "skipped")
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in keys
    }


def run(
    output_dir: pathlib.Path,
    *,
    scope: str,
    inventory_path: pathlib.Path,
    order: str,
    seed: int | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    before = source_identity.capture(ROOT)
    (output_dir / "source_identity.before.json").write_text(
        json.dumps(before, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selected = (
        _old_failure_nodeids(inventory_path)
        if scope == "old-failures"
        else list(PASS3_TARGETED)
        if scope == "pass3-targeted"
        else ["tests", "scripts", "tools/cgkn-agent-kit/tests"]
    )
    if order == "reverse":
        selected.reverse()
    if order == "shuffled" and seed is None:
        raise ValueError("--seed is required with --order shuffled")
    junit = output_dir / "junit.xml"
    events = output_dir / "pytest_events.jsonl"
    raw_log = output_dir / "pytest_raw.log"
    cache = output_dir / "pytest-cache"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "scripts.pytest_event_recorder",
        "--run-profile-marked",
        "-m",
        "not provider and not live_provider and not soak",
        "--tb=short",
        "--disable-warnings",
        f"--junitxml={junit}",
        "-o",
        f"cache_dir={cache}",
        *selected,
    ]
    env = dict(os.environ)
    for name in SECRET_ENV_NAMES:
        env.pop(name, None)
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "CGKN_PROVIDER_NETWORK_FORBIDDEN": "1",
            # Provider-free regression must not silently consume an installed
            # local model through host-level hybrid routing. Tests that cover
            # local routing opt in with their own scoped monkeypatches.
            "CGNK_MODEL_ROUTING_PROFILE": "api_only",
            "CGNK_USE_LOCAL_MODEL": "0",
            "CGNK_AUTO_START_OLLAMA": "0",
            "CGKN_PYTEST_EVENT_LOG": str(events.resolve()),
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "npm_config_offline": "true",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "PYTHONPATH": os.pathsep.join(
                [
                    str(ROOT),
                    str(ROOT / "tools" / "cgkn-agent-kit" / "src"),
                    env.get("PYTHONPATH", ""),
                ]
            ).rstrip(os.pathsep),
        }
    )
    env.pop("CGNK_LOCAL_MODEL_CMD", None)
    env.pop("CGNK_LOCAL_MODEL_TASKS", None)
    if order == "shuffled":
        env["CGKN_TEST_ORDER_SEED"] = str(seed)
    else:
        env.pop("CGKN_TEST_ORDER_SEED", None)
    started = time.perf_counter()
    timed_out = False
    completed_returncode: int | None = None
    with raw_log.open("w", encoding="utf-8", newline="\n") as log:
        try:
            completed = subprocess.run(
                argv,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
            )
            completed_returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    elapsed = time.perf_counter() - started
    after = source_identity.capture(ROOT)
    (output_dir / "source_identity.after.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    counts = _junit_counts(junit) if junit.is_file() else {}
    report = {
        "kind": "CGKNProviderFreeRegression",
        "formal_evidence_status": "NOT_EVALUATED",
        "created_at": _now(),
        "scope": scope,
        "order": order,
        "order_seed": seed if order == "shuffled" else None,
        "watchdog_timeout_seconds": timeout_seconds,
        "watchdog_timed_out": timed_out,
        "argv": argv,
        "interpreter": sys.executable,
        "python_version": sys.version,
        "pythonpath": env["PYTHONPATH"],
        "credentials_inherited": False,
        "network_provider_forbidden": True,
        "network_isolation": {
            "package_indexes": "disabled",
            "external_proxy": "closed_loopback_port",
            "localhost_allowed": True,
        },
        "source_identity_before": before["source_identity_hash"],
        "source_identity_after": after["source_identity_hash"],
        "source_snapshot_stable": before["source_identity_hash"] == after["source_identity_hash"],
        "returncode": completed_returncode,
        "elapsed_seconds": elapsed,
        "counts": counts,
        "artifacts": {
            "raw_log": str(raw_log.resolve()),
            "junit": str(junit.resolve()),
            "phase_events": str(events.resolve()),
        },
        "status": "PASS" if completed_returncode == 0 and before["source_identity_hash"] == after["source_identity_hash"] else "FAIL",
    }
    (output_dir / "regression_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--scope", choices=("old-failures", "pass3-targeted", "full"), default="old-failures")
    parser.add_argument("--inventory", type=pathlib.Path, default=ROOT / "TEST_INVENTORY.json")
    parser.add_argument("--order", choices=("normal", "reverse", "shuffled"), default="normal")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args(argv)
    report = run(
        args.output_dir.resolve(),
        scope=args.scope,
        inventory_path=args.inventory.resolve(),
        order=args.order,
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
