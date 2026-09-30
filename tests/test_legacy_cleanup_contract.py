from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


class LegacyCleanupContractTests(unittest.TestCase):
    def test_codex_bridge_does_not_embed_naked_legacy_cli_pipeline(self) -> None:
        text = read("scripts/codex_conversation.py")

        self.assertNotIn("generation_subprocess_command", text)
        self.assertNotIn("run_generation_subprocess(args", text)
        self.assertNotIn('str(SCRIPTS_DIR / "generate_project.py")', text)
        self.assertIn("provider_project_pipeline.execute", text)
        self.assertIn("evaluate_public_delivery_gate", text)

    def test_superseded_generation_surfaces_are_absent(self) -> None:
        retired = (
            "scripts/generate_project.py",
            "scripts/legacy_provider_pipeline.py",
            "scripts/deliver_product_studio.py",
            "scripts/run_product_studio.py",
            "legacy/generate_project_legacy.py",
            "legacy/deliver_product_studio.py",
            "legacy/run_product_studio.py",
        )
        self.assertEqual([], [path for path in retired if (ROOT / path).exists()])

    def test_customer_policy_uses_soft_questions_not_blocking_questions(self) -> None:
        text = read("scripts/codex_conversation.py")

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
