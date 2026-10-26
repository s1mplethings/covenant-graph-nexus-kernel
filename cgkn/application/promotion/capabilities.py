from __future__ import annotations

from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec


PROMOTION_CAPABILITIES = (
    ("promotion.collect_evidence", "evidence", "promotion_evidence", "read.project.evidence", "READ_LOCAL", "Collect a public-safe evidence projection."),
    ("promotion.detect_signal", "promotion_evidence", "promotion_signal", "detect.signal", "PURE", "Detect publication value from validated evidence."),
    ("promotion.build_campaign", "promotion_signal", "campaign", "build.campaign", "PURE", "Build a canonical evidence-bound campaign brief."),
    ("promotion.generate_copy", "campaign", "content_variants", "generate.copy", "PURE", "Generate bounded platform variants from approved claims."),
    ("promotion.validate_claims", "content_variants", "claim_validation", "validate.claims", "PURE", "Validate claim support, privacy, and platform constraints."),
    ("promotion.render_card", "campaign", "media_asset", "render.card", "WRITE_LOCAL_SANDBOX", "Render deterministic evidence cards."),
    ("promotion.render_video", "campaign", "media_asset", "render.video", "WRITE_LOCAL_SANDBOX", "Render deterministic FFmpeg promotion video."),
    ("promotion.plan_publication", "content_variants", "publication_plan", "plan.publication", "PURE", "Bind approval and idempotent publication plans."),
    ("promotion.publish", "publication_plan", "publication_receipt", "publish.external", "EXTERNAL_WRITE", "Publish approved content through a qualified adapter."),
    ("promotion.fetch_metrics", "publication_receipt", "analytics", "fetch.metrics", "EXTERNAL_READ", "Fetch aggregate platform analytics where supported."),
)


def build_promotion_registry() -> CapabilityRegistry:
    components: dict[str, ComponentSpec] = {}
    descriptors: list[CapabilityDescriptor] = []
    for capability_id, input_name, output_name, executor_ref, effect, purpose in PROMOTION_CAPABILITIES:
        component = ComponentSpec(
            capability_id, "1.0",
            (PortSpec(input_name, f"artifact.promotion.{input_name}@1"),),
            (PortSpec(output_name, f"artifact.promotion.{output_name}@1"),),
            ({"external.write": True} if effect == "EXTERNAL_WRITE" else ({"filesystem.write": True} if effect == "WRITE_LOCAL_SANDBOX" else ({"network.read": True} if effect == "EXTERNAL_READ" else {"promotion.effect": effect}))),
            "policy.promotion.approval@1",
            {"purpose": purpose, "scope": ["promotion"], "permissions": ["explicit_publish_approval"] if effect == "EXTERNAL_WRITE" else [], "limitations": ["no hidden evidence", "no credential model context"]},
        )
        descriptor = CapabilityDescriptor(
            capability_id, "1.0", component.ref, f"promotion.{executor_ref}@1", ("deterministic", "http_adapter"),
            (input_name,), (output_name,), ("external.write",) if effect == "EXTERNAL_WRITE" else (("filesystem.write",) if effect == "WRITE_LOCAL_SANDBOX" else ()),
            120.0 if capability_id == "promotion.render_video" else 30.0, "bounded", "HIGH" if effect == "EXTERNAL_WRITE" else "LOW",
            "promotion_v1", {"qualification": "promotion-v1", "production_registry_modified": False}, ("tests/application/promotion",),
            CapabilityLifecycle.CANDIDATE,
        )
        components[component.ref] = component; descriptors.append(descriptor)
    registry = CapabilityRegistry(components)
    for descriptor in descriptors:
        registry.register_candidate(descriptor)
        if descriptor.risk_level != "HIGH":
            registry.admit(descriptor.ref)
    return registry

