from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "codex_conversation_contract.md"
BRIDGE = ROOT / "scripts" / "codex_conversation.py"


def test_contract_document_records_expected_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")
    for term in (
        "only user-facing intake and result surface",
        "support lane",
        "whiteboard + agent_session",
        "reviewed Provider route",
        "local_packager",
        "public delivery",
    ):
        assert term in text


def test_bridge_preserves_legacy_and_mainline_guards() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "LEGACY PROVIDER PIPELINE" in source
    assert "Codex conversation mainline must not call this" in source
    start = source[source.index("def start_agent_generation(") : source.index("def record_generation_start_waiting(")]
    assert "target=run_agent_generation_job" not in start


def test_public_delivery_is_gated_before_emit() -> None:
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    checked = 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        gate_lines = [
            call.lineno
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "evaluate_public_delivery_gate"
        ]
        emit_lines = [
            call.lineno
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "emit_public_delivery"
        ]
        for emit_line in emit_lines:
            checked += 1
            assert any(gate_line < emit_line for gate_line in gate_lines), node.name
    assert checked > 0
