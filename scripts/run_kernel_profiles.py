from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILES = {
    "static": [
        [sys.executable, "-m", "compileall", "-q", "cgkn", "scripts/kernel_gate_common.py", "scripts/kernel_architecture_gate.py", "scripts/test_architecture_gate.py", "scripts/kernel_completeness_gate.py"],
        [sys.executable, "scripts/product_direction_gate.py"],
        [sys.executable, "scripts/kernel_architecture_gate.py"],
        [sys.executable, "scripts/test_architecture_gate.py"],
        [sys.executable, "scripts/kernel_completeness_gate.py"],
    ],
    "unit": [[sys.executable, "-m", "pytest", "-q", "tests/component", "tests/artifacts", "tests/execution", "tests/state", "tests/capabilities", "tests/growth", "tests/telemetry", "tests/test_capability_tree_mvp.py"]],
    "boundary": [[sys.executable, "-m", "pytest", "-q", "tests/architecture", "tests/executors", "tests/runtime/test_invalidation_and_edits.py", "tests/test_provider_transport.py"]],
    "local-functional": [[sys.executable, "-m", "pytest", "-q", "tests/runtime/test_dag_runner.py", "tests/agent/test_agent_mvp.py", "tests/test_component_runtime_integration.py", "tests/test_artifact_driven_kernel.py"]],
}


def run_profile(name: str) -> dict[str, object]:
    started = time.perf_counter()
    commands = []
    for command in PROFILES[name]:
        completed = subprocess.run(command, cwd=ROOT, check=False)
        commands.append({"argv": command, "returncode": completed.returncode})
        if completed.returncode:
            break
    return {"profile": name, "status": "PASS" if all(item["returncode"] == 0 for item in commands) else "FAIL", "duration_ms": int((time.perf_counter() - started) * 1000), "commands": commands}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run named deterministic CGKN kernel validation profiles.")
    parser.add_argument("profiles", nargs="*", choices=tuple(PROFILES))
    args = parser.parse_args()
    results = [run_profile(name) for name in (args.profiles or list(PROFILES))]
    print(json.dumps({"kind": "CGKNKernelProfileResults", "schema_version": "1.0", "results": results}, indent=2))
    return 0 if all(item["status"] == "PASS" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
