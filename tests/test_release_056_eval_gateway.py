from __future__ import annotations

import pathlib

from scripts import run_release_056_eval_gateway as gateway


def test_gateway_wrapper_pins_dependency_and_never_accepts_a_token_argument() -> None:
    assert gateway.API_LAB_COMMIT == "999dff096afe45f058fe67016aee28a73912d5d4"
    source = pathlib.Path(gateway.__file__).read_text(encoding="utf-8")
    assert "CGKN_PROVIDER_GATEWAY_TOKEN" in source
    assert "info.access_token" in source
    assert "--token" not in source
    assert "shell=False" in source
    assert gateway.MODEL_PRICES_USD_PER_MILLION["qwen"]["input"] == 1.65
    assert gateway.MODEL_PRICES_USD_PER_MILLION["deepseek"]["output"] == 1.20
