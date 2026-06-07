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
    def test_default_manifest_uses_cfo_controlled_module_pipeline(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})

        role_ids = [role["id"] for role in manifest["roles"]]
        step_ids = [step["id"] for step in manifest["steps"]]
        self.assertEqual("cfo", role_ids[0])
        self.assertIn("context_librarian", role_ids)
        self.assertIn("risk_reviewer", role_ids)
        self.assertIn("backend", role_ids)
        self.assertIn("frontend", role_ids)
        self.assertEqual("cfo_pipeline", step_ids[0])
        self.assertEqual("context_support", step_ids[1])
        self.assertEqual("risk_support", step_ids[2])
        self.assertIn("cfo_review", step_ids)
        self.assertEqual("package", step_ids[-1])
        self.assertEqual(4, manifest["limits"]["max_agent_turns_per_step"])
        self.assertEqual(10, manifest["limits"]["max_total_steps"])
        self.assertEqual("MODULE_PIPELINE.md", manifest["cfo_contract"]["planning_artifact"])
        self.assertEqual("DELIVERY_NOTES.md", manifest["cfo_contract"]["review_artifact"])
        self.assertEqual("CFO_CONTEXT_DB.json", manifest["cfo_contract"]["support_artifacts"]["context_db"])
        self.assertEqual("CFO_RISK_REGISTER.md", manifest["cfo_contract"]["support_artifacts"]["risk_register"])

    def test_cfo_system_prompt_contains_orchestration_rules(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        cfo_role = manifest["roles"][0]
        cfo_step = manifest["steps"][0]

        prompt = dynamic_runner._system_prompt(cfo_role, cfo_step, manifest)

        self.assertIn("CFO operating rules", prompt)
        self.assertIn("MODULE_PIPELINE.md", prompt)
        self.assertIn("DELIVERY_NOTES.md", prompt)
        self.assertIn("CFO_CONTEXT_DB.json", prompt)
        self.assertIn("CFO_RISK_REGISTER.md", prompt)
        self.assertIn("main coordinating agent", prompt)

    def test_support_agent_system_prompt_is_advisory_only(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        role = next(role for role in manifest["roles"] if role["id"] == "context_librarian")
        step = next(step for step in manifest["steps"] if step["id"] == "context_support")

        prompt = dynamic_runner._system_prompt(role, step, manifest)

        self.assertIn("CFO support operating rules", prompt)
        self.assertIn("CFO_CONTEXT_DB.json", prompt)
        self.assertIn("not a route owner", prompt)
        self.assertIn("Do not implement product features", prompt)

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

    def test_pipeline_planner_can_use_local_model_before_api(self) -> None:
        original_local_call = planner_agent.local_model_router.call_json_task
        original_creds = planner_agent.check_connectivity._resolve_api_credentials
        try:
            local_manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            local_manifest["source"] = "local_model_test"
            planner_agent.local_model_router.call_json_task = lambda *args, **kwargs: {
                "ok": True,
                "provider": "test-local",
                "json": local_manifest,
            }
            planner_agent.check_connectivity._resolve_api_credentials = lambda: (_ for _ in ()).throw(AssertionError("api should not be needed"))

            with tempfile.TemporaryDirectory() as temp_dir:
                session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
                manifest = planner_agent.plan_pipeline(session_path, {"project_summary": "demo"}, "gpt-real", 5)
        finally:
            planner_agent.local_model_router.call_json_task = original_local_call
            planner_agent.check_connectivity._resolve_api_credentials = original_creds

        self.assertEqual("local_model_test", manifest["source"])
        self.assertEqual("cfo", manifest["roles"][0]["id"])

    def test_pipeline_manifest_validation_rejects_unknown_step_type(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        manifest["steps"][0]["type"] = "execute_python"

        ok, errors = pipeline_manifest.validate_pipeline_manifest(manifest)

        self.assertFalse(ok)
        self.assertTrue(any("execute_python" in error for error in errors))

    def test_normalize_manifest_preserves_cfo_support_contract(self) -> None:
        raw = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        raw["cfo_contract"]["support_artifacts"]["context_db"] = "CUSTOM_CONTEXT_DB.json"
        raw["cfo_contract"]["support_agent_rule"] = "support stays advisory"

        normalized = pipeline_manifest.normalize_pipeline_manifest(raw, {"project_summary": "demo"})

        self.assertEqual("CUSTOM_CONTEXT_DB.json", normalized["cfo_contract"]["support_artifacts"]["context_db"])
        self.assertEqual("support stays advisory", normalized["cfo_contract"]["support_agent_rule"])

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
                    "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                    "role": "foundation",
                    "goal": "write README",
                    "allowed_actions": ["write_file", "read_file", "list_files"],
                },
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
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
                skip_user_evidence_checkpoint=True,
            )

            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            events = read_jsonl(session_path)
            self.assertTrue(any(event.get("kind") == "pipeline_manifest" for event in events))
            self.assertTrue(any(event.get("kind") == "pipeline_step_result" for event in events))

    def test_dynamic_pipeline_runner_uses_local_model_for_cfo_pipeline_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {**manifest["steps"][0], "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"]},
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
            ]
            original_local_call = dynamic_runner.local_model_router.call_text_task
            original_provider = dynamic_runner._call_step_provider
            try:
                dynamic_runner.local_model_router.call_text_task = lambda *args, **kwargs: {
                    "ok": True,
                    "provider": "test-local",
                    "text": json.dumps({"actions": [{"type": "write_file", "path": "MODULE_PIPELINE.md", "content": "# Plan\n"}]}),
                }
                dynamic_runner._call_step_provider = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be needed"))

                result = dynamic_runner.run_dynamic_pipeline(
                    session_path=session_path,
                    project_dir=project_dir,
                    pipeline_manifest=manifest,
                    model="gpt-real",
                    timeout=5,
                    max_turns=2,
                    fallback_to_agent_loop=False,
                    skip_user_evidence_checkpoint=True,
                )
            finally:
                dynamic_runner.local_model_router.call_text_task = original_local_call
                dynamic_runner._call_step_provider = original_provider

            self.assertTrue((project_dir / "MODULE_PIPELINE.md").exists())
            self.assertTrue(pathlib.Path(result["package_path"]).exists())

    def test_dynamic_pipeline_runner_retries_malformed_agent_json_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {
                    "id": "build",
                    "type": "agent_turn",
                    "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                    "role": "foundation",
                    "goal": "write README",
                    "allowed_actions": ["write_file"],
                },
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
            ]
            calls = {"count": 0}

            def fake_agent(events, model, timeout):
                calls["count"] += 1
                if calls["count"] == 1:
                    return '{"message":"bad","actions":[{"type":"write_file","path":"README.md"}'
                return {"actions": [{"type": "write_file", "path": "README.md", "content": "# Recovered\n"}]}

            result = dynamic_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=3,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                skip_user_evidence_checkpoint=True,
            )

            events = read_jsonl(session_path)
            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            self.assertGreaterEqual(calls["count"], 2)
            self.assertFalse(any(event.get("kind") == "pipeline_fallback" for event in events))
            self.assertTrue(any("malformed JSON" in str(event.get("error", "")) for event in events))

    def test_dynamic_pipeline_runner_salvages_truncated_write_file_then_repairs_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {
                    "id": "backend",
                    "type": "agent_turn",
                    "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                    "role": "backend",
                    "goal": "write backend",
                    "allowed_actions": ["write_file"],
                },
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
            ]
            calls = {"count": 0}

            def fake_agent(events, model, timeout):
                calls["count"] += 1
                if calls["count"] == 1:
                    return (
                        '{"message":"partial","actions":['
                        '{"type":"write_file","path":"backend/app.py","content":"print(\\"ok\\")\\n"},'
                        '{"type":"write_file","path":"HANDOFF_BACKEND.md","content":"# cut'
                    )
                return {"actions": [{"type": "write_file", "path": "HANDOFF_BACKEND.md", "content": "# Backend\n"}]}

            result = dynamic_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=3,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                skip_user_evidence_checkpoint=True,
            )

            events = read_jsonl(session_path)
            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            self.assertEqual('print("ok")\n', (project_dir / "backend" / "app.py").read_text(encoding="utf-8"))
            self.assertEqual("# Backend\n", (project_dir / "HANDOFF_BACKEND.md").read_text(encoding="utf-8"))
            self.assertEqual(2, calls["count"])
            self.assertFalse(any(event.get("kind") == "pipeline_fallback" for event in events))
            self.assertTrue(any("partially recovered" in str(event.get("error", "")) for event in events))

    def test_dynamic_pipeline_runner_rejects_invalid_json_artifact_before_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            manifest["steps"] = [
                {
                    "id": "context_support",
                    "type": "agent_turn",
                    "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                    "role": "context_librarian",
                    "goal": "write context db",
                    "allowed_actions": ["write_file"],
                },
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
            ]
            calls = {"count": 0}

            def fake_agent(events, model, timeout):
                calls["count"] += 1
                if calls["count"] == 1:
                    return {"actions": [{"type": "write_file", "path": "CFO_CONTEXT_DB.json", "content": '{"project_goal":"demo",,'}]}
                return {
                    "actions": [
                        {"type": "write_file", "path": "CFO_CONTEXT_DB.json", "content": '{"project_goal":"demo"}'},
                        {"type": "write_file", "path": "README.md", "content": "# Demo\n"},
                    ]
                }

            result = dynamic_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=3,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                skip_user_evidence_checkpoint=True,
            )

            events = read_jsonl(session_path)
            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            self.assertEqual('{"project_goal":"demo"}', (project_dir / "CFO_CONTEXT_DB.json").read_text(encoding="utf-8"))
            self.assertTrue(any("JSON content is invalid" in str(event) for event in events))

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

            def fake_runner(*, session_path, project_dir, pipeline_manifest, model, timeout, max_turns, **kwargs):
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
                    "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                    "role": "foundation",
                    "goal": "write README",
                    "allowed_actions": ["write_file"],
                },
                {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
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
                skip_user_evidence_checkpoint=True,
            )

            self.assertIn("generation_context_snapshot", captured["kinds"])
            self.assertIn("pipeline_manifest", captured["kinds"])


if __name__ == "__main__":
    unittest.main()
