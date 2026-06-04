from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import product_studio_reply
import telegram_live_bridge as bridge


class TelegramGenerationTimeoutResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_slug = "unit-timeout-result"
        self.run_dir = ROOT / "examples" / "runtime_runs" / self.project_slug
        self.project_dir = ROOT / "generated" / self.project_slug
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_timeout_writes_blocked_failure_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            phase_log = self.run_dir / "artifacts" / "generation_phase_log.jsonl"
            phase_log.parent.mkdir(parents=True, exist_ok=True)
            phase_log.write_text(
                '{"phase":"usage_planning","status":"started"}\n'
                '{"phase":"usage_planning_local","status":"started"}\n',
                encoding="utf-8",
            )
            diagnostics = self.run_dir / "agent_usage" / "usage_planning_diagnostics.json"
            diagnostics.parent.mkdir(parents=True, exist_ok=True)
            diagnostics.write_text('{"status":"started","planner":"local_deterministic"}\n', encoding="utf-8")
            result_path = pathlib.Path(temp_dir) / "generation_result.json"
            args = argparse.Namespace(project_slug=self.project_slug)
            result = bridge.write_timeout_failure_result(args, 900, result_path)
            self.assertTrue(result_path.exists())
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual("usage_planning_local", result["last_known_phase"])
            self.assertEqual("usage_planning_local", result["recent_phase_events"][-1]["phase"])
            self.assertEqual("started", result["timeout_diagnostics"]["status"])
            self.assertIn("missing_artifacts", result)
            self.assertTrue(result["can_retry"])

    def test_timeout_reply_uses_product_studio_reply_composer(self) -> None:
        reply = product_studio_reply.ProductStudioReplyComposer().timeout_or_blocked_reply(
            {
                "status": "BLOCKED",
                "reason": "generation subprocess exceeded total timeout",
                "last_known_phase": "usage_planning",
                "missing_artifacts": ["generation_result.json", "visual_evidence_plan.json"],
            }
        )
        self.assertIn("虚拟项目组", reply)
        self.assertIn("后台生成超过", reply)
        self.assertIn("缺失 artifact", reply)


if __name__ == "__main__":
    unittest.main()
