from __future__ import annotations

import pathlib
import json


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "cgkn"
SKILL_DIR = PLUGIN_DIR / "skills" / "use-cgkn"


def test_plugin_skill_routes_active_codex_through_guarded_mcp_tools() -> None:
    instructions = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert "name: use-cgkn" in instructions
    assert "Use the `cgkn_*` MCP tools" in instructions
    assert "cgkn_prepare" in instructions
    assert "cgkn_seal_brief" in instructions
    assert "cgkn_plan_generation" in instructions
    assert "cgkn_probe_provider" in instructions
    assert "cgkn_generate" in instructions
    assert "cgkn_diagnose_failure" in instructions
    assert "resume.safe" in instructions
    assert "Never pass API keys or tokens as tool arguments" in instructions
    assert "Never ask CGKN tools to start nested Codex sessions" in instructions
    assert "formal evidence PASS" in normalized
    assert "cgkn-agent assist" not in instructions
    assert "python scripts/local_packager.py" not in instructions


def test_cgkn_plugin_has_discoverable_ui_metadata() -> None:
    manifest = json.loads((PLUGIN_DIR / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert manifest["interface"]["displayName"] == "CGKN"
    assert "Plan, generate, diagnose, and test" in manifest["interface"]["shortDescription"]
    assert "MCP" in manifest["interface"]["longDescription"]
    assert len(manifest["interface"]["defaultPrompt"]) == 4
    assert any("diagnose" in prompt.lower() for prompt in manifest["interface"]["defaultPrompt"])
