from __future__ import annotations

import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.normalize import normalize_keypoints_to_knowledge_items, stable_hash_for


def kp(text: str, category: str = "constraint", source: str = "evt1") -> dict:
    return {
        "kind": "KeyPoint",
        "id": "kp_" + source,
        "category": category,
        "text": text,
        "source_event_ids": [source],
        "scope": "project.ctcp" if "CTCP" in text else "project.cgnk",
        "importance": "critical" if "read-only" in text else "high",
        "need_state": "needed_now",
        "retention": "keep",
        "review_state": "accepted",
        "confidence": 0.95,
        "status": "active",
        "tags": ["CTCP"] if "CTCP" in text else [],
        "diagnostics": [],
    }


class KnowledgeNormalizeTests(unittest.TestCase):
    def test_duplicate_keypoints_dedupe_into_one_item(self) -> None:
        first = normalize_keypoints_to_knowledge_items([kp("Do not modify CTCP; CTCP is read-only.", source="evt1")])
        second = normalize_keypoints_to_knowledge_items([kp("Do not modify CTCP; CTCP is read-only.", source="evt2")], first["items"])
        self.assertFalse(second["items"])
        self.assertEqual(1, len(second["updated_existing_items"]))
        self.assertIn("evt2", second["updated_existing_items"][0]["source_refs"])

    def test_stable_hash_is_deterministic(self) -> None:
        self.assertEqual(stable_hash_for("A  B", "goal", "project"), stable_hash_for("a b", "goal", "project"))

    def test_ctcp_read_only_supersedes_ctcp_write_allowed(self) -> None:
        old = {
            "kind": "KnowledgeItem",
            "id": "ki_old",
            "title": "Old",
            "type": "decision",
            "scope": "project.ctcp",
            "content": "Old plan: directly work in CTCP and CTCP may be modified.",
            "source_refs": ["evt0"],
            "tags": ["CTCP"],
            "importance": "high",
            "need_state": "needed_now",
            "retention": "keep",
            "review_state": "accepted",
            "status": "active",
            "supersedes": [],
            "stable_hash": "old_hash",
            "diagnostics": [],
        }
        result = normalize_keypoints_to_knowledge_items([kp("Do not modify CTCP; CTCP is read-only.", source="evt1")], [old])
        self.assertEqual("superseded", result["superseded"][0]["status"])
        self.assertEqual("ki_old", result["items"][0]["supersedes"][0])

    def test_source_refs_are_preserved(self) -> None:
        result = normalize_keypoints_to_knowledge_items([kp("Do not modify CTCP; CTCP is read-only.", source="evt1")])
        self.assertEqual(["evt1"], result["items"][0]["source_refs"])


if __name__ == "__main__":
    unittest.main()
