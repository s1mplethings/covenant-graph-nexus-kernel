import pathlib
import shutil
import json

import pytest

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.execution import BlockExecutionRequest, TaskContext


ROOT = pathlib.Path(__file__).resolve().parents[3]


def _request(case_id: str, requirements: tuple[str, ...] = ("R1", "R2", "R3")) -> BlockExecutionRequest:
    return BlockExecutionRequest(
        project_id="p", run_id="r", attempt_id="a", node_id="accept",
        component_ref="project.acceptance.external@1", executor_ref="project.acceptance@1",
        task_context=TaskContext(
            "accept", {"case_id": case_id, "acceptance": list(requirements)},
            {"snapshot": {"snapshot_hash": "sha256:test"}},
        ),
        timeout_seconds=30,
    )


def _manifest(root: pathlib.Path, case_id: str, tests: dict[str, list[str]]) -> None:
    (root / f"test_{case_id}.requirements.json").write_text(json.dumps({
        "schema_version": "1.0", "case_id": case_id, "tests": tests,
    }), encoding="utf-8")


@pytest.mark.happy_path
@pytest.mark.local_functional
@pytest.mark.hidden_acceptance
def test_seeded_acceptance_is_external_and_returns_only_sanitized_receipt(tmp_path):
    source = ROOT / "benchmarks" / "real_project_generation" / "fixtures" / "seeded_repair"
    workspace = tmp_path / "project"; shutil.copytree(source, workspace)
    (workspace / "math_utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    executor = ExternalAcceptanceExecutor(workspace, ROOT / "benchmarks" / "real_project_generation" / "acceptance")
    request = _request("seeded_repair", ("arithmetic", "bounded patch", "pytest", "external acceptance"))
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
    request = _request("unknown")
    result = executor.execute(request)
    assert not result.succeeded and result.outputs["failure_class"] == "HARNESS_FAILURE"


@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_failed_acceptance_withholds_harness_diagnostics(tmp_path):
    acceptance = tmp_path / "acceptance"; acceptance.mkdir()
    (acceptance / "test_demo.py").write_text("def test_secret_contract():\n    assert False, 'hidden-value'\n", encoding="utf-8")
    _manifest(acceptance, "demo", {"test_demo.py::test_secret_contract": ["public-requirement-3"]})
    executor = ExternalAcceptanceExecutor(tmp_path / "project", acceptance)
    (tmp_path / "project").mkdir()
    request = _request("demo")
    result = executor.execute(request)
    rendered = str(result.outputs)
    assert not result.succeeded
    assert "hidden-value" not in rendered and "test_secret_contract" not in rendered
    assert tuple(result.outputs["failed_requirement_ids"]) == ("public-requirement-3",)
    assert result.outputs["public_requirement_summaries"] == {"public-requirement-3": "R3"}
    assert result.outputs["mapping_complete"] is True
    assert result.outputs["requirement_manifest_hash"].startswith("sha256:")


@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_multiple_failed_nodes_map_to_stable_public_requirement_order(tmp_path):
    acceptance = tmp_path / "acceptance"; acceptance.mkdir()
    (acceptance / "test_demo.py").write_text(
        "def test_first():\n    assert False\n\ndef test_third():\n    assert False\n",
        encoding="utf-8",
    )
    _manifest(acceptance, "demo", {
        "test_demo.py::test_first": ["public-requirement-1"],
        "test_demo.py::test_third": ["public-requirement-3"],
    })
    project = tmp_path / "project"; project.mkdir()
    result = ExternalAcceptanceExecutor(project, acceptance).execute(_request("demo"))
    assert tuple(result.outputs["failed_requirement_ids"]) == ("public-requirement-1", "public-requirement-3")


@pytest.mark.parametrize("manifest", [
    None,
    {"schema_version": "1.0", "case_id": "demo", "tests": {"test_demo.py::test_failure": ["public-requirement-999"]}},
    {"schema_version": "1.0", "case_id": "wrong", "tests": {"test_demo.py::test_failure": ["public-requirement-1"]}},
])
@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_missing_or_invalid_requirement_manifest_fails_harness_closed(tmp_path, manifest):
    acceptance = tmp_path / "acceptance"; acceptance.mkdir()
    (acceptance / "test_demo.py").write_text("def test_failure():\n    assert False\n", encoding="utf-8")
    if manifest is not None:
        (acceptance / "test_demo.requirements.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = tmp_path / "project"; project.mkdir()
    result = ExternalAcceptanceExecutor(project, acceptance).execute(_request("demo"))
    assert not result.succeeded
    assert result.outputs["failure_class"] == "HARNESS_ATTRIBUTION_UNAVAILABLE"
    assert tuple(result.outputs["failed_requirement_ids"]) == ()
    assert result.outputs["mapping_complete"] is False


@pytest.mark.negative
@pytest.mark.hidden_acceptance
def test_unknown_hidden_node_fails_mapping_without_leaking_identity_or_assertion(tmp_path):
    marker_name = "SUPER_SECRET_HIDDEN_TEST_NAME"
    marker_value = "SUPER_SECRET_EXPECTED_VALUE"
    acceptance = tmp_path / "acceptance"; acceptance.mkdir()
    (acceptance / "test_demo.py").write_text(
        f"def test_{marker_name}():\n    assert False, '{marker_value}'\n", encoding="utf-8",
    )
    _manifest(acceptance, "demo", {"test_demo.py::different_node": ["public-requirement-1"]})
    project = tmp_path / "project"; project.mkdir()
    result = ExternalAcceptanceExecutor(project, acceptance).execute(_request("demo"))
    rendered = json.dumps(result.as_dict(), ensure_ascii=False)
    assert result.outputs["failure_class"] == "HARNESS_ATTRIBUTION_UNAVAILABLE"
    assert marker_name not in rendered and marker_value not in rendered
