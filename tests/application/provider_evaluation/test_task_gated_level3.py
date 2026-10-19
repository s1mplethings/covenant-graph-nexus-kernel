from __future__ import annotations

from dataclasses import replace

import pytest

from cgkn.application.provider_evaluation import (
    ProjectActionAuthority, ProjectProviderPlan, ProductionQualificationEvidence,
    ProviderCapabilityProfile, TaskClassGateStatus, TaskClassQualificationGate,
)
from cgkn.application.software_project.greenfield import (
    BundleInterfaceContract, BundleKind, BundleSpec, ProductionPromptSizePolicy,
    ProjectShapedQualificationReceipt, project_domain_prompt,
)


def profile(provider: str, task: str) -> ProviderCapabilityProfile:
    row = ProviderCapabilityProfile(provider, provider + "-model", task, 1, 1, 1, 1, 1, 1,
                                    100, "UNAVAILABLE", 10, {}, "v", "g", "s", "p", True, (),
                                    profile_hash="sha256:" + provider[0] * 64,
                                    qualification_status="PROVISIONAL_ELIGIBLE", confidence="LOW")
    return row


def plan() -> ProjectProviderPlan:
    return ProjectProviderPlan("campaign", "grok", "grok", "deepseek", "qwen", "qwen", "qwen",
                               {"project.domain.simple": "qwen", "project.domain.persistent": "qwen", "project.domain.library": "grok"},
                               {}, {}, {})


def spec() -> BundleSpec:
    interface = BundleInterfaceContract("sample.core", ("execute", "ProjectError"),
                                        {"execute": "execute(operation, parameters)"}, ("invalid input raises ProjectError",))
    return BundleSpec("project.sample.bundle.domain@1", BundleKind.DOMAIN, "domain", ("sample/core.py",), (), (),
                      (interface.interface_hash,), (), ("obligation.behavior",), ("write_file",),
                      ("tests", "hidden_acceptance"), {"task_class": "project.domain.simple"}, 1000, 10000, 240, "low", interface)


def projection(**overrides):
    values = dict(task_class="project.domain.simple", project_id="sample", package_name="sample",
                  domain_goal="Do the domain work", spec=spec(), obligations=({"ref": "obligation.behavior"},),
                  controlled_errors=("invalid input raises ProjectError",), system="domain only",
                  schema={"type": "object"}, before_payload={"duplicate": "x" * 2000})
    values.update(overrides)
    return project_domain_prompt(**values)


def test_patch_gate_is_independent_of_simple_failure():
    evidence = (
        ProductionQualificationEvidence("project.domain.simple", "qwen", "q", TaskClassGateStatus.PRODUCTION_DEGRADED_NO_CANDIDATE),
        ProductionQualificationEvidence("repository.patch", "qwen", "q", TaskClassGateStatus.PRODUCTION_QUALIFIED, ("receipt",)),
    )
    gate = TaskClassQualificationGate((profile("qwen", "repository.patch"),), evidence)
    patch = gate.decide("repository.patch", plan(), project_id="p04", model_by_provider={"qwen": "qwen3.8-max"})
    simple = gate.decide("project.domain.simple", plan(), project_id="p01", model_by_provider={"grok": "grok-4.7"})
    assert patch.allow_project_run and simple.allow_project_run
    assert patch.status == TaskClassGateStatus.PRODUCTION_QUALIFIED
    assert simple.status == TaskClassGateStatus.PROJECT_QUALIFICATION_IN_PROGRESS


def test_micro_only_provider_enters_project_qualification():
    gate = TaskClassQualificationGate((profile("deepseek", "project.domain.library"),), ())
    decision = gate.decide("project.domain.library", plan(), project_id="p03", model_by_provider={"deepseek": "d"})
    assert decision.allow_project_run and "project-shaped" in decision.reason


def test_prompt_projection_excludes_cli_hidden_and_duplicates():
    value = projection()
    body = str(dict(value.authoritative_payload)).lower()
    assert "hidden" not in body and "cli" not in body and "__main__.py" not in body
    assert "duplicate_project_contract" in value.excluded_authorities
    assert value.total_chars < value.before_chars and value.projection_hash == projection().projection_hash


def test_prompt_projection_rejects_hidden_or_credentials():
    with pytest.raises(RuntimeError, match="PRODUCTION_PROMPT_BOUNDARY_VIOLATION"):
        projection(domain_goal="read hidden_fixture")
    with pytest.raises(RuntimeError, match="PRODUCTION_PROMPT_BOUNDARY_VIOLATION"):
        projection(domain_goal="use api_key")


def test_prompt_projection_overflow_fails_closed():
    tiny = ProductionPromptSizePolicy({"project.domain.simple": 10, "project.domain.persistent": 10,
                                       "project.domain.library": 10, "repository.patch": 10, "project.repair": 10})
    with pytest.raises(RuntimeError, match="PROMPT_PROJECTION_OVERFLOW"):
        projection(size_policy=tiny)


def qualification(value=None):
    value = value or projection()
    return ProjectShapedQualificationReceipt(
        "q1", value.task_class, value.project_id, "grok", "grok-4.7", "pc", "di", "do",
        value.projection_hash, "lesson", "route", "project.domain.simple@1", "revision-1", "PASS", "PASS", True,
    )


def expected(row):
    return {name: str(getattr(row, name)) for name in ("project_id", "task_class", "project_contract_hash",
            "domain_interface_hash", "domain_obligation_hash", "prompt_projection_hash", "lesson_snapshot_hash",
            "route_snapshot_hash", "operation_policy_id", "provider_id", "model")}


def test_qualification_candidate_reuses_only_exact_authority():
    row = qualification(); assert row.assert_reusable(expected(row)) == "revision-1"
    mismatch = expected(row); mismatch["prompt_projection_hash"] = "other"
    with pytest.raises(RuntimeError, match="QUALIFICATION_CANDIDATE_REUSE_FAILURE"):
        row.assert_reusable(mismatch)


def test_candidate_forbids_backup_and_allows_one_repair():
    authority = ProjectActionAuthority("grok", "qwen", "qwen")
    authority.record_candidate("r1")
    with pytest.raises(RuntimeError, match="PROVIDER_ROUTE_AUTHORITY_VIOLATION"):
        authority.authorize_backup(failure_domain="PROVIDER_TRANSPORT_FAILURE")
    assert authority.authorize_repair(failure_domain="CANDIDATE_FUNCTIONAL_DEFECT") == "qwen"
    with pytest.raises(RuntimeError, match="PROJECT_ADDITIONAL_ACTION_LIMIT"):
        authority.authorize_repair(failure_domain="CANDIDATE_FUNCTIONAL_DEFECT")


def test_transport_without_candidate_allows_only_frozen_backup():
    authority = ProjectActionAuthority("grok", "qwen", "qwen")
    assert authority.authorize_backup(failure_domain="PROVIDER_TRANSPORT_FAILURE") == "qwen"
    with pytest.raises(RuntimeError, match="PROJECT_ADDITIONAL_ACTION_LIMIT"):
        authority.authorize_backup(failure_domain="PROVIDER_TRANSPORT_FAILURE")


def test_repair_projection_contains_only_bounded_state_and_failure():
    value = projection(operation="REPAIR", current_sources={"sample/core.py": "pass\n"},
                       failure_evidence={"failure_domain": "CANDIDATE_FUNCTIONAL_DEFECT"})
    assert value.authoritative_payload["existing_sources"] == {"sample/core.py": "pass\n"}
    assert value.authoritative_payload["failure_evidence"]["failure_domain"] == "CANDIDATE_FUNCTIONAL_DEFECT"
