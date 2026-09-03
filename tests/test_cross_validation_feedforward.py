from __future__ import annotations

import hashlib
import json

from scripts import cross_validation_feedforward as subject
from scripts import run_local_pipeline_impl


def seal(document: dict, field: str) -> dict:
    result = dict(document)
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result[field] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


def quality(component_id: str, paths: list[str]) -> dict:
    return seal(
        {
            "kind": "CGKNGeneratedComponentQualityValidation",
            "schema_version": 1,
            "component_id": component_id,
            "status": "pass",
            "checks": ["source_contracts"],
            "validated_paths": paths,
            "blockers": [],
            "affected_files": [],
        },
        "receipt_sha256",
    )


def registry(paths: list[str]) -> dict:
    return seal(
        {
            "kind": "CGKNProjectInterfaceRegistry",
            "schema_version": 1,
            "provider_count": len(paths),
            "consumer_edge_count": 0,
            "providers": [{"path": path} for path in paths],
            "consumer_edges": [],
        },
        "registry_sha256",
    )


def snapshot(
    component_id: str,
    *,
    expected: list[str] | None = None,
    completed: list[str] | None = None,
    projections: list[dict] | None = None,
) -> dict:
    return seal(
        {
            "kind": "CGKNIntegrationFeedforwardSnapshot",
            "schema_version": 1,
            "current_component": component_id,
            "current_contract": {
                "expected_upstream_components": expected or [],
                "missing_upstream_components": [],
            },
            "upstream_state": {
                "completed_components": completed or [],
                "cross_validation_feedforward": projections or [],
            },
            "downstream_consumers": [],
        },
        "snapshot_sha256",
    )


def test_component_receipt_cross_binds_all_views_and_projects_only_pass() -> None:
    core = subject.build_component_receipt(
        component_id="core",
        required_paths=["src/core.py"],
        actual_paths=["src/core.py"],
        component_quality_validation=quality("core", ["src/core.py"]),
        interface_registry=registry(["src/core.py"]),
        integration_feedforward=snapshot("core"),
    )

    assert core["status"] == "pass"
    assert core["authority"] == {
        "veto_only": True,
        "can_assert_formal_evidence": False,
        "can_package": False,
        "can_deliver": False,
    }
    projection = subject.component_feedforward_projection(core)
    assert projection["component_id"] == "core"
    assert projection["receipt_sha256"] == core["receipt_sha256"]

    downstream = subject.build_component_receipt(
        component_id="tests",
        required_paths=["tests/test_core.py"],
        actual_paths=["tests/test_core.py"],
        component_quality_validation=quality("tests", ["tests/test_core.py"]),
        interface_registry=registry(["src/core.py", "tests/test_core.py"]),
        integration_feedforward=snapshot(
            "tests",
            expected=["core"],
            completed=["core"],
            projections=[projection],
        ),
    )
    assert downstream["status"] == "pass"


def test_component_receipt_fails_closed_for_tamper_missing_path_and_unvalidated_upstream() -> None:
    tampered_quality = quality("tests", ["tests/test_core.py"])
    tampered_quality["validated_paths"] = ["tests/other.py"]
    receipt = subject.build_component_receipt(
        component_id="tests",
        required_paths=["tests/test_core.py", "tests/test_contract.py"],
        actual_paths=["tests/test_core.py"],
        component_quality_validation=tampered_quality,
        interface_registry=registry(["src/core.py", "tests/test_core.py"]),
        integration_feedforward=snapshot(
            "tests",
            expected=["core"],
            completed=["core"],
            projections=[],
        ),
    )

    assert receipt["status"] == "fail"
    assert subject.component_feedforward_projection(receipt) == {}
    assert any("required paths" in blocker for blocker in receipt["blockers"])
    assert any("quality receipt hash" in blocker for blocker in receipt["blockers"])
    assert any("lack passing" in blocker for blocker in receipt["blockers"])


def test_project_receipt_aggregates_component_and_assembled_quality_without_authority() -> None:
    component = subject.build_component_receipt(
        component_id="core",
        required_paths=["src/core.py"],
        actual_paths=["src/core.py"],
        component_quality_validation=quality("core", ["src/core.py"]),
        interface_registry=registry(["src/core.py"]),
        integration_feedforward=snapshot("core"),
    )
    assembled_quality = seal(
        {
            "kind": "CGKNAssembledProjectQualityValidation",
            "schema_version": 1,
            "status": "pass",
            "blockers": [],
        },
        "receipt_sha256",
    )

    receipt = subject.build_project_receipt(
        component_receipts=[component],
        assembled_quality_validation=assembled_quality,
        required_final_paths=["src/core.py", "README.md"],
        actual_paths=["src/core.py", "README.md"],
        interface_registry=registry(["src/core.py", "README.md"]),
    )

    assert receipt["scope"] == "assembled_project"
    assert receipt["status"] == "pass"
    assert receipt["authority"]["veto_only"] is True
    assert receipt["authority"]["can_deliver"] is False
    assert subject.receipt_hash_valid(receipt)


def test_real_integration_snapshot_carries_only_bounded_passing_projection() -> None:
    core_receipt = subject.build_component_receipt(
        component_id="core",
        required_paths=["src/core.py"],
        actual_paths=["src/core.py"],
        component_quality_validation=quality("core", ["src/core.py"]),
        interface_registry=registry(["src/core.py"]),
        integration_feedforward=snapshot("core"),
    )
    pipeline = {
        "components": [
            {"id": "core", "required_paths": ["src/core.py"]},
            {
                "id": "tests",
                "depends_on": ["core"],
                "required_paths": ["tests/test_core.py"],
            },
        ]
    }
    integrated = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        goal="Build a tested core library.",
        component=pipeline["components"][1],
        component_pipeline=pipeline,
        plan_doc={},
        prior_component_results=[
            {
                "component_id": "core",
                "cross_validation_feedforward_receipt": core_receipt,
            }
        ],
        prior_files=[{"path": "src/core.py", "content": "def run():\n    return 1\n"}],
        repair_errors=[],
    )

    projections = integrated["upstream_state"]["cross_validation_feedforward"]
    assert len(projections) == 1
    assert projections[0]["component_id"] == "core"
    assert "blockers" not in projections[0]
    assert "authority" not in projections[0]

    changed_audit_only = json.loads(json.dumps(integrated))
    changed_audit_only["upstream_state"]["cross_validation_feedforward"][0][
        "receipt_sha256"
    ] = "different-audit-receipt"
    changed_interface = json.loads(json.dumps(integrated))
    changed_interface["upstream_state"]["cross_validation_feedforward"][0][
        "interface_registry_sha256"
    ] = "different-interface"
    assert (
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(integrated)
        == run_local_pipeline_impl.integration_feedforward_checkpoint_hash(changed_audit_only)
    )
    assert (
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(integrated)
        != run_local_pipeline_impl.integration_feedforward_checkpoint_hash(changed_interface)
    )
