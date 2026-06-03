from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import product_studio_reply


class ProductStudioReplyTests(unittest.TestCase):
    def test_project_type_mismatch_reply_names_block_reason(self) -> None:
        text = product_studio_reply.compose_timeout_or_blocked_reply(
            {
                "status": "BLOCKED",
                "reason": "project_type_mismatch",
                "last_known_phase": "delivery_bundle",
                "missing_artifacts": ["effect_report.json"],
            }
        )
        self.assertIn("project_type_mismatch", text)
        self.assertIn("项目方向偏题", text)
        self.assertIn("虚拟项目组", text)

    def test_timeout_reply_is_not_only_generic_timeout(self) -> None:
        text = product_studio_reply.compose_timeout_or_blocked_reply(
            {
                "status": "BLOCKED",
                "reason": "generation subprocess exceeded total timeout",
                "last_known_phase": "usage_planning",
                "missing_artifacts": ["usage_plan.json"],
            }
        )
        self.assertIn("generation subprocess exceeded total timeout", text)
        self.assertIn("最后阶段", text)
        self.assertIn("缺失 artifact", text)


if __name__ == "__main__":
    unittest.main()
