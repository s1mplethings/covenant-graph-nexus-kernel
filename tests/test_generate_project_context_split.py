from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.generate_project as generate_project


class GenerateProjectContextSplitTests(unittest.TestCase):
    def test_raw_requirement_drives_composition_and_execution(self) -> None:
        requirement = "做一个本地日志分析工具，上传日志文件后生成统计报告。"
        enriched = "CGNK_CONTEXT_PROMPT requirement_blueprint internal planning context"
        slug = "unit-context-split"
        calls: dict[str, str] = {}

        original_build = generate_project.build_enriched_goal
        original_compose = generate_project.compose_local_pipeline.compose
        original_execute = generate_project.run_local_pipeline.execute
        try:
            generate_project.build_enriched_goal = lambda *args, **kwargs: (enriched, {"quality": {"status": "pass"}, "budget": {}})

            def fake_compose(goal: str, **kwargs: object) -> dict[str, object]:
                calls["compose_goal"] = goal
                return {
                    "kind": "LocalPipelineCompositionRun",
                    "goal": goal,
                    "pipeline_plan": {"payload": {"requirement": goal}},
                }

            def fake_execute(ns: argparse.Namespace) -> dict[str, object]:
                calls["execute_goal"] = str(ns.goal)
                plan = json.loads(pathlib.Path(ns.plan).read_text(encoding="utf-8"))
                calls["internal_context_prompt"] = str(plan.get("internal_context_prompt", ""))
                return {
                    "kind": "RuntimeExecutionResult",
                    "status": "pass",
                    "project_dir": str(ROOT / "generated" / slug),
                    "run_dir": str(ROOT / "examples" / "runtime_runs" / slug),
                }

            generate_project.compose_local_pipeline.compose = fake_compose
            generate_project.run_local_pipeline.execute = fake_execute
            result_path = ROOT / "examples" / "test_results" / f"{slug}_result.json"
            args = argparse.Namespace(
                requirement=requirement,
                project_slug=slug,
                prompt_max_chars=12000,
                allow_network=False,
                allow_provider=False,
                use_api=False,
                use_local_model=False,
                model="unused",
                timeout=60,
                result_path=str(result_path),
                allow_model_usage_planning=False,
            )

            result = generate_project.run_generation(args)

            self.assertEqual("pass", result["status"])
            self.assertEqual(requirement, calls["compose_goal"])
            self.assertEqual(requirement, calls["execute_goal"])
            self.assertEqual(enriched, calls["internal_context_prompt"])
        finally:
            generate_project.build_enriched_goal = original_build
            generate_project.compose_local_pipeline.compose = original_compose
            generate_project.run_local_pipeline.execute = original_execute
            shutil.rmtree(ROOT / "examples" / "runtime_runs" / slug, ignore_errors=True)
            shutil.rmtree(ROOT / "generated" / slug, ignore_errors=True)
            for suffix in ("_composition.json", "_execution.json", "_requirement_blueprint.json", "_context_prompt.json", "_result.json"):
                (ROOT / "examples" / "test_results" / f"{slug}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
