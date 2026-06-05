from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

import scripts.agent_conversation_loop as agent_loop
import scripts.dynamic_pipeline_runner as dynamic_runner
import scripts.local_packager as local_packager
import scripts.pipeline_manifest as pipeline_manifest
import scripts.pipeline_planner_agent as planner_agent
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_session(session_dir: pathlib.Path, chat_id: str, summary: str = "做一个本地任务管理器") -> dict:
    session = bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = summary
    session["messages"].append({"role": "user", "text": summary, "created_at": bridge.now()})
    bridge.save_session(session_dir, session)
    bridge.append_agent_session_event(session_dir, chat_id, {"kind": "user", "role": "user", "text": summary})
    return session


def package_result(project_dir: pathlib.Path) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    manifest = local_packager.package_project(project_dir)
    return {
        "status": manifest["status"],
        "manifest": manifest,
        "manifest_path": manifest["manifest_path"],
        "package_path": manifest["package_path"],
    }


class AgentGeneratedPipelineTests(unittest.TestCase):
    def test_pipeline_planner_falls_back_to_default_manifest(self) -> None:
        original = planner_agent.check_connectivity._resolve_api_credentials
        planner_agent.check_connectivity._resolve_api_credentials = lambda: {"api_key": ""}
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
                agent_loop.append_event(session_path, {"kind": "user", "role": "user", "text": "做一个 CLI 工具"})
                manifest = planner_agent.plan_pipeline(session_path, {"project_summary": "做一个 CLI 工具"}, "gpt-test", 5)
        finally:
            planner_agent.check_connectivity._resolve_api_credentials = original

        self.assertEqual("AgentGeneratedPipelineManifest", manifest["kind"])
        self.assertTrue(manifest["roles"])
        self.assertTrue(manifest["steps"])
        self.assertTrue(any(step.get("type") == "package_project" for step in manifest["steps"]))

    def test_pipeline_manifest_validation_rejects_unknown_step_type(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        manifest["steps"][0]["type"] = "execute_python"

        ok, errors = pipeline_manifest.validate_pipeline_manifest(manifest)

        self.assertFalse(ok)
        self.assertTrue(any("execute_python" in error for error in errors))

    def test_dynamic_pipeline_runner_executes_agent_turn_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {
                    "id": "build",
                    "type": "agent_turn",
                    "role": "builder",
                    "goal": "write README",
                    "allowed_actions": ["write_file", "read_file", "list_files"],
                },
                {"id": "package", "type": "package_project", "goal": "package"},
            ]

            def fake_agent(events, model, timeout):
                return {"actions": [{"type": "write_file", "path": "README.md", "content": "# Built\n"}]}

            result = dynamic_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=3,
                agent=fake_agent,
                fallback_to_agent_loop=False,
            )

            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            events = read_jsonl(session_path)
            self.assertTrue(any(event.get("kind") == "pipeline_manifest" for event in events))
            self.assertTrue(any(event.get("kind") == "pipeline_step_result" for event in events))

    def test_run_agent_generation_job_uses_pipeline_planner_before_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            make_session(session_dir, "chat-pipeline")
            client = FakeTelegramClient()
            calls: list[str] = []
            original_plan = bridge.pipeline_planner_agent.plan_pipeline
            original_runner = bridge.dynamic_pipeline_runner.run_dynamic_pipeline
            original_loop = bridge.agent_conversation_loop.run_agent_loop

            def fake_plan(*args, **kwargs):
                calls.append("planner")
                return pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})

            def fake_runner(*, session_path, project_dir, pipeline_manifest, model, timeout, max_turns):
                calls.append("runner")
                return package_result(pathlib.Path(project_dir)) | {"pipeline_manifest": pipeline_manifest, "driver": "agent_generated_pipeline"}

            def forbidden_loop(**kwargs):
                calls.append("old_loop")
                raise AssertionError("old loop should not run before planner and runner")

            bridge.pipeline_planner_agent.plan_pipeline = fake_plan
            bridge.dynamic_pipeline_runner.run_dynamic_pipeline = fake_runner
            bridge.agent_conversation_loop.run_agent_loop = forbidden_loop
            try:
                bridge.run_agent_generation_job(client, "chat-pipeline", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.pipeline_planner_agent.plan_pipeline = original_plan
                bridge.dynamic_pipeline_runner.run_dynamic_pipeline = original_runner
                bridge.agent_conversation_loop.run_agent_loop = original_loop

            self.assertEqual(["planner", "runner"], calls)
            self.assertTrue(client.documents)

    def test_pipeline_runner_fallback_to_agent_loop_on_runner_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            make_session(session_dir, "chat-fallback")
            client = FakeTelegramClient()
            called = {"fallback": False}
            original_plan = bridge.pipeline_planner_agent.plan_pipeline
            original_runner = bridge.dynamic_pipeline_runner.run_dynamic_pipeline
            original_loop = bridge.agent_conversation_loop.run_agent_loop

            bridge.pipeline_planner_agent.plan_pipeline = lambda *args, **kwargs: pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})

            def failing_runner(**kwargs):
                raise RuntimeError("runner exploded")

            def fake_loop(*, session_path, project_dir, model, timeout, max_turns):
                called["fallback"] = True
                return package_result(pathlib.Path(project_dir))

            bridge.dynamic_pipeline_runner.run_dynamic_pipeline = failing_runner
            bridge.agent_conversation_loop.run_agent_loop = fake_loop
            try:
                bridge.run_agent_generation_job(client, "chat-fallback", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.pipeline_planner_agent.plan_pipeline = original_plan
                bridge.dynamic_pipeline_runner.run_dynamic_pipeline = original_runner
                bridge.agent_conversation_loop.run_agent_loop = original_loop

            self.assertTrue(called["fallback"])
            events = read_jsonl(bridge.agent_session_path(session_dir, "chat-fallback"))
            self.assertTrue(any(event.get("kind") == "pipeline_fallback" for event in events))

    def test_pipeline_manifest_is_written_to_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            make_session(session_dir, "chat-manifest")
            client = FakeTelegramClient()
            original_plan = bridge.pipeline_planner_agent.plan_pipeline
            original_runner = bridge.dynamic_pipeline_runner.run_dynamic_pipeline

            bridge.pipeline_planner_agent.plan_pipeline = lambda *args, **kwargs: pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            bridge.dynamic_pipeline_runner.run_dynamic_pipeline = (
                lambda *, session_path, project_dir, pipeline_manifest, model, timeout, max_turns: package_result(pathlib.Path(project_dir))
                | {"pipeline_manifest": pipeline_manifest, "driver": "agent_generated_pipeline"}
            )
            try:
                bridge.run_agent_generation_job(client, "chat-manifest", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.pipeline_planner_agent.plan_pipeline = original_plan
                bridge.dynamic_pipeline_runner.run_dynamic_pipeline = original_runner

            manifest_path = log_dir / "agent_projects" / "chat-manifest" / "pipeline_manifest.json"
            self.assertTrue(manifest_path.exists())
            doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("planner_agent", doc.get("source"))

    def test_pipeline_agents_receive_generation_context_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            agent_loop.append_event(session_path, {"kind": "generation_context_snapshot", "whiteboard": {"project_summary": "demo"}})
            captured: dict[str, list[str]] = {}
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {
                    "id": "build",
                    "type": "agent_turn",
                    "role": "builder",
                    "goal": "write README",
                    "allowed_actions": ["write_file"],
                },
                {"id": "package", "type": "package_project", "goal": "package"},
            ]

            def fake_agent(events, model, timeout):
                captured["kinds"] = [str(event.get("kind")) for event in events]
                return {"actions": [{"type": "write_file", "path": "README.md", "content": "# Context\n"}]}

            dynamic_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=3,
                agent=fake_agent,
                fallback_to_agent_loop=False,
            )

            self.assertIn("generation_context_snapshot", captured["kinds"])
            self.assertIn("pipeline_manifest", captured["kinds"])


if __name__ == "__main__":
    unittest.main()
