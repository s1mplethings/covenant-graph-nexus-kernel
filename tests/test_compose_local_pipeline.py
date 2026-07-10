from __future__ import annotations

import pathlib
import sys
import unittest

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.compose_local_pipeline as compose_local_pipeline

pytestmark = [pytest.mark.slow, pytest.mark.e2e]


class ComposeLocalPipelineTests(unittest.TestCase):
    def test_full_agent_route_compiles_without_unbound_control_inputs(self) -> None:
        result = compose_local_pipeline.compose(
            "Need customer intake, requirement blueprint, local librarian, online library sources, feature library search, "
            "local agent planning, adversarial review, project generation, test graph, effect report, checkpoint, "
            "context pack, and unified control running together",
            allow_network=True,
            allow_provider=True,
        )
        payload = result["pipeline_plan"]["payload"]
        selected = payload["selected_modules"]
        for ref in [
            "module.conversation.reduce@1",
            "module.customer.service@1",
            "module.requirement_blueprint.generator@1",
            "module.local.librarian@1",
            "module.online.library_sources@1",
            "module.feature.library_search@1",
            "module.local_agent.plan@1",
            "module.adversarial_generation@1",
            "module.project.generator@1",
            "module.test_graph.emit@1",
            "module.effect_report.emit@1",
            "module.generation_checkpoint.commit@1",
            "module.context_pack.build@1",
            "module.unified_control@1",
        ]:
            self.assertIn(ref, selected)
        self.assertEqual("pass", payload["route_quality_report"]["route_compile_status"])
        self.assertEqual([], payload["route_quality_report"]["unbound_inputs"])

    def test_local_model_manages_component_routing_when_available(self) -> None:
        original_hint = compose_local_pipeline.optional_local_model_hint
        try:
            compose_local_pipeline.optional_local_model_hint = lambda *args, **kwargs: {
                "enabled": True,
                "provider": "command",
                "model": "unit-local-router",
                "ok": True,
                "result": {
                    "selected_modules": [
                        "module.customer.service@1",
                        "module.local.librarian@1",
                        "module.local_agent.plan@1",
                        "module.project.generator@1",
                        "module.test_graph.emit@1",
                        "module.effect_report.emit@1",
                        "module.unified_control@1",
                    ],
                    "librarian_notes": "Use local assets and existing project-generation modules.",
                    "route_notes": "Split VN work by timeline, model config, and visual evidence.",
                    "phase_routing": [
                        {
                            "id": "timeline",
                            "label": "Timeline editor",
                            "active_module": "module.project.generator@1",
                            "depends_on": [],
                            "outputs": ["timeline_ui", "node_model"],
                            "path_hints": ["src/**", "static/**"],
                            "prompt_max_chars": 3200,
                            "agent_focus": "Build story graph editing first.",
                            "acceptance_gate": ["User can create and link timeline nodes."],
                            "handoff_notes": ["Pass node schema to image workflow."],
                        },
                        {
                            "id": "local-image-model",
                            "label": "Local image model integration",
                            "active_module": "module.project.generator@1",
                            "depends_on": ["timeline"],
                            "outputs": ["background_generator", "sprite_generator"],
                            "path_hints": ["src/**", "assets/**"],
                            "prompt_max_chars": 4200,
                            "agent_focus": "Keep background and sprite generation separate.",
                            "acceptance_gate": ["Separate capability checks exist for background and sprite routes."],
                            "handoff_notes": ["Pass generated asset manifest to verification."],
                        },
                    ],
                    "delivery_gates": ["timeline demo", "image preview artifact"],
                    "evidence_requirements": ["screenshot", "generated image preview"],
                    "retry_policy": {"retry_scope": "failed_component_only", "max_repair_notes": 3},
                    "risks": ["local image server may be missing"],
                },
            }

            result = compose_local_pipeline.compose("本地 VN 项目助手，时间线，背景和立绘分开生成", use_local_model=True)
        finally:
            compose_local_pipeline.optional_local_model_hint = original_hint

        payload = result["pipeline_plan"]["payload"]
        management = payload["local_agent_management"]
        component_pipeline = payload["component_pipeline"]

        self.assertEqual("local_model", management["source"])
        self.assertEqual("local_model_managed_component_routing", component_pipeline["strategy"])
        self.assertEqual(["timeline", "local-image-model"], component_pipeline["execution_order"])
        self.assertEqual("Timeline editor", component_pipeline["components"][0]["label"])
        self.assertIn("image preview artifact", management["delivery_gates"])
        self.assertIn("local_agent_manager", result["project_understanding"]["payload"]["route_manager"]["local_model_scope"])


if __name__ == "__main__":
    unittest.main()
