from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_public_benchmark_adapter", ROOT / "scripts" / "run_public_benchmark_adapter.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

pytestmark = pytest.mark.benchmark


def _git(root: pathlib.Path, *args: str) -> str:
    value = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return value.stdout.strip()


def _checkout(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    root = tmp_path / "official"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "CGNK Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("official harness\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _benchmark(commit: str) -> dict:
    return {
        "id": "TEST", "repository": "https://example.invalid/official",
        "commit": commit, "license": "Apache-2.0", "redistribution": "NO_DATA_COPY",
    }


def test_adapter_runs_clean_pinned_checkout_and_sanitizes_output(tmp_path: pathlib.Path) -> None:
    checkout, commit = _checkout(tmp_path)
    output = tmp_path / "evidence" / "run-1"
    result = MODULE.run_adapter(
        benchmark=_benchmark(commit), checkout=checkout,
        command=[sys.executable, "-c", "print('official evaluator pass')"],
        output=output, timeout_seconds=10, task_ids=["T-1"],
    )
    assert result["status"] == "PASS"
    assert result["task_ids"] == ["T-1"]
    assert result["official_checkout_clean_before_after"] is True
    assert json.loads((output / "receipt.json").read_text(encoding="utf-8"))["receipt_hash"] == result["receipt_hash"]


def test_adapter_rejects_dirty_or_mismatched_checkout(tmp_path: pathlib.Path) -> None:
    checkout, commit = _checkout(tmp_path)
    (checkout / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="clean"):
        MODULE.verify_checkout(checkout, commit)
    (checkout / "dirty.txt").unlink()
    with pytest.raises(ValueError, match="commit mismatch"):
        MODULE.verify_checkout(checkout, "0" * 40)


def test_adapter_rejects_secret_bearing_command_arguments() -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        MODULE.validate_command(["python", "runner.py", "--api-key", "do-not-store"])
