from __future__ import annotations

import pathlib
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_conversation as bridge

FORBIDDEN_FINAL_KEYS = {"delivered", "final_delivered", "delivery_manifest_sent", "PASS_FINAL"}


def send_candidate_review(
    client: Any,
    conversation_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    candidate_dir: pathlib.Path,
    candidate_bundle: pathlib.Path,
) -> dict[str, Any]:
    result = bridge.emit_candidate_review_delivery(client, conversation_id, session_dir, session, candidate_dir, candidate_bundle)
    generation = session.setdefault("generation", {})
    generation["candidate_review_sent"] = True
    generation["ask_user_review_sent"] = True
    for key in FORBIDDEN_FINAL_KEYS:
        generation.pop(key, None)
    return result


def assert_candidate_sender_scope(session: dict[str, Any]) -> dict[str, Any]:
    generation = session.get("generation", {}) if isinstance(session.get("generation"), dict) else {}
    leaked = sorted(key for key in FORBIDDEN_FINAL_KEYS if key in generation)
    return {"status": "fail" if leaked else "pass", "leaked_final_keys": leaked}
