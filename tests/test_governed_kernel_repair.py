from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import governed_kernel_repair as repair


def test_repair_request_rejects_candidate_and_requires_regression_target() -> None:
    checkpoint = {"checkpoint_id": "cp", "checkpoint_sha256": "b" * 64}
    base = {
        "action": "repair_kernel",
        "scope": "kernel",
        "result_sha256": "c" * 64,
        "acceptance_checks": [],
    }
    with pytest.raises(ValueError, match="unsafe"):
        repair.build_repair_request(
            {**base, "repair_targets": ["generated/customer/app.py", "tests/test_bug.py"]},
            checkpoint,
            reproduction_checks=["pytest tests/test_bug.py"],
        )
    with pytest.raises(ValueError, match="regression test"):
        repair.build_repair_request(
            {**base, "repair_targets": ["scripts/router.py"]},
            checkpoint,
            reproduction_checks=["pytest tests/test_bug.py"],
        )


def test_repair_executes_in_allowlisted_mirror_then_copies_declared_files() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / "scripts").mkdir()
        (root / "tests").mkdir()
        (root / "scripts" / "validator.py").write_text("BUG = True\n", encoding="utf-8")
        (root / "tests" / "test_validator.py").write_text("def test_bug(): pass\n", encoding="utf-8")
        request = {
            "checkpoint_id": "cp",
            "repair_targets": ["scripts/validator.py", "tests/test_validator.py"],
            "reproduction_checks": ["python -m pytest tests/test_validator.py -q"],
        }

        def fake_codex(argv, **kwargs):
            isolated = pathlib.Path(argv[argv.index("--cd") + 1])
            (isolated / "scripts" / "validator.py").write_text("BUG = False\n", encoding="utf-8")
            (isolated / "tests" / "test_validator.py").write_text("def test_bug(): assert True\n", encoding="utf-8")
            assert not (isolated / "generated").exists()
            assert "workspace-write" in argv
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        def fake_test(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="1 passed", stderr="")

        receipt = repair.execute_repair(
            request,
            root,
            codex_command="codex",
            runner=fake_codex,
            test_runner=fake_test,
        )
        assert receipt["status"] == "PASS"
        assert (root / "scripts" / "validator.py").read_text(encoding="utf-8") == "BUG = False\n"
        assert receipt["original_checkpoint_must_be_reemitted"] is True
