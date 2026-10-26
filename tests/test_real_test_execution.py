from __future__ import annotations

import os
import pathlib
import sys
import json

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import real_test_execution
from scripts import canonical_evidence_hash


def test_model_written_summary_without_execution_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("# Test Report\n\nlooks good\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "test_execution.json" in result["missing"]


def test_real_pytest_execution_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    result = real_test_execution.run_tests(tmp_path, run_id="run-a", candidate_id="candidate-a", commit_sha="commit-a")
    assert result["kind"] == "CGKNTestExecutionEvidence"
    assert result["schema_version"] == "1.0"
    assert result["status"] == "PASS"
    assert result["argv"]
    assert result["stdout_hash"].startswith("sha256:")
    assert result["stderr_hash"].startswith("sha256:")
    assert result["result_artifact_hash"].startswith("sha256:")
    report = (tmp_path / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "run_id: run-a" in report
    assert f"candidate_hash: {result['candidate_hash']}" in report
    assert "commit_sha: commit-a" in report
    assert "commands_run:" in report
    assert "python" in report and "pytest" in report
    assert real_test_execution.inspect_test_report(tmp_path, run_id="run-a", candidate_hash=result["candidate_hash"], commit_sha="commit-a")["verdict"] == "PASS"


def test_real_pytest_ignores_deleted_inherited_pythonpath(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted_parent = tmp_path.parent / "deleted-parent-pythonpath"
    assert not deleted_parent.exists()
    monkeypatch.setenv("PYTHONPATH", str(deleted_parent))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    result = real_test_execution.run_tests(tmp_path)

    assert result["status"] == "PASS"
    assert result["collected"] == 1


def test_real_pytest_does_not_execute_existing_inherited_pythonpath_startup_code(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inherited = tmp_path / "parent-pythonpath"
    inherited.mkdir()
    (inherited / "sitecustomize.py").write_text(
        "raise RuntimeError('parent startup code executed')\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(inherited))
    candidate = tmp_path / "candidate"
    (candidate / "tests").mkdir(parents=True)
    (candidate / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    result = real_test_execution.run_tests(candidate)

    assert result["status"] == "PASS"
    stdout = pathlib.Path(result["stdout_artifact"]).read_text(encoding="utf-8")
    stderr = pathlib.Path(result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "parent startup code executed" not in stdout + stderr


def test_real_pytest_uses_minimal_parent_environment_and_live_owned_temp(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNRELATED_PARENT_SENTINEL", "must-not-leak")
    candidate = tmp_path / "candidate"
    (candidate / "tests").mkdir(parents=True)
    (candidate / "tests" / "test_environment.py").write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "def test_child_environment():\n"
        "    assert 'UNRELATED_PARENT_SENTINEL' not in os.environ\n"
        "    assert Path(os.environ['TEMP']).is_dir()\n"
        "    assert Path(os.environ['TMP']).is_dir()\n",
        encoding="utf-8",
    )

    result = real_test_execution.run_tests(candidate)

    assert result["status"] == "PASS"
    assert result["environment"] == "isolated_minimal_env"
    basetemp_index = result["argv"].index("--basetemp")
    assert not pathlib.Path(result["argv"][basetemp_index + 1]).exists()


def test_declared_pytest_testpaths_are_authoritative_over_legacy_tests(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["quality_tests"]\n',
        encoding="utf-8",
    )
    legacy = tmp_path / "tests"
    legacy.mkdir()
    (legacy / "test_legacy.py").write_text(
        "def test_legacy_guess():\n    assert False\n",
        encoding="utf-8",
    )
    quality = tmp_path / "quality_tests"
    quality.mkdir()
    (quality / "test_quality.py").write_text(
        "def test_quality_contract():\n    assert True\n",
        encoding="utf-8",
    )

    result = real_test_execution.run_tests(tmp_path)

    assert result["status"] == "PASS"
    assert result["collected"] == 1
    assert result["argv"][-1] == "quality_tests"
    assert "test_legacy_guess" not in (tmp_path / "test_stdout.txt").read_text(encoding="utf-8")


def test_test_output_dir_is_cleaned_after_success(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -s\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_output_dir.py").write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "def test_uses_test_output_dir():\n"
        "    root = Path(os.environ['CGKN_TEST_OUTPUT_DIR'])\n"
        "    marker = root / 'marker.txt'\n"
        "    marker.write_text('ok', encoding='utf-8')\n"
        "    print(f'CGKN_TEST_OUTPUT_DIR={root}', flush=True)\n"
        "    print(f'CGKN_TEST_OUTPUT_MARKER={marker.exists()}', flush=True)\n",
        encoding="utf-8",
    )
    result = real_test_execution.run_tests(tmp_path)
    stdout = (tmp_path / "test_stdout.txt").read_text(encoding="utf-8")
    output_line = next(line for line in stdout.splitlines() if "CGKN_TEST_OUTPUT_DIR=" in line)
    output_dir = pathlib.Path(output_line.split("CGKN_TEST_OUTPUT_DIR=", 1)[1])

    assert result["status"] == "PASS"
    assert "CGKN_TEST_OUTPUT_MARKER=True" in stdout
    assert not output_dir.exists()
    assert not (tmp_path / "marker.txt").exists()
    assert "CGKN_TEST_OUTPUT_DIR" not in os.environ
    assert result["candidate_mutated_during_test"] is False


def test_test_output_dir_is_cleaned_after_timeout(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[pathlib.Path] = []
    real_temporary_directory = real_test_execution.tempfile.TemporaryDirectory

    class RecordingTemporaryDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._inner = real_temporary_directory(*args, **kwargs)

        def __enter__(self) -> str:
            path = pathlib.Path(self._inner.__enter__())
            created.append(path)
            return str(path)

        def __exit__(self, *exc_info: object) -> object:
            return self._inner.__exit__(*exc_info)

    monkeypatch.setattr(real_test_execution.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -s\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_timeout.py").write_text(
        "import os\n"
        "import time\n"
        "from pathlib import Path\n\n"
        "def test_timeout_cleanup():\n"
        "    root = Path(os.environ['CGKN_TEST_OUTPUT_DIR'])\n"
        "    (root / 'timeout-marker.txt').write_text('alive', encoding='utf-8')\n"
        "    print(f'CGKN_TEST_OUTPUT_DIR={root}', flush=True)\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    result = real_test_execution.run_tests(tmp_path, timeout=1)

    assert result["status"] == "FAIL"
    assert result["timeout"] is True
    assert created
    assert all(not path.exists() for path in created)
    assert "CGKN_TEST_OUTPUT_DIR" not in os.environ


def test_candidate_source_hash_excludes_evidence_outputs_not_product_assets(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    asset = tmp_path / "generated" / "background_scene.png"
    asset.write_bytes(b"product-asset")
    before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    for name in ("test_execution.json", "TEST_REPORT.md", "test_stdout.txt", "test_stderr.txt", "customer_runtime.json", "visual_evidence.json"):
        (tmp_path / name).write_text("changed evidence output\n", encoding="utf-8")
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "browser_visual_evidence.png").write_bytes(b"screenshot output")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) == before
    asset.write_bytes(b"changed-product-asset")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) != before


@pytest.mark.parametrize(
    "relative_path",
    [
        "screenshots/product_reference.png",
        "media/generated_images/final_background.png",
        "export/project.json",
        "exports/customer_bundle.json",
        "output/final_result.json",
        "outputs/report.json",
        "projects/workspace.json",
        "src/env/settings.py",
        "fixtures/delivery_manifest.json",
    ],
)
def test_candidate_source_hash_includes_product_paths_with_tool_like_names(tmp_path: pathlib.Path, relative_path: str) -> None:
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("product-v1\n", encoding="utf-8")
    before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    target.write_text("product-v2\n", encoding="utf-8")
    after = canonical_evidence_hash.candidate_source_hash(tmp_path)
    assert after != before


def test_candidate_source_hash_excludes_only_root_evidence_files(tmp_path: pathlib.Path) -> None:
    root_manifest = tmp_path / "delivery_manifest.json"
    root_manifest.write_text("root evidence\n", encoding="utf-8")
    before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    root_manifest.write_text("changed root evidence\n", encoding="utf-8")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) == before

    nested_manifest = tmp_path / "fixtures" / "delivery_manifest.json"
    nested_manifest.parent.mkdir()
    nested_manifest.write_text("nested product manifest\n", encoding="utf-8")
    nested_before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    nested_manifest.write_text("changed nested product manifest\n", encoding="utf-8")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) != nested_before


def test_candidate_source_hash_excludes_root_env_but_includes_nested_env(tmp_path: pathlib.Path) -> None:
    root_env = tmp_path / "env" / "tool.txt"
    root_env.parent.mkdir()
    root_env.write_text("root env\n", encoding="utf-8")
    before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    root_env.write_text("changed root env\n", encoding="utf-8")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) == before

    nested_env = tmp_path / "src" / "env" / "settings.py"
    nested_env.parent.mkdir(parents=True)
    nested_env.write_text("VALUE = 1\n", encoding="utf-8")
    nested_before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    nested_env.write_text("VALUE = 2\n", encoding="utf-8")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) != nested_before


def test_no_real_execution_marker_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("commands_run:\n- NO REAL TEST EXECUTION\nexit_code: none\nNO REAL TEST EXECUTION\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"


def test_hash_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["stdout_hash"] = "sha256:bad"
    (tmp_path / "test_execution.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "stdout_hash_mismatch" in result["missing"]


def test_test_execution_status_tamper_without_hash_update_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["status"] = "FAIL"
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]


def test_test_execution_self_equal_fake_hashes_do_not_pass(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["artifact_hash"] = "sha256:" + "0" * 64
    doc["result_artifact_hash"] = "sha256:" + "0" * 64
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]
    assert "result_artifact_hash" in result["missing"]


def test_stdout_and_stderr_file_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    (tmp_path / "test_stdout.txt").write_text("tampered stdout\n", encoding="utf-8")
    stdout_result = real_test_execution.inspect_test_report(tmp_path)
    assert stdout_result["verdict"] == "FAIL"
    assert "stdout_hash_mismatch" in stdout_result["missing"]
    real_test_execution.run_tests(tmp_path)
    (tmp_path / "test_stderr.txt").write_text("tampered stderr\n", encoding="utf-8")
    stderr_result = real_test_execution.inspect_test_report(tmp_path)
    assert stderr_result["verdict"] == "FAIL"
    assert "stderr_hash_mismatch" in stderr_result["missing"]


def test_test_candidate_hash_tamper_with_fake_artifact_hashes_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["candidate_hash"] = "sha256:" + "1" * 64
    doc["artifact_hash"] = "sha256:" + "2" * 64
    doc["result_artifact_hash"] = "sha256:" + "2" * 64
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "candidate_hash_current" in result["missing"]


def test_candidate_hash_mismatch_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path, candidate_hash="sha256:actual")
    result = real_test_execution.inspect_test_report(tmp_path, candidate_hash="sha256:other")
    assert result["verdict"] == "FAIL"
    assert "candidate_hash" in result["missing"]


def test_candidate_pytest_does_not_inherit_repository_pytest_controls(
    tmp_path: pathlib.Path, monkeypatch,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_env.py").write_text(
        "import os\n\n"
        "def test_outer_pytest_controls_are_absent():\n"
        "    for name in ('PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'CGKN_PYTEST_EVENT_LOG'):\n"
        "        assert name not in os.environ\n"
        "    assert os.environ.get('PYTEST_CURRENT_TEST') != 'outer::node (call)'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", "--definitely-not-a-real-option")
    monkeypatch.setenv("PYTEST_PLUGINS", "missing_outer_plugin")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "outer::node (call)")
    monkeypatch.setenv("CGKN_PYTEST_EVENT_LOG", str(tmp_path / "outer-events.jsonl"))

    result = real_test_execution.run_tests(tmp_path)

    assert result["status"] == "PASS", result
    assert result["collected"] == 1
    assert result["passed"] == 1


def test_test_time_product_file_change_detects_candidate_mutation(tmp_path: pathlib.Path) -> None:
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "project.json").write_text('{"version": 1}\n', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mutation.py").write_text(
        "from pathlib import Path\n\n"
        "def test_mutates_export():\n"
        "    Path('export/project.json').write_text('{\"version\": 2}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = real_test_execution.run_tests(tmp_path)
    assert result["status"] == "FAIL"
    assert result["candidate_mutated_during_test"] is True
    assert "export/project.json" in result["candidate_source_diff"]["changed"]


def test_test_time_product_file_added_detects_candidate_mutation(tmp_path: pathlib.Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mutation.py").write_text(
        "from pathlib import Path\n\n"
        "def test_adds_output():\n"
        "    Path('outputs').mkdir(exist_ok=True)\n"
        "    Path('outputs/result.json').write_text('{\"ok\": true}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = real_test_execution.run_tests(tmp_path)
    assert result["status"] == "FAIL"
    assert result["candidate_mutated_during_test"] is True
    assert "outputs/result.json" in result["candidate_source_diff"]["added"]


def test_test_time_cache_and_evidence_outputs_do_not_trigger_candidate_mutation(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_outputs.py").write_text(
        "from pathlib import Path\n\n"
        "def test_writes_only_cache_and_evidence_outputs():\n"
        "    Path('__pycache__').mkdir(exist_ok=True)\n"
        "    Path('__pycache__/module.pyc').write_bytes(b'pyc')\n"
        "    Path('.pytest_cache').mkdir(exist_ok=True)\n"
        "    Path('.pytest_cache/state').write_text('cache', encoding='utf-8')\n"
        "    Path('test_stdout.txt').write_text('stdout', encoding='utf-8')\n"
        "    Path('test_stderr.txt').write_text('stderr', encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = real_test_execution.run_tests(tmp_path)
    assert result["status"] == "PASS"
    assert result["candidate_mutated_during_test"] is False


def test_explicit_minimum_collected_tests_is_enforced(tmp_path: pathlib.Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_small.py").write_text(
        "def test_one():\n"
        "    assert True\n"
        "\n"
        "def test_two():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = real_test_execution.run_tests(tmp_path, minimum_collected=3)

    assert result["exit_code"] == 0
    assert result["collected"] == 2
    assert result["status"] == "FAIL"
    assert result["minimum_collected_required"] == 3
    assert result["minimum_collected_met"] is False
