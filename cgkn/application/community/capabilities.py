from __future__ import annotations

from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec


COMMUNITY_CAPABILITIES = (
    ("community.discover", "scan_plan", "community_threads", "discover", "EXTERNAL_READ", "Discover bounded public discussion candidates."),
    ("community.read_thread", "thread_ref", "community_thread", "read-thread", "EXTERNAL_READ", "Read bounded target, parent, and relevant thread context."),
    ("community.rank_opportunity", "community_thread", "community_opportunity", "rank", "PURE", "Rank ability-to-help and participation value."),
    ("community.decide_engagement", "community_opportunity", "engagement_decision", "decide", "PURE", "Separate engagement, project mention, and link decisions."),
    ("community.prepare_context", "engagement_decision", "reply_context", "context", "PURE", "Prepare bounded untrusted thread and approved evidence context."),
    ("community.draft_reply", "reply_context", "reply_draft", "draft", "PURE", "Draft a technical, transparent, non-salesy reply."),
    ("community.validate_reply", "reply_draft", "reply_validation", "validate", "PURE", "Validate policy, standalone value, claims, disclosure, and spam risk."),
    ("community.plan_reply", "reply_draft", "reply_approval", "plan", "PURE", "Bind an exact reply revision to human approval."),
    ("community.publish_reply", "reply_approval", "community_reply_receipt", "publish", "EXTERNAL_WRITE", "Publish an explicitly approved reply through a qualified official adapter."),
    ("community.fetch_followups", "community_reply_receipt", "follow_up_state", "followups", "EXTERNAL_READ", "Read direct responses and moderation events."),
    ("community.fetch_metrics", "community_reply_receipt", "community_metrics", "metrics", "EXTERNAL_READ", "Fetch public aggregate reply metrics."),
)


def build_community_registry() -> CapabilityRegistry:
    components: dict[str, ComponentSpec] = {}
    descriptors: list[CapabilityDescriptor] = []
    for capability_id, input_name, output_name, executor_ref, effect, purpose in COMMUNITY_CAPABILITIES:
        if effect == "EXTERNAL_WRITE":
            declared = {"external.write": True}
            effects = ("external.write",)
            risk = "HIGH"
        elif effect == "EXTERNAL_READ":
            declared = {"network.read": True}
            effects = ("network.read",)
            risk = "MEDIUM"
        else:
            declared = {"community.effect": "PURE"}
            effects = ()
            risk = "LOW"
        component = ComponentSpec(
            capability_id, "1.0",
            (PortSpec(input_name, f"artifact.community.{input_name}@1"),),
            (PortSpec(output_name, f"artifact.community.{output_name}@1"),),
            declared, "policy.community.reply-approval@1",
            {
                "purpose": purpose,
                "scope": ["community"],
                "permissions": ["APPROVED_TO_REPLY"] if effect == "EXTERNAL_WRITE" else [],
                "limitations": ["untrusted thread data", "no hidden evidence", "no credentials in executor context", "no private messages", "no likes or votes"],
            },
        )
        descriptor = CapabilityDescriptor(
            capability_id, "1.0", component.ref, f"community.{executor_ref}@1",
            ("deterministic", "http_adapter", "cheap_llm"), (input_name,), (output_name,), effects,
            30.0, "bounded", risk, "community_v1",
            {"qualification": "community-v1", "production_registry_modified": False, "external_write_guarded": effect == "EXTERNAL_WRITE"},
            ("tests/application/community",), CapabilityLifecycle.CANDIDATE,
        )
        components[component.ref] = component
        descriptors.append(descriptor)
    registry = CapabilityRegistry(components)
    for descriptor in descriptors:
        registry.register_candidate(descriptor)
        if descriptor.risk_level != "HIGH":
            registry.admit(descriptor.ref)
    return registry

