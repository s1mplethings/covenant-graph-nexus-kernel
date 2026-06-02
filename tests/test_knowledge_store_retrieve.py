from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.retrieve import retrieve_relevant_knowledge
from cgnk_knowledge.store import load_project_knowledge, new_project_knowledge_pack, save_project_knowledge, upsert_knowledge_items


def item(item_id: str, *, type_: str = "constraint", importance: str = "high", need: str = "needed_now", retention: str = "keep", review: str = "accepted", status: str = "active") -> dict:
    return {
        "kind": "KnowledgeItem",
        "id": item_id,
        "title": item_id,
        "type": type_,
        "scope": "project.ctcp" if "ctcp" in item_id else "project.cgnk",
        "content": item_id,
        "source_refs": ["evt"],
        "tags": ["module"] if "module" in item_id else [],
        "importance": importance,
        "need_state": need,
        "retention": retention,
        "review_state": review,
        "status": status,
        "supersedes": [],
        "stable_hash": item_id + "_hash",
        "diagnostics": [],
    }


class KnowledgeStoreRetrieveTests(unittest.TestCase):
    def test_project_pack_can_be_saved_loaded_and_sorted(self) -> None:
        pack = new_project_knowledge_pack("CGNK")
        pack = upsert_knowledge_items(pack, [item("ki_low", importance="low"), item("ki_ctcp_critical", importance="critical")])
        self.assertEqual(["ki_ctcp_critical", "ki_low"], [row["id"] for row in pack["all_items"]])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "knowledge.json"
            save_project_knowledge(path, pack)
            loaded = load_project_knowledge(path)
        self.assertEqual(pack["all_items"], loaded["all_items"])

    def test_retrieval_filters_and_ranks(self) -> None:
        pack = new_project_knowledge_pack("CGNK")
        rows = [
            item("ki_ctcp_critical", importance="critical", need="needed_now"),
            item("ki_rejected", review="rejected"),
            item("ki_superseded", status="superseded"),
            item("ki_discard", retention="discard"),
            item("ki_archive", retention="archive"),
            item("ki_reference", type_="decision", need="reference_only"),
        ]
        pack = upsert_knowledge_items(pack, rows)
        result = retrieve_relevant_knowledge(pack, {"kind": "KnowledgeRetrievalQuery", "selected_modules": [], "needed_types": [], "max_items": 20})
        self.assertEqual("ki_ctcp_critical", result["selected_items"][0]["id"])
        reasons = {row["item"]["id"]: row["reason"] for row in result["excluded_items"]}
        self.assertEqual("rejected", reasons["ki_rejected"])
        self.assertEqual("superseded", reasons["ki_superseded"])
        self.assertEqual("discard", reasons["ki_discard"])
        self.assertEqual("archived", reasons["ki_archive"])
        self.assertEqual("reference_not_requested", reasons["ki_reference"])
        with_reference = retrieve_relevant_knowledge(pack, {"kind": "KnowledgeRetrievalQuery", "selected_modules": [], "needed_types": [], "include_reference": True, "max_items": 20})
        self.assertIn("ki_reference", [row["id"] for row in with_reference["selected_items"]])
        with_archive = retrieve_relevant_knowledge(pack, {"kind": "KnowledgeRetrievalQuery", "selected_modules": [], "needed_types": [], "include_archived": True, "max_items": 20})
        self.assertIn("ki_archive", [row["id"] for row in with_archive["selected_items"]])


if __name__ == "__main__":
    unittest.main()
