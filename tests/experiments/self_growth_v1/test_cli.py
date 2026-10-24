from __future__ import annotations

import json

from scripts import run_self_growth_benchmarks as cli


def test_source_identity_can_be_read_without_clean_requirement() -> None:
    commit, tree = cli._source_identity(expected_commit=None, require_clean=False)
    assert len(commit) == 40
    assert len(tree) == 40


def test_pricing_snapshot_has_official_sources() -> None:
    value = json.loads(cli.PRICING_PATH.read_text(encoding="utf-8"))
    assert value["models"]["qwen"]["source"].startswith("https://help.aliyun.com/")
    assert value["models"]["deepseek"]["source"].startswith("https://api-docs.deepseek.com/")
    assert value["models"]["qwen"]["currency"] == "CNY"
    assert value["models"]["deepseek"]["currency"] == "USD"
