from __future__ import annotations

from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec


_CAPABILITIES = (
    ("persona.read_state", "persona_query", "persona_projection", "read", "Read a bounded Persona state projection."),
    ("persona.retrieve_context", "persona_context_query", "persona_action_context", "context", "Select relevant Persona references without replacing Knowledge retrieval."),
    ("persona.build_situation", "public_interaction", "social_situation", "situation", "Classify role, authority, history, and social risk."),
    ("persona.decide_attention", "social_situation", "attention_decision", "attention", "Choose act, wait, ignore, follow-up, commitment, or review."),
    ("persona.reflect", "reflection_request", "reflection_candidate", "reflect", "Produce a bounded evidence-backed derived reflection candidate."),
    ("persona.record_experience", "experience_evidence", "persona_state_receipt", "record", "Reference an observed experience and issue a state receipt."),
    ("persona.social_rehearsal", "public_draft", "social_rehearsal", "simulate", "Run advisory synthetic-role risk rehearsal."),
)


def build_persona_registry() -> CapabilityRegistry:
    components = {}; descriptors = []
    for capability_id, input_name, output_name, executor_name, purpose in _CAPABILITIES:
        component = ComponentSpec(capability_id, "1.0", (PortSpec(input_name, f"artifact.persona.{input_name}@1"),),
                                  (PortSpec(output_name, f"artifact.persona.{output_name}@1"),),
                                  {"persona.effect": "PURE_OR_LOCAL_STATE"}, "policy.persona.governed-state@1",
                                  {"purpose": purpose, "scope": ["persona"], "permissions": [],
                                   "limitations": ["no external write", "no second knowledge authority", "no identity mutation", "evidence references only"]})
        descriptor = CapabilityDescriptor(capability_id, "1.0", component.ref, f"persona.{executor_name}@1",
                                          ("deterministic", "cheap_llm_optional"), (input_name,), (output_name,), (), 30.0,
                                          "localized", "LOW", "persona_v1", {"qualification": "persona-v1", "external_write": False},
                                          ("tests/application/persona",), CapabilityLifecycle.CANDIDATE)
        components[component.ref] = component; descriptors.append(descriptor)
    registry = CapabilityRegistry(components)
    for descriptor in descriptors:
        registry.register_candidate(descriptor); registry.admit(descriptor.ref)
    return registry
