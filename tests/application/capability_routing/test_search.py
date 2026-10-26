from __future__ import annotations

import pytest

from cgkn.application.capability_routing import (
    CapabilityEffect,
    CapabilitySearchIndex,
    CapabilitySearchRequest,
)
from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def _add(
    registry: CapabilityRegistry,
    component: ComponentSpec,
    *,
    executor: str = "deterministic@1",
    effects: tuple[str, ...] = (),
    status: CapabilityLifecycle = CapabilityLifecycle.ADMITTED,
    version: str = "1",
) -> None:
    descriptor = CapabilityDescriptor(
        component.component_id,
        version,
        component.ref,
        executor,
        ("deterministic",),
        tuple(port.name for port in component.input_ports),
        tuple(port.name for port in component.output_ports),
        effects,
        5.0,
        "zero",
        "LOW",
        "test",
        {},
        ("tests/capability-routing",),
    )
    registry.register_candidate(descriptor)
    if status is CapabilityLifecycle.ADMITTED:
        registry.admit(descriptor.ref)


def _registry() -> CapabilityRegistry:
    text = PortSpec("text", "artifact.text@1")
    result = PortSpec("result", "artifact.result@1")
    components = (
        ComponentSpec("text.slugify", "1", (text,), (result,), {}, None, {"purpose": "Create URL slugs from human text"}),
        ComponentSpec("knowledge.search", "1", (PortSpec("query", "artifact.query@1"),), (result,), {"knowledge": "read-only"}, None, {"purpose": "Retrieve grounded knowledge evidence"}),
        ComponentSpec("source.patch", "1", (PortSpec("patch", "artifact.patch@1"),), (result,), {"filesystem": "write"}, None, {"purpose": "Repair and patch source code", "permissions": ["source.write"], "scope": ["project"]}),
        ComponentSpec("release.publish", "1", (PortSpec("release", "artifact.release@1"),), (result,), {"external": "write"}, None, {"purpose": "Publish a release", "permissions": ["release.publish"]}),
        ComponentSpec("system.maintain", "1", (), (result,), {"maintenance": "compact"}, None, {"purpose": "Compact derived indexes", "required_state": ["maintenance_window"]}),
        ComponentSpec("candidate.unqualified", "1", (), (result,), {}, None, {"purpose": "Unqualified candidate"}),
        ComponentSpec("text.slugify", "2", (text,), (result,), {}, None, {"purpose": "Create URL slugs from human text"}),
    )
    registry = CapabilityRegistry({item.ref: item for item in components})
    for component in components:
        effects = (
            ("filesystem.write",)
            if component.component_id == "source.patch"
            else ("external.write",)
            if component.component_id == "release.publish"
            else ("maintenance.compact",)
            if component.component_id == "system.maintain"
            else ()
        )
        status = CapabilityLifecycle.CANDIDATE if component.component_id == "candidate.unqualified" else CapabilityLifecycle.ADMITTED
        _add(registry, component, effects=effects, status=status, version=component.version)
    return registry


def test_index_is_deterministically_rebuilt_from_registry_authority() -> None:
    registry = _registry()
    first = CapabilitySearchIndex.rebuild(registry)
    second = CapabilitySearchIndex.rebuild(registry)
    assert first.index_hash == second.index_hash
    assert first.authority_hash == second.authority_hash
    assert len(first.records) == len(registry.query())


def test_exact_capability_name_and_version_select_one_qualified_record() -> None:
    index = CapabilitySearchIndex.rebuild(_registry())
    result = index.search(CapabilitySearchRequest(
        "text.slugify@1", ("text",), (CapabilityEffect.READ_ONLY,), requested_version="1", exact_ref="text.slugify@1"
    ))
    assert result.status == "PASS"
    assert [item.capability_ref for item in result.candidates] == ["text.slugify@1"]


def test_semantic_paraphrase_selects_grounded_knowledge_retrieval() -> None:
    index = CapabilitySearchIndex.rebuild(_registry())
    result = index.search(CapabilitySearchRequest(
        "find grounded evidence for a question", ("query",), (CapabilityEffect.READ_ONLY,), top_k=3
    ))
    assert result.candidates[0].capability_ref == "knowledge.search@1"


@pytest.mark.parametrize(
    "search_request,rejection",
    [
        (CapabilitySearchRequest("repair source code", ("patch",), (CapabilityEffect.READ_ONLY,), permissions=("source.write",), allowed_scope=("project",)), "EFFECT_NOT_ALLOWED"),
        (CapabilitySearchRequest("repair source code", (), (CapabilityEffect.WRITE_CODE,), permissions=("source.write",), allowed_scope=("project",)), "MISSING_INPUT"),
        (CapabilitySearchRequest("repair source code", ("patch",), (CapabilityEffect.WRITE_CODE,), allowed_scope=("project",)), "PERMISSION_DENIED"),
        (CapabilitySearchRequest("repair source code", ("patch",), (CapabilityEffect.WRITE_CODE,), permissions=("source.write",)), "SCOPE_DENIED"),
        (CapabilitySearchRequest("text slug", ("text",), (CapabilityEffect.READ_ONLY,), requested_version="9"), "VERSION_MISMATCH"),
    ],
)
def test_deterministic_eligibility_rejects_incompatible_candidates(search_request, rejection) -> None:
    result = CapabilitySearchIndex.rebuild(_registry()).search(search_request)
    assert any(rejection in reasons for reasons in result.rejected.values())


def test_unqualified_and_external_action_capabilities_fail_closed() -> None:
    index = CapabilitySearchIndex.rebuild(_registry())
    unqualified = index.search(CapabilitySearchRequest("unqualified candidate", allowed_effects=(CapabilityEffect.READ_ONLY,)))
    assert "UNQUALIFIED" in unqualified.rejected["candidate.unqualified@1"]
    external = index.search(CapabilitySearchRequest("publish release", ("release",), (CapabilityEffect.READ_ONLY,), permissions=("release.publish",)))
    assert "EFFECT_NOT_ALLOWED" in external.rejected["release.publish@1"]


def test_required_state_is_an_eligibility_gate() -> None:
    index = CapabilitySearchIndex.rebuild(_registry())
    blocked = index.search(CapabilitySearchRequest("compact indexes", allowed_effects=(CapabilityEffect.MAINTENANCE,)))
    assert "REQUIRED_STATE_MISSING" in blocked.rejected["system.maintain@1"]
    allowed = index.search(CapabilitySearchRequest("compact indexes", allowed_effects=(CapabilityEffect.MAINTENANCE,), available_state=("maintenance_window",)))
    assert allowed.candidates[0].capability_ref == "system.maintain@1"


def test_read_write_and_maintenance_effects_remain_distinct() -> None:
    index = CapabilitySearchIndex.rebuild(_registry())
    effects = {item.capability_ref: item.effect for item in index.records}
    assert effects["knowledge.search@1"] is CapabilityEffect.READ_ONLY
    assert effects["source.patch@1"] is CapabilityEffect.WRITE_CODE
    assert effects["release.publish@1"] is CapabilityEffect.EXTERNAL_ACTION
    assert effects["system.maintain@1"] is CapabilityEffect.MAINTENANCE


def test_irrelevant_capability_flood_keeps_topk_context_bounded() -> None:
    from cgkn.application.capability_routing.benchmarks import synthetic_registry

    registry, expected = synthetic_registry(1000)
    result = CapabilitySearchIndex.rebuild(registry).search(
        CapabilitySearchRequest("clean CSV rows and remove duplicate blank records", top_k=3)
    )
    assert result.candidates[0].capability_ref == expected
    assert len(result.candidates) == 3
    assert result.topk_context_tokens < result.full_registry_context_tokens * 0.1


def test_no_eligible_capability_is_explicit_not_fallback() -> None:
    result = CapabilitySearchIndex.rebuild(_registry()).search(
        CapabilitySearchRequest("publish release", ("release",), (CapabilityEffect.EXTERNAL_ACTION,), permissions=())
    )
    assert result.status == "NO_ELIGIBLE_CAPABILITY"
    assert result.candidates == ()


def test_search_request_is_strict_and_immutable() -> None:
    with pytest.raises(ValueError, match="goal"):
        CapabilitySearchRequest(" ")
    with pytest.raises(ValueError, match="top_k"):
        CapabilitySearchRequest("x", top_k=0)
    request = CapabilitySearchRequest("x", permissions=("p", "p"))
    assert request.permissions == ("p",)

