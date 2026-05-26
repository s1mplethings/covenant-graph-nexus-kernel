from __future__ import annotations

import unittest

from cgnk_ctcp.feature_map import rejected_features, selected_features


class CtcpFeatureMapTest(unittest.TestCase):
    def test_selected_and_rejected_features_are_explicit(self) -> None:
        selected = selected_features()
        rejected = rejected_features()
        self.assertIn("project_generation_pipeline", selected)
        self.assertIn("provider_capability_boundary", selected)
        self.assertIn("old_progress_fallback", rejected)
        self.assertIn("old_telegram_bot_main_flow", rejected)


if __name__ == "__main__":
    unittest.main()
