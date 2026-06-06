from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


class LegacyCleanupContractTests(unittest.TestCase):
    def test_telegram_bridge_does_not_embed_legacy_provider_pipeline(self) -> None:
        text = read("scripts/telegram_live_bridge.py")

        self.assertNotIn("generation_subprocess_command", text)
        self.assertNotIn("run_generation_subprocess(args", text)
        self.assertNotIn('str(SCRIPTS_DIR / "generate_project.py")', text)
        self.assertNotIn("run_local_pipeline", text)

    def test_generate_project_is_legacy_only_if_present(self) -> None:
        path = ROOT / "scripts" / "generate_project.py"
        if not path.exists():
            self.skipTest("scripts/generate_project.py is absent")
        text = path.read_text(encoding="utf-8", errors="replace")

        self.assertIn("LEGACY CLI ONLY", text)
        self.assertIn("Not used by Telegram formal generation", text)

    def test_legacy_provider_pipeline_marked_legacy(self) -> None:
        path = ROOT / "scripts" / "legacy_provider_pipeline.py"
        if not path.exists():
            self.skipTest("legacy provider pipeline module is absent")
        text = path.read_text(encoding="utf-8", errors="replace")

        self.assertIn("LEGACY ONLY", text)
        self.assertIn("Not part of CGNK formal Telegram generation", text)

    def test_customer_policy_uses_soft_questions_not_blocking_questions(self) -> None:
        text = read("scripts/telegram_live_bridge.py")

        self.assertNotIn("Ask only questions that block generation", text)
        self.assertIn("non-blocking soft questions", text)

    def test_kernel_contract_checker_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/kernel_contract_check.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("PASS", result.stdout.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
