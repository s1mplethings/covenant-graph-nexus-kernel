from __future__ import annotations

import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.classify import classify_keypoint


class KnowledgeClassifyTests(unittest.TestCase):
    def test_cgkn_read_only_is_critical(self) -> None:
        row = classify_keypoint("Do not modify CGKN; CGKN is read-only.", source="user")
        self.assertEqual(("critical", "needed_now", "keep", "accepted"), (row["importance"], row["need_state"], row["retention"], row["review_state"]))

    def test_no_provider_call_is_critical(self) -> None:
        row = classify_keypoint("No provider calls are allowed.", source="user")
        self.assertEqual(("critical", "needed_now", "keep"), (row["importance"], row["need_state"], row["retention"]))

    def test_module_composed_agent_architecture_is_high_keep(self) -> None:
        row = classify_keypoint("Architecture: agents come from module composition.", source="user")
        self.assertEqual(("high", "keep"), (row["importance"], row["retention"]))

    def test_gui_url_is_ephemeral(self) -> None:
        row = classify_keypoint("GUI URL is http://127.0.0.1:3000.", source="auto")
        self.assertEqual(("low", "reference_only", "ephemeral"), (row["importance"], row["need_state"], row["retention"]))

    def test_old_test_report_is_compressed_reference(self) -> None:
        row = classify_keypoint("Agent interaction benchmark report passed.", source="auto")
        self.assertEqual(("medium", "reference_only", "compress"), (row["importance"], row["need_state"], row["retention"]))

    def test_rejected_cgkn_write_plan_is_rejected(self) -> None:
        row = classify_keypoint("不要改 CGKN，之前那个错了", source="user")
        self.assertEqual(("rejected", "not_needed", "archive"), (row["review_state"], row["need_state"], row["retention"]))

    def test_noise_is_discarded(self) -> None:
        row = classify_keypoint("thanks", source="auto")
        self.assertEqual(("noise", "not_needed", "discard"), (row["importance"], row["need_state"], row["retention"]))


if __name__ == "__main__":
    unittest.main()
