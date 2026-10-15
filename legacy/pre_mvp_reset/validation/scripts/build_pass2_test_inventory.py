from __future__ import annotations

import argparse
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "artifacts" / "function_stress_pass" / "20261010-pass2"


def summary(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    matches = re.findall(r"^=+\s*(.+?)\s*=+$", text, flags=re.MULTILINE)
    if matches:
        return matches[-1]
    concise = re.findall(r"^(\d+ passed(?:, \d+ [a-z]+)* in .+)$", text, flags=re.MULTILINE)
    return concise[-1] if concise else "log missing summary"


def failed_nodeids(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    values = []
    for line in text.splitlines():
        match = re.match(r"^(?:FAILED|ERROR)\s+([^\s]+)", line)
        if match:
            values.append(match.group(1))
    return sorted(dict.fromkeys(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    targeted = RUNTIME / "pass2_targeted_regression.log"
    isolated = RUNTIME / "full_suite_last_failed_isolated.log"
    inventory = {
        "kind": "CGKNPass2TestInventory",
        "formal_evidence_status": "NOT_EVALUATED",
        "deduplication_rule": "Each pytest nodeid is counted once per run; overlapping runs are not summed.",
        "runs": [
            {
                "id": "complete_provider_free_profile",
                "command": "pytest -q --run-profile-marked -m 'not provider and not live_provider and not soak' --disable-warnings",
                "result": {"passed": 2439, "failed": 74, "errors": 16, "deselected": 8, "elapsed_seconds": 3693.24},
                "status": "NEEDS_REWORK",
                "note": "The initiating terminal stream was not redirected; the exact failed set was rerun and logged below.",
            },
            {
                "id": "isolated_failed_set",
                "command": "pytest --last-failed -q --run-profile-marked -m 'not provider and not live_provider and not soak' --tb=short",
                "result": {"passed": 24, "failed": 65, "deselected": 237, "elapsed_seconds": 771.78},
                "status": "NEEDS_REWORK",
                "log": str(isolated.relative_to(ROOT)).replace("\\", "/"),
                "failed_nodeids": failed_nodeids(isolated),
            },
            {
                "id": "pass2_targeted_regression",
                "command": "See REPRODUCE_PASS2.md",
                "summary": summary(targeted),
                "status": "PASS" if not failed_nodeids(targeted) and "passed" in summary(targeted) else "FAIL",
                "log": str(targeted.relative_to(ROOT)).replace("\\", "/"),
                "failed_nodeids": failed_nodeids(targeted),
            },
            {
                "id": "agent_kit_recovery",
                "node_scope": "tools/cgkn-agent-kit/tests/test_agent_kit.py",
                "result": {"passed": 26, "failed": 0, "skipped": 0},
                "status": "PASS",
            },
            {
                "id": "fixed_benchmark_regression",
                "node_scope": "tests/test_project_generation_benchmark_v1.py",
                "result": {"passed": 32, "failed": 0},
                "status": "PASS",
            },
            {
                "id": "first_batch_skips_explicit",
                "nodeids": [
                    "tests/test_generation_timeout_result.py::CodexConversationGenerationTimeoutResultTests::test_timeout_reply_uses_product_studio_reply_composer",
                    "tests/test_generation_timeout_result.py::CodexConversationGenerationTimeoutResultTests::test_timeout_writes_blocked_failure_result",
                ],
                "original_trigger": "module-level pytest.mark.codex excluded by default profile",
                "missing_capability": "none; explicit profile execution was required",
                "initial_explicit_result": "1 passed, 1 failed because write_timeout_failure_result was absent",
                "final_result": {"passed": 2, "failed": 0, "skipped": 0},
                "status": "PASS",
            },
        ],
        "classification": {
            "pass2_targeted_new_failures": 0,
            "complete_suite_persistent_failures": 65,
            "environment_or_local_state_examples": [
                "provider credential precedence sees host QWEN_API_KEY",
                "missing historical examples/knowledge fixtures",
                "tracked historical artifacts violate current hygiene guard",
            ],
            "preexisting_contract_or_fixture_examples": [
                "legacy dynamic pipeline attributes absent from codex_conversation",
                "old split-generation fixtures disagree with current ownership/manifest contracts",
                "README/Product Studio and marker contracts disagree with current repository",
            ],
            "unresolved_policy": "Persistent failures are not relabeled PASS; the repository-wide status is NEEDS_REWORK.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
