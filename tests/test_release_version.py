from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_review_candidate_versions_are_aligned() -> None:
    repository_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    plugin = json.loads(
        (ROOT / "plugins" / "cgkn" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    agent_init = (
        ROOT / "tools" / "cgkn-agent-kit" / "src" / "cgkn_agent_kit" / "__init__.py"
    ).read_text(encoding="utf-8")
    server = (ROOT / "plugins" / "cgkn" / "scripts" / "cgkn_mcp_server.py").read_text(
        encoding="utf-8"
    )

    assert repository_version == "0.2.0-rc.1"
    assert plugin["version"].startswith(f"{repository_version}+codex.")
    assert '__version__ = "0.2.0rc1"' in agent_init
    assert re.search(r'^SERVER_VERSION = "0\.2\.0-rc\.1"$', server, re.MULTILINE)
