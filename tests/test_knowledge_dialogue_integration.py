from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.dialogue_integration import update_knowledge_from_dialogue_turn
from cgnk_knowledge.retrieve import retrieve_relevant_knowledge


class KnowledgeDialogueIntegrationTests(unittest.TestCase):
    def test_update_creates_events_keypoints_items_and_report(self) -> None:
        result = update_knowledge_from_dialogue_turn({"session_id": "s1", "project": "CGKN"}, "Do not modify CGKN; CGKN is read-only.")
        self.assertTrue(result["events"])
        self.assertTrue(result["keypoints"])
        self.assertTrue(result["items"])
        self.assertEqual("KnowledgeUpdateReport", result["report"]["kind"])

    def test_repeated_turns_update_pack_incrementally_and_supersede(self) -> None:
        first = update_knowledge_from_dialogue_turn({"session_id": "s1", "project": "CGKN"}, "Old plan: directly work in CGKN and CGKN may be modified.")
        second = update_knowledge_from_dialogue_turn({"session_id": "s1", "project": "CGKN", "turn_index": 1}, "Now the target is work in CGKN only. Do not modify CGKN; CGKN is read-only.", pack=first["pack"])
        statuses = {row["id"]: row["status"] for row in second["pack"]["all_items"]}
        self.assertIn("superseded", statuses.values())
        self.assertTrue(second["report"]["superseded_items"])

    def test_no_raw_full_chat_required_for_retrieval(self) -> None:
        result = update_knowledge_from_dialogue_turn({"session_id": "s1", "project": "CGKN"}, "Do not modify CGKN; CGKN is read-only.")
        retrieval = retrieve_relevant_knowledge(result["pack"], {"kind": "KnowledgeRetrievalQuery", "selected_modules": [], "needed_types": ["constraint"], "max_items": 5})
        self.assertTrue(retrieval["selected_items"])
        self.assertNotIn("raw", retrieval["selected_items"][0])

    def test_no_provider_web_build_test_real_calls(self) -> None:
        result = update_knowledge_from_dialogue_turn({}, "Need local deterministic extraction only.")
        self.assertEqual("KnowledgeDialogueUpdateResult", result["kind"])


if __name__ == "__main__":
    unittest.main()
