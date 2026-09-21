from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repository_cleanup.py"


def load_module():
    spec = importlib.util.spec_from_file_location("repository_cleanup_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_does_not_modify_files(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    module = load_module()
    rows = [
        {"path": "artifacts/run/output.json", "bytes": 25, "topLevel": "artifacts"},
        {"path": "cgkn/runtime/runner.py", "bytes": 100, "topLevel": "cgkn"},
    ]
    monkeypatch.setattr(module, "head_entries", lambda root: rows)
    before = list(tmp_path.rglob("*"))

    assert module.dry_run(tmp_path) == 0

    assert list(tmp_path.rglob("*")) == before
    output = capsys.readouterr().out
    assert '"mode": "dry-run"' in output
    assert '"delete": []' in output
    assert '"artifacts"' in output


def test_cleanup_plan_never_requests_local_delete() -> None:
    module = load_module()
    plan = module.cleanup_plan(
        [{"path": "artifacts/run/output.json", "bytes": 25, "topLevel": "artifacts"}]
    )
    assert plan["delete"] == []
    assert "artifacts" in plan["untrack"]
    assert plan["estimatedFileReduction"] == 1
    assert plan["estimatedSizeReductionBytes"] == 25
