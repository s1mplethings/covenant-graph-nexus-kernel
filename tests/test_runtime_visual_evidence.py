from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import runtime_visual_evidence


def test_no_screenshot_fails(tmp_path: pathlib.Path) -> None:
    result = runtime_visual_evidence.collect_visual_evidence(tmp_path)
    assert result["verdict"] == "FAIL"


def test_runtime_preview_png_passes(tmp_path: pathlib.Path) -> None:
    runtime_visual_evidence.write_runtime_preview_png(tmp_path / "screenshots" / "app_home.png")
    result = runtime_visual_evidence.collect_visual_evidence(tmp_path)
    assert result["verdict"] == "PASS"
    assert result["screenshots"]


def test_static_html_preview_evidence_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main>Hello</main>", encoding="utf-8")
    result = runtime_visual_evidence.create_static_html_preview_evidence(tmp_path)
    assert result["verdict"] == "PASS"
