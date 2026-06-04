from __future__ import annotations

import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.keypoint_extract import extract_keypoints_from_turn


class KnowledgeKeypointExtractTests(unittest.TestCase):
    def test_required_keypoints_are_extracted(self) -> None:
        message = "\n".join(
            [
                "Goal: build a modular conversation knowledge system.",
                "Do not modify CGKN; CGKN is read-only.",
                "Architecture decision: agents are generated from module composition.",
                "Artifact created: examples/knowledge/agent_context_pack.example.json",
                "Agent interaction benchmark tests passed in commit abc123.",
                "Temporary GUI localhost URL: http://127.0.0.1:3000.",
            ]
        )
        result = extract_keypoints_from_turn({"project": "CGNK", "current_event_ids": ["evt1"]}, message)
        categories = {row["category"] for row in result["keypoints"]}
        self.assertIn("goal", categories)
        self.assertIn("constraint", categories)
        self.assertIn("decision", categories)
        self.assertIn("artifact_ref", categories)
        self.assertIn("test_result", categories)
        self.assertTrue(any("localhost" in row["text"] for row in result["keypoints"]))
        self.assertTrue(all(row["source_event_ids"] == ["evt1"] for row in result["keypoints"]))

    def test_no_llm_provider_call_occurs(self) -> None:
        result = extract_keypoints_from_turn({}, "Need deterministic local extraction only.")
        self.assertEqual("KeyPointExtractionResult", result["kind"])


if __name__ == "__main__":
    unittest.main()
