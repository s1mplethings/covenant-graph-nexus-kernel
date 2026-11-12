from __future__ import annotations
import pytest

import unittest

from cgkn.agent.capability_registry import (ProjectContext, RegistryEntry,
                                            SharedCapabilityRegistry)


def entry(capability_id="media.technical_acceptance", origin="ACFV"):
    return RegistryEntry(
        capability_id=capability_id, version="1", implementation_ref="deterministic:media_acceptance",
        input_contract=("video_path", "require_audio"), output_contract=("acceptance_receipt",),
        effects=("read",), origin_project=origin, provenance={"run": "p1-continuation"},
        reuse_conditions=("generic media file",), known_limitations=("technical only",),
        evidence_summary=("P1 PASS",), generic_responsibility=True)


class ProjectIsolationTests(unittest.TestCase):
    def test_tree_versions_are_independent(self):
        acfv = ProjectContext("ACFV", "media", 7, node_states={"accept": "VERIFIED"})
        character = ProjectContext("CharacterCut", "character clips", 1, node_states={"clip": "VERIFIED"})
        character.assert_no_inheritance_from(acfv)
        self.assertNotEqual(acfv.tree_version, character.tree_version)

    def test_acceptance_does_not_leak(self):
        acfv = ProjectContext("ACFV", "media", 7, acceptance={"R-release": "PASS"})
        character = ProjectContext("CharacterCut", "character clips", 1)
        self.assertNotIn("R-release", character.acceptance)
        self.assertEqual(character.acceptance, {})

    def test_budget_does_not_leak(self):
        character = ProjectContext("CharacterCut", "character clips", 1,
                                   budget={"state": "BLOCKED", "spent_cny": 40.0})
        persona = ProjectContext("DigitalPersona", "persona", 1,
                                 budget={"state": "OK", "spent_cny": 0.0})
        self.assertEqual(persona.budget["state"], "OK")
        self.assertNotEqual(character.budget["state"], persona.budget["state"])

    def test_unknown_does_not_leak(self):
        character = ProjectContext("CharacterCut", "character clips", 1,
                                   unknown={"provider": "PROVIDER_OUTCOME_UNKNOWN"})
        persona = ProjectContext("DigitalPersona", "persona", 1)
        self.assertEqual(persona.unknown, {})
        self.assertNotIn("provider", persona.unknown)

    @pytest.mark.happy_path
    @pytest.mark.boundary
    def test_shared_capability_bind_execute_local_verify(self):
        registry = SharedCapabilityRegistry()
        ok, code, _ = registry.admit_candidate(entry())
        self.assertTrue(ok, code)
        binding = registry.bind(project_id="CharacterCut", project_node_id="clip.policy",
                                capability_id="media.technical_acceptance", version="1",
                                local_consumer="character.clip.policy",
                                local_context={"input": "collection.mp4"},
                                verification_scope=("p2/collection_acceptance.json",),
                                consumer_inputs=("video_path", "require_audio"))
        passed, reason = registry.verify_binding(binding, ("p2/collection_acceptance.json",))
        self.assertTrue(passed, reason)

    def test_context_mismatch_requires_adapter(self):
        registry = SharedCapabilityRegistry()
        registry.admit_candidate(entry())
        with self.assertRaisesRegex(ValueError, "ADAPTER_REQUIRED"):
            registry.bind(project_id="DigitalPersona", project_node_id="upload",
                          capability_id="media.technical_acceptance", version="1",
                          local_consumer="persona.upload",
                          local_context={}, verification_scope=("p3/upload.json",),
                          consumer_inputs=("video_path", "persona_text"))

    @pytest.mark.negative
    @pytest.mark.boundary
    def test_foreign_project_pass_cannot_be_local_pass(self):
        registry = SharedCapabilityRegistry()
        registry.admit_candidate(entry())
        binding = registry.bind(project_id="DigitalPersona", project_node_id="media",
                                capability_id="media.technical_acceptance", version="1",
                                local_consumer="persona.video",
                                local_context={}, verification_scope=("p3/acceptance.json",),
                                consumer_inputs=("video_path", "require_audio"))
        passed, reason = registry.verify_binding(
            binding, ("p3/acceptance.json",),
            foreign_project_pass_refs=("acfv/run-01/P1_ACCEPTANCE.json",))
        self.assertTrue(passed, reason)
        passed, reason = registry.verify_binding(
            binding, ("acfv/run-01/P1_ACCEPTANCE.json",),
            foreign_project_pass_refs=("acfv/run-01/P1_ACCEPTANCE.json",))
        self.assertFalse(passed)
        self.assertEqual(reason, "FOREIGN_PROJECT_ACCEPTANCE_CANNOT_BE_PROJECT_PASS")

    def test_registry_rejects_non_generic_or_missing_effects(self):
        registry = SharedCapabilityRegistry()
        bad = RegistryEntry("character.twilight.identity", "1", "model:x",
                            ("frame",), ("identity",), (), "CharacterCut", {}, ("twilight only",),
                            generic_responsibility=False)
        ok, code, details = registry.admit_candidate(bad)
        self.assertFalse(ok)
        self.assertEqual(code, "REJECTED")
        self.assertTrue(any("generic" in reason or "effects" in reason for reason in details["reasons"]))

    def test_tree_identity_mismatch_rejected_when_sharing_version_and_nodes(self):
        a = ProjectContext("ACFV", "media", 7, node_states={"n": "VERIFIED"})
        b = ProjectContext("CharacterCut", "character", 7, node_states={"n": "VERIFIED"})
        with self.assertRaisesRegex(ValueError, "PROJECT_TREE_IDENTITY_MISMATCH"):
            b.assert_no_inheritance_from(a)


if __name__ == "__main__":
    unittest.main()
