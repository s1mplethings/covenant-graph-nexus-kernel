from cgkn.application.promotion.capabilities import build_promotion_registry
from cgkn.capabilities import CapabilityLifecycle
from cgkn.application.capability_routing import CapabilityEffect, CapabilitySearchIndex, CapabilitySearchRequest
from cgkn.application.self_growth.contracts_v1 import CapabilityProposal, EffectTier
import pytest


def test_promotion_capabilities_use_registry_without_mutating_production():
    registry = build_promotion_registry()
    items = registry.query()
    assert len(items) == 10
    assert registry.resolve("promotion.detect_signal").lifecycle_status is CapabilityLifecycle.ADMITTED
    publisher = next(item for item in items if item.capability_id == "promotion.publish")
    assert publisher.lifecycle_status is CapabilityLifecycle.CANDIDATE
    assert publisher.declared_effects == ("external.write",)
    assert publisher.provenance["production_registry_modified"] is False


def test_capability_queries_find_media_and_external_write():
    registry = build_promotion_registry()
    assert registry.query(output_port="media_asset")
    external = registry.query(effect="external.write")
    assert len(external) == 1 and external[0].capability_id == "promotion.publish"


def test_capability_search_composes_promotion_renderer():
    index = CapabilitySearchIndex.rebuild(build_promotion_registry())
    result = index.search(CapabilitySearchRequest("render a promotion video", available_inputs=("campaign",), allowed_effects=(CapabilityEffect.WRITE_CODE,), allowed_scope=("promotion",)))
    assert result.status == "PASS"
    assert any(item.capability_ref.startswith("promotion.render_video@") for item in result.candidates)


def test_self_growth_cannot_auto_propose_external_publisher():
    with pytest.raises(ValueError, match="not eligible"):
        CapabilityProposal("c", "promotion.publisher.extra", "1", "publish externally", "transport", {"semantic_type": "plan"}, {"semantic_type": "receipt"}, EffectTier.EXTERNAL_WRITE, ("oauth",), (), ("external.write",), ("fail-closed",), ("promotion",), (), "no adapter", ("promotion",), ("hidden qualification",), ("human approval",))
