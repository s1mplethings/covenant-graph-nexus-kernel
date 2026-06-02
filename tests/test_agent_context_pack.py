from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cgnk_knowledge.context_pack import build_agent_context_pack
from cgnk_knowledge.store import new_project_knowledge_pack, upsert_knowledge_items
from test_knowledge_store_retrieve import item


class AgentContextPackTests(unittest.TestCase):
    def test_context_pack_filters_and_groups_items(self) -> None:
        pack = new_project_knowledge_pack("CGNK")
        critical = item("ki_ctcp_readonly", importance="critical", need="needed_now")
        preference = item("ki_preference", type_="preference", importance="low", need="needed_later")
        decision = item("ki_decision", type_="decision", importance="high", need="needed_now")
        discarded = item("ki_discard", retention="discard")
        rejected = item("ki_rejected", review="rejected")
        superseded = item("ki_superseded", status="superseded")
        pack = upsert_knowledge_items(pack, [critical, preference, decision, discarded, rejected, superseded])
        context = build_agent_context_pack(pack, {"id": "goal1", "scope": "project.ctcp"}, max_items=20)
        self.assertEqual("ki_ctcp_readonly", context["critical_constraints"][0]["id"])
        self.assertEqual("ki_decision", context["active_decisions"][0]["id"])
        self.assertIn("ki_ctcp_readonly", [row["id"] for row in context["needed_now"]])
        usable_ids = {row["id"] for key in ("critical_constraints", "active_decisions", "needed_now", "needed_later") for row in context[key]}
        self.assertNotIn("ki_discard", usable_ids)
        self.assertNotIn("ki_rejected", usable_ids)
        self.assertNotIn("ki_superseded", usable_ids)
        reasons = {row["item"]["id"]: row["reason"] for row in context["excluded_knowledge"]}
        self.assertEqual("discard", reasons["ki_discard"])
        self.assertEqual("rejected", reasons["ki_rejected"])
        self.assertEqual("superseded", reasons["ki_superseded"])
        self.assertIn("ki_discard", [row["id"] for row in context["discard_candidates"]])
        json.dumps(context)


if __name__ == "__main__":
    unittest.main()
