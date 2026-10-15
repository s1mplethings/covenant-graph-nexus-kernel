from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_TESTS = [
    "tests/architecture", "tests/artifacts", "tests/compiler", "tests/component", "tests/orchestration",
    "tests/execution", "tests/executors", "tests/providers", "tests/state", "tests/runtime", "tests/recovery",
    "tests/capabilities", "tests/growth", "tests/agent", "tests/telemetry",
    "tests/test_artifact_driven_kernel.py", "tests/test_capability_tree_mvp.py", "tests/test_component_runtime_integration.py", "tests/test_provider_transport.py",
]
CORE_TESTS = [path for path in CORE_TESTS if (ROOT / path).exists()]
PYTEST = [sys.executable, "-m", "pytest", "-q"]
PROFILES = {
    "static": [
        [sys.executable, "-m", "compileall", "-q", "cgkn", "contracts", "scripts"],
        [sys.executable, "scripts/product_direction_gate.py"],
        [sys.executable, "scripts/kernel_architecture_gate.py"],
        [sys.executable, "scripts/test_architecture_gate.py"],
        [sys.executable, "scripts/kernel_completeness_gate.py"],
        [sys.executable, "scripts/kernel_source_identity.py"],
    ],
    "unit": [PYTEST + CORE_TESTS],
    "boundary": [PYTEST + ["-m", "boundary"] + CORE_TESTS],
    "fault": [PYTEST + ["-m", "fault_injection"] + CORE_TESTS],
    "security": [PYTEST + ["-m", "security"] + CORE_TESTS],
    "local-functional": [PYTEST + ["-m", "local_functional"] + CORE_TESTS],
    "full-core": [PYTEST + CORE_TESTS],
    "active-repository": [PYTEST],
    "live-provider": [PYTEST + ["-m", "live_provider"]],
}
SUMMARY = re.compile(r"(?P<count>\d+) (?P<kind>passed|failed|skipped|error|errors)(?:,| in)")


def _is_pytest(command: list[str]) -> bool:
    return len(command) >= 3 and command[1:3] == ["-m", "pytest"]


def _junit_results(path: pathlib.Path) -> tuple[list[str], list[str], list[str]]:
    passed: list[str] = []; skipped: list[str] = []; failed: list[str] = []
    if not path.is_file():
        return passed, skipped, failed
    for case in ET.parse(path).iter("testcase"):
        classname = str(case.get("classname", ""))
        name = str(case.get("name", ""))
        nodeid = classname.replace(".", "/") + ".py::" + name
        if case.find("skipped") is not None:
            skipped.append(nodeid)
        elif case.find("failure") is not None or case.find("error") is not None:
            failed.append(nodeid)
        else:
            passed.append(nodeid)
    return passed, skipped, failed


def _totals(output: str) -> dict[str, int]:
    result = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for match in SUMMARY.finditer(output):
        kind = match.group("kind")
        key = "errors" if kind in {"error", "errors"} else kind
        result[key] = int(match.group("count"))
    return result


def run_profile(name: str) -> dict[str, object]:
    if name == "live-provider" and not os.environ.get("CGKN_OPENAI_API_KEY"):
        return {"profile": name, "status": "BLOCKED_ENVIRONMENT", "duration_ms": 0, "commands": [], "test_node_ids": [], "totals": {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}, "reason": "CGKN_OPENAI_API_KEY is not configured"}
    started = time.perf_counter(); commands = []; passed_nodeids: set[str] = set(); skipped_nodeids: set[str] = set(); failed_nodeids: set[str] = set(); totals = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for index, command in enumerate(PROFILES[name]):
        executed = list(command)
        junit_path = ROOT / "artifacts" / f"kernel-profile-{name}-{index}.xml"
        if _is_pytest(command):
            junit_path.parent.mkdir(parents=True, exist_ok=True)
            junit_path.unlink(missing_ok=True)
            executed.append(f"--junitxml={junit_path}")
        completed = subprocess.run(executed, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        if _is_pytest(command):
            passed, skipped, failed = _junit_results(junit_path)
            passed_nodeids.update(passed); skipped_nodeids.update(skipped); failed_nodeids.update(failed)
        parsed = _totals(completed.stdout + "\n" + completed.stderr)
        for key in totals: totals[key] += parsed[key]
        commands.append({"argv": executed, "returncode": completed.returncode, "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-2000:]})
        if completed.returncode: break
    return {"profile": name, "status": "PASS" if commands and all(item["returncode"] == 0 for item in commands) else "FAIL", "duration_ms": int((time.perf_counter() - started) * 1000), "commands": commands, "test_node_ids": sorted(passed_nodeids), "skipped_test_node_ids": sorted(skipped_nodeids), "failed_test_node_ids": sorted(failed_nodeids), "totals": totals}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic CGKN kernel validation profiles.")
    parser.add_argument("profiles", nargs="*", choices=tuple(PROFILES))
    parser.add_argument("--profile", action="append", choices=tuple(PROFILES), dest="selected")
    parser.add_argument("--output")
    args = parser.parse_args()
    names = args.selected or args.profiles or [name for name in PROFILES if name != "live-provider"]
    results = [run_profile(name) for name in names]
    value = {"kind": "CGKNKernelProfileResults", "schema_version": "2.0", "results": results}
    rendered = json.dumps(value, indent=2) + "\n"
    if args.output: (ROOT / args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if all(item["status"] in {"PASS", "BLOCKED_ENVIRONMENT"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
