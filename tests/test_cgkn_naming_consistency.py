from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_cgkn_naming_consistency as naming


def test_cgnk_naming_check_passes_for_strict_outputs() -> None:
    result = naming.scan()
    assert result["status"] == "PASS"


def test_legacy_tokens_require_compatibility_context(tmp_path: pathlib.Path) -> None:
    token = "CG" + "KN"
    ok = tmp_path / "ok.md"
    bad = tmp_path / "bad.md"
    ok.write_text(f"legacy machine identifier: {token}\n", encoding="utf-8")
    bad.write_text(f"{token}\n", encoding="utf-8")

    assert naming.scan_file(ok) == []
    findings = naming.scan_file(bad)
    assert findings
    assert findings[0].context == "legacy token outside compatibility context"
