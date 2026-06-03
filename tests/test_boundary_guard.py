from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.cgnk_boundary_guard as guard


SAMPLES = ROOT / "examples" / "boundary" / "sample_intents.json"


def load_case(name: str) -> tuple[dict, dict | None]:
    payload = json.loads(SAMPLES.read_text(encoding="utf-8"))
    case_payload = payload["cases"][name]
    return case_payload["intent"], case_payload.get("run_state")


class BoundaryGuardTests(unittest.TestCase):
    def test_product_agent_writes_product_story_allowed(self) -> None:
        intent, run_state = load_case("allow_product_story")
        decision = guard.BoundaryGuard().decide(intent, run_state=run_state)
        self.assertEqual("allow", decision["status"])
        self.assertEqual("pass", decision["checks"]["role_contract"])
        self.assertEqual("pass", decision["checks"]["gate_dependency"])

    def test_product_agent_generated_path_blocked(self) -> None:
        intent, run_state = load_case("block_product_agent_generated_path")
        decision = guard.BoundaryGuard().decide(intent, run_state=run_state)
        self.assertEqual("block", decision["status"])
        self.assertEqual("fail", decision["checks"]["artifact_boundary"])

    def test_qa_agent_writes_product_story_blocked_or_escalated(self) -> None:
        intent, run_state = load_case("block_qa_writes_product_story")
        decision = guard.BoundaryGuard().decide(intent, run_state=run_state)
        self.assertIn(decision["status"], {"block", "escalate"})
        self.assertEqual("fail", decision["checks"]["artifact_boundary"])

    def test_delivery_bundle_missing_gates_blocked(self) -> None:
        intent, run_state = load_case("block_delivery_missing_gates")
        decision = guard.BoundaryGuard().decide(intent, run_state=run_state)
        self.assertEqual("block", decision["status"])
        self.assertEqual("fail", decision["checks"]["gate_dependency"])
        self.assertTrue(any("artifact.test_report@1" in message for message in decision["messages"]))

    def test_provider_request_blocked_when_role_disallows_provider(self) -> None:
        intent, run_state = load_case("block_provider_request")
        decision = guard.BoundaryGuard().decide(intent, run_state=run_state)
        self.assertEqual("block", decision["status"])
        self.assertEqual("fail", decision["checks"]["provider_permission"])

    def test_ledger_writes_jsonl(self) -> None:
        intent, run_state = load_case("allow_product_story")
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = pathlib.Path(temp_dir) / "boundary_guard_ledger.jsonl"
            decision = guard.BoundaryGuard(ledger_path=ledger_path).decide(intent, run_state=run_state)
            lines = ledger_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            entry = json.loads(lines[0])
            self.assertEqual(decision["status"], entry["decision"]["status"])
            self.assertIn("recorded_at", entry)

    def test_no_network_or_provider_direct_calls(self) -> None:
        source = (ROOT / "scripts" / "cgnk_boundary_guard.py").read_text(encoding="utf-8")
        forbidden = [
            "urllib.request.urlopen",
            "requests.post",
            "requests.get",
            "httpx.post",
            "httpx.get",
            "openai.",
        ]
        for snippet in forbidden:
            self.assertNotIn(snippet, source)


if __name__ == "__main__":
    unittest.main()
