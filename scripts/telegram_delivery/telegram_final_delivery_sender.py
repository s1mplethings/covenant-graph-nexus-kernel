from __future__ import annotations

import pathlib
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import telegram_live_bridge as bridge


def send_final_delivery(
    client: Any,
    chat_id: int | str,
    session_dir: pathlib.Path,
    session: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not manifest.get("delivery_allowed") and manifest.get("final_verdict") != "PASS_FINAL":
        return {"status": "rejected", "reason": "final_gate_not_passed", "sent": []}
    project_dir = pathlib.Path(str(manifest.get("project_dir") or manifest.get("output_dir") or pathlib.Path(str(manifest.get("package_path", ""))).parent))
    sent = bridge.send_delivery_from_manifest(client, chat_id, session_dir, session, manifest)
    generation = session.setdefault("generation", {})
    generation["final_delivered"] = bool(sent)
    generation["delivery_manifest_sent"] = bool(manifest.get("manifest_path") or manifest.get("delivery_manifest"))
    return {"status": "sent" if sent else "rejected", "sent": sent, "project_dir": str(project_dir)}
