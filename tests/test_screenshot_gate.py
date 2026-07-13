from __future__ import annotations

import base64
import pathlib

import pytest

from scripts.screenshot_gate import inspect_screenshot, screenshot_integrity_gate

PIL = pytest.importorskip("PIL.Image")
from PIL import Image, ImageDraw  # noqa: E402


def _meta(path: pathlib.Path) -> dict:
    return {
        "path": str(path),
        "candidate_id": "candidate_a",
        "database_hash": "db_a",
        "browser_session_id": "browser_a",
        "url": "http://127.0.0.1:5000/",
        "action_id": "action_a",
        "captured_after_action": True,
    }


def test_rejects_fake_header_only_and_one_by_one_png(tmp_path: pathlib.Path) -> None:
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"\x89PNG\r\n\x1a\nnot a png")
    tiny = tmp_path / "tiny.png"
    tiny.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))

    assert inspect_screenshot(fake)["reason"] == "decode_failed"
    tiny_result = inspect_screenshot(tiny)
    assert tiny_result["status"] == "NEEDS_REWORK"
    assert "too_small" in tiny_result["reasons"]


def test_rejects_pure_color_and_duplicate_screenshots(tmp_path: pathlib.Path) -> None:
    pure = tmp_path / "pure.png"
    Image.new("RGB", (900, 700), "white").save(pure)
    duplicate = tmp_path / "duplicate.png"
    duplicate.write_bytes(pure.read_bytes())

    gate = screenshot_integrity_gate([_meta(pure), _meta(duplicate)], candidate_id="candidate_a", database_hash="db_a", browser_session_id="browser_a")

    assert gate["status"] == "NEEDS_REWORK"
    assert gate["duplicate_count"] >= 1
    assert any("pure_color" in item["reasons"] for item in gate["inspections"])


def test_accepts_valid_800_by_600_browser_screenshot_metadata(tmp_path: pathlib.Path) -> None:
    shot = tmp_path / "dashboard.png"
    image = Image.new("RGB", (900, 700), "white")
    draw = ImageDraw.Draw(image)
    for index in range(0, 900, 20):
        color = (index % 255, (index * 2) % 255, (index * 3) % 255)
        draw.rectangle([index, 0, min(899, index + 12), 699], fill=color)
    draw.text((40, 40), "Local Research Experiment Tracker 中文实验 Alpha", fill=(0, 0, 0))
    image.save(shot)

    gate = screenshot_integrity_gate([_meta(shot)], candidate_id="candidate_a", database_hash="db_a", browser_session_id="browser_a")

    assert gate["status"] == "PASS"
    assert gate["valid_count"] == 1


def test_rejects_wrong_candidate_database_browser_or_old_action(tmp_path: pathlib.Path) -> None:
    shot = tmp_path / "dashboard.png"
    image = Image.new("RGB", (900, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 880, 680], fill=(20, 120, 200))
    draw.text((40, 40), "real content", fill=(255, 255, 255))
    image.save(shot)
    meta = _meta(shot)
    meta["candidate_id"] = "old"
    meta["database_hash"] = "other"
    meta["browser_session_id"] = "other_browser"
    meta["captured_after_action"] = False

    gate = screenshot_integrity_gate([meta], candidate_id="candidate_a", database_hash="db_a", browser_session_id="browser_a")

    reasons = gate["inspections"][0]["reasons"]
    assert "wrong_candidate" in reasons
    assert "wrong_database" in reasons
    assert "wrong_browser_session" in reasons
    assert "not_after_user_action" in reasons
