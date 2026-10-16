import pathlib
import shutil

import pytest

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.execution import BlockExecutionRequest, TaskContext


ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.happy_path
@pytest.mark.local_functional
@pytest.mark.hidden_acceptance
def test_seeded_acceptance_is_external_and_returns_only_sanitized_receipt(tmp_path):
    source = ROOT / "benchmarks" / "real_project_generation" / "fixtures" / "seeded_repair"
    workspace = tmp_path / "project"; shutil.copytree(source, workspace)
    (workspace / "math_utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    executor = ExternalAcceptanceExecutor(workspace, ROOT / "benchmarks" / "real_project_generation" / "acceptance")
    request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="accept", component_ref="project.acceptance.external@1", executor_ref="project.acceptance@1", task_context=TaskContext("accept", {"case_id": "seeded_repair"}, {"snapshot": {"snapshot_hash": "sha256:test"}}), timeout_seconds=30)
    result = executor.execute(request)
    assert result.succeeded
    assert result.outputs["status"] == "PASS"
    assert result.outputs["snapshot_hash"] == "sha256:test"
    rendered = str(result.outputs)
    assert "test_seeded_repair.py" not in rendered and "math_utils import" not in rendered


@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_missing_harness_fails_closed(tmp_path):
    executor = ExternalAcceptanceExecutor(tmp_path, tmp_path / "missing")
    request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="accept", component_ref="project.acceptance.external@1", executor_ref="project.acceptance@1", task_context=TaskContext("accept", {"case_id": "unknown"}))
    result = executor.execute(request)
    assert not result.succeeded and result.outputs["failure_class"] == "HARNESS_FAILURE"


@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_failed_acceptance_withholds_harness_diagnostics(tmp_path):
    acceptance = tmp_path / "acceptance"; acceptance.mkdir()
    (acceptance / "test_demo.py").write_text("def test_secret_contract():\n    assert False, 'hidden-value'\n", encoding="utf-8")
    executor = ExternalAcceptanceExecutor(tmp_path / "project", acceptance)
    (tmp_path / "project").mkdir()
    request = BlockExecutionRequest(project_id="p", run_id="r", attempt_id="a", node_id="accept", component_ref="project.acceptance.external@1", executor_ref="project.acceptance@1", task_context=TaskContext("accept", {"case_id": "demo"}, {"snapshot": {"snapshot_hash": "sha256:test"}}), timeout_seconds=30)
    result = executor.execute(request)
    rendered = str(result.outputs)
    assert not result.succeeded
    assert "hidden-value" not in rendered and "test_secret_contract" not in rendered
    assert tuple(result.outputs["failed_requirement_ids"]) == ("public-requirement-1",)
