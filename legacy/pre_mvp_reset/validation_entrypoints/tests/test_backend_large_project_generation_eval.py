from __future__ import annotations

import pathlib

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.e2e]


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "generated" / "front_back_separate_eval" / "run_front_back_eval.py"


def test_ignored_generated_fixture_cannot_be_formal_backend_e2e() -> None:
    assert not EVAL.exists()
    assert "generated" in EVAL.parts
