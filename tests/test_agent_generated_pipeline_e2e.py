from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.local_packager as local_packager
import scripts.pipeline_manifest as pipeline_manifest
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def simple_manifest() -> dict:
    return {
        "kind": "AgentGeneratedPipelineManifest",
        "version": 1,
        "project_goal": "做一个本地 hello 工具",
        "source": "planner_agent",
        "roles": [
            {"id": "cfo", "name": "CFO", "purpose": "write plans and review delivery evidence"},
            {"id": "builder", "name": "Builder", "purpose": "create the local hello tool"},
            {"id": "qa", "name": "QA", "purpose": "record test evidence"},
        ],
        "shared_whiteboard_keys": ["project_summary", "acceptance_criteria", "default_assumptions"],
        "steps": [
            {
                "id": "plan",
                "type": "agent_turn",
                "stage": ["product_plan", "technical_plan"],
                "role": "cfo",
                "goal": "write PRODUCT_PLAN.md, OUTPUT_CONTRACT.md, TECHNICAL_PLAN.md, and BUILD_PLAN.md",
                "allowed_actions": ["write_file"],
            },
            {
                "id": "build",
                "type": "agent_turn",
                "stage": "build",
                "role": "builder",
                "goal": "write README.md and app.py",
                "allowed_actions": ["write_file"],
            },
            {
                "id": "test",
                "type": "agent_turn",
                "stage": "test",
                "role": "qa",
                "goal": "write TEST_REPORT.md",
                "allowed_actions": ["write_file"],
            },
            {
                "id": "evidence_review",
                "type": "agent_turn",
                "stage": "evidence_review",
                "role": "qa",
                "goal": "write EVIDENCE_REVIEW.md",
                "allowed_actions": ["write_file"],
            },
            {
                "id": "review",
                "type": "agent_turn",
                "stage": "review",
                "role": "cfo",
                "goal": "write DELIVERY_NOTES.md",
                "allowed_actions": ["write_file"],
            },
            {"id": "package", "type": "package_project", "stage": "package", "goal": "package delivery"},
        ],
        "limits": {"max_agent_turns_per_step": 2, "max_total_steps": 6, "allow_dynamic_new_steps": False},
    }


class AgentGeneratedPipelineE2ETests(unittest.TestCase):
    def test_telegram_generation_uses_agent_generated_pipeline_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            original_thread = bridge.threading.Thread
            original_income = bridge.start_generation_from_income
            original_plan = bridge.pipeline_planner_agent.plan_pipeline
            original_step_agent = bridge.dynamic_pipeline_runner._call_step_provider

            def fake_step_agent(events, model, timeout):
                prompt = str(events[0].get("content", ""))
                if "Current step goal: write PRODUCT_PLAN.md" in prompt:
                    return {
                        "actions": [
                            {"type": "write_file", "path": "PRODUCT_PLAN.md", "content": "# Product Plan\n\nBuild a hello CLI.\n"},
                            {"type": "write_file", "path": "OUTPUT_CONTRACT.md", "content": "# Output Contract\n\nZip with runnable CLI.\n"},
                            {"type": "write_file", "path": "TECHNICAL_PLAN.md", "content": "# Technical Plan\n\nUse Python.\n"},
                            {"type": "write_file", "path": "BUILD_PLAN.md", "content": "# Build Plan\n\nCreate README and app.py.\n"},
                        ]
                    }
                if "Current step goal: write TEST_REPORT.md" in prompt:
                    return {"actions": [{"type": "write_file", "path": "TEST_REPORT.md", "content": "# Test Report\n\ncommands_run:\n- python app.py\n\nresults:\n- planned fixture\n\nfailures:\n- none\n\nrepairs:\n- none\n\nremaining_warnings:\n- not executed in fixture\n"}]}
                if "Current step goal: write EVIDENCE_REVIEW.md" in prompt:
                    return {"actions": [{"type": "write_file", "path": "EVIDENCE_REVIEW.md", "content": "# Evidence Review\n\ntest_code_files: none\ntest_commands: python app.py\nsample_inputs: none\nscreenshots: none\nvideos: none\npreview_files: none\nwhat_user_should_check: CLI output\nmissing_real_evidence: no visual media required\nnext_recommended_action: package\n"}]}
                if "Current step goal: write DELIVERY_NOTES.md" in prompt:
                    return {"actions": [{"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Delivery Notes\n\ndelivery_status: WARNING\ntests_executed: fixture evidence\nevidence_found: README, app.py, TEST_REPORT.md\nevidence_missing: none\nknown_limits: fixture did not execute command\nrevision_entry: initial\n"}]}
                return {
                    "actions": [
                        {"type": "write_file", "path": "README.md", "content": "# Hello Tool\n\nRun `python app.py`.\n"},
                        {"type": "write_file", "path": "app.py", "content": "print('hello from CGNK')\n"},
                    ]
                }

            try:
                bridge.threading.Thread = InlineThread
                bridge.start_generation_from_income = lambda *args, **kwargs: False
                bridge.pipeline_planner_agent.plan_pipeline = lambda *args, **kwargs: simple_manifest()
                bridge.dynamic_pipeline_runner._call_step_provider = fake_step_agent

                bridge.handle_text(client, "chat-e2e-pipeline", "做一个本地 hello 工具", session_dir, log_dir, "gpt-test", 5)
                bridge.handle_text(client, "chat-e2e-pipeline", "开始生成", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.threading.Thread = original_thread
                bridge.start_generation_from_income = original_income
                bridge.pipeline_planner_agent.plan_pipeline = original_plan
                bridge.dynamic_pipeline_runner._call_step_provider = original_step_agent

            project_dir = log_dir / "agent_projects" / "chat-e2e-pipeline"
            session = bridge.load_session(session_dir, "chat-e2e-pipeline")
            events = read_jsonl(bridge.agent_session_path(session_dir, "chat-e2e-pipeline"))

            self.assertTrue(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
            self.assertTrue(any(event.get("kind") == "pipeline_manifest" for event in events))
            self.assertTrue(any(event.get("kind") == "pipeline_step_result" for event in events))
            self.assertEqual("agent_generated_pipeline", session["generation"]["driver"])
            self.assertTrue((project_dir / "PRODUCT_PLAN.md").exists())
            self.assertTrue((project_dir / "README.md").exists())
            self.assertTrue((project_dir / "app.py").exists())
            self.assertTrue((project_dir / "generation_context_snapshot.json").exists())
            self.assertTrue((project_dir / "pipeline_run_summary.json").exists())

    def test_dynamic_pipeline_failure_records_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            original_thread = bridge.threading.Thread
            original_income = bridge.start_generation_from_income
            original_plan = bridge.pipeline_planner_agent.plan_pipeline
            original_runner = bridge.dynamic_pipeline_runner.run_dynamic_pipeline
            original_loop = bridge.agent_conversation_loop.run_agent_loop

            def fake_loop(*, session_path, project_dir, model, timeout, max_turns):
                project = pathlib.Path(project_dir)
                project.mkdir(parents=True, exist_ok=True)
                (project / "README.md").write_text("# Fallback\n", encoding="utf-8")
                (project / "app.py").write_text("print('fallback')\n", encoding="utf-8")
                (project / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python app.py\n", encoding="utf-8")
                (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: WARNING\n", encoding="utf-8")
                manifest = local_packager.package_project(project, startup_command="python app.py")
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            try:
                bridge.threading.Thread = InlineThread
                bridge.start_generation_from_income = lambda *args, **kwargs: False
                bridge.pipeline_planner_agent.plan_pipeline = lambda *args, **kwargs: simple_manifest()
                bridge.dynamic_pipeline_runner.run_dynamic_pipeline = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("runner failed"))
                bridge.agent_conversation_loop.run_agent_loop = fake_loop

                bridge.handle_text(client, "chat-fallback-e2e", "做一个本地 hello 工具", session_dir, log_dir, "gpt-test", 5)
                bridge.handle_text(client, "chat-fallback-e2e", "开始生成", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.threading.Thread = original_thread
                bridge.start_generation_from_income = original_income
                bridge.pipeline_planner_agent.plan_pipeline = original_plan
                bridge.dynamic_pipeline_runner.run_dynamic_pipeline = original_runner
                bridge.agent_conversation_loop.run_agent_loop = original_loop

            session = bridge.load_session(session_dir, "chat-fallback-e2e")
            events = read_jsonl(bridge.agent_session_path(session_dir, "chat-fallback-e2e"))

            self.assertTrue(any(event.get("kind") == "pipeline_fallback" for event in events))
            self.assertTrue(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
            self.assertEqual("agent_conversation_loop_fallback", session["generation"]["driver"])

    def test_pipeline_manifest_cannot_use_legacy_paths(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        manifest["steps"] = [
            {
                "id": "legacy",
                "type": "run_command",
                "goal": "call legacy path",
                "command": "python scripts/generate_project.py && python scripts/run_local_pipeline.py",
            }
        ]

        ok, errors = pipeline_manifest.validate_pipeline_manifest(manifest)

        self.assertFalse(ok)
        self.assertTrue(any("legacy generation paths" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
