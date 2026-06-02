from __future__ import annotations

import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cgnk_knowledge.event_log import append_event, events_from_jsonl, events_to_jsonl, list_events


def event(event_id: str, session_id: str = "s1", turn_index: int = 1) -> dict:
    return {
        "kind": "ConversationEvent",
        "event_id": event_id,
        "session_id": session_id,
        "turn_index": turn_index,
        "type": "user.message",
        "content_summary": "summary only",
        "artifact_refs": [],
        "diagnostics": [],
    }


class KnowledgeEventLogTests(unittest.TestCase):
    def test_append_event_adds_events_deterministically(self) -> None:
        log = append_event([], event("evt2", turn_index=2))["events"]
        log = append_event(log, event("evt1", turn_index=1))["events"]
        self.assertEqual(["evt1", "evt2"], [row["event_id"] for row in log])

    def test_list_events_filters_by_session_id(self) -> None:
        log = [event("evt1", "s1"), event("evt2", "s2")]
        self.assertEqual(["evt2"], [row["event_id"] for row in list_events(log, session_id="s2")])

    def test_jsonl_roundtrip_works(self) -> None:
        rows = [event("evt1"), event("evt2", turn_index=2)]
        self.assertEqual(rows, events_from_jsonl(events_to_jsonl(rows)))

    def test_invalid_event_returns_diagnostics(self) -> None:
        result = append_event([], {"event_id": "bad"})
        self.assertTrue(result["diagnostics"])
        self.assertEqual("CGNK_KNOWLEDGE_EVENT_INVALID", result["diagnostics"][0]["code"])

    def test_no_db_sqlite_required(self) -> None:
        result = append_event([], event("evt1"))
        self.assertIsInstance(result["events"], list)


if __name__ == "__main__":
    unittest.main()
