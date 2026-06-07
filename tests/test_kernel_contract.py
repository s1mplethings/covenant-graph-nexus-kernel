from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.pipeline_manifest as pipeline_manifest
import scripts.local_model_router as local_model_router
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))


def read_source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def function_body(text: str, name: str) -> str:
    match = re.search(rf"^def\s+{re.escape(name)}\s*\(", text, flags=re.M)
    if not match:
        return ""
    next_match = re.search(r"^def\s+\w+\s*\(", text[match.end() :], flags=re.M)
    if not next_match:
        return text[match.start() :]
    return text[match.start() : match.end() + next_match.start()]


def generation_confirmation_branch(text: str) -> str:
    match = re.search(r'if\s+intent\s*==\s*"generation_confirmation"\s*:', text)
    if not match:
        return ""
    end = re.search(r'^\s*if\s+intent\s*==\s*"escalation_request"\s*:', text[match.end() :], flags=re.M)
    if not end:
        return text[match.start() :]
    return text[match.start() : match.end() + end.start()]


class KernelContractTests(unittest.TestCase):
    def test_kernel_contract_checker_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/kernel_contract_check.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout.splitlines()[0])

    def test_generation_confirmation_does_not_use_legacy_pipeline(self) -> None:
        branch = generation_confirmation_branch(read_source("scripts/telegram_live_bridge.py"))

        self.assertTrue(branch)
        for forbidden in ("generate_project.py", "run_local_pipeline", "simulator", "run_generation_subprocess"):
            self.assertNotIn(forbidden, branch)

    def test_soft_questions_are_not_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            original_start = bridge.start_agent_generation
            original_memory = bridge.DEFAULT_MEMORY_DIR
            called: dict[str, object] = {}

            def fake_start(client, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["chat_id"] = str(chat_id)
                called["announce_start"] = announce_start

            try:
                bridge.DEFAULT_MEMORY_DIR = root / "memory"
                session = bridge.default_session("chat-soft")
                session["whiteboard"]["project_summary"] = "做一个本地知识库"
                session["whiteboard"]["soft_questions"] = ["是否需要导出 CSV？"]
                bridge.save_session(session_dir, session)
                bridge.start_agent_generation = fake_start

                bridge.handle_text(FakeTelegramClient(), "chat-soft", "开始生成", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.start_agent_generation = original_start
                bridge.DEFAULT_MEMORY_DIR = original_memory

            self.assertEqual("chat-soft", called.get("chat_id"))
            self.assertFalse(called.get("announce_start"))

    def test_critical_questions_are_not_gate_but_are_acceptance_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            original_start = bridge.start_agent_generation
            original_memory = bridge.DEFAULT_MEMORY_DIR
            called: dict[str, object] = {}

            def fake_start(client, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["chat_id"] = str(chat_id)
                called["announce_start"] = announce_start

            try:
                bridge.DEFAULT_MEMORY_DIR = root / "memory"
                session = bridge.default_session("chat-critical")
                session["whiteboard"]["project_summary"] = "做一个本地 VN 助手"
                session["whiteboard"]["critical_questions"] = ["本地模型或外部 API 配置在哪里？"]
                session["whiteboard"]["acceptance_criteria"] = ["降级预览不算核心能力验收通过"]
                bridge.save_session(session_dir, session)
                bridge.start_agent_generation = fake_start

                bridge.handle_text(FakeTelegramClient(), "chat-critical", "开始生成", session_dir, log_dir, "gpt-test", 5)
            finally:
                bridge.start_agent_generation = original_start
                bridge.DEFAULT_MEMORY_DIR = original_memory

            self.assertEqual("chat-critical", called.get("chat_id"))
            doc = read_source("docs/00_kernel_contract.md")
            self.assertIn("critical_questions", doc)
            self.assertIn("fallback output is not misreported", doc)
            universal = read_source("docs/07_universal_capability_strategy_contract.md")
            self.assertIn("not tied to a project type", universal)
            self.assertIn("Do not add project-type-specific rules", universal)
            self.assertIn("underlying capabilities", universal)
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
            self.assertIn("capability_strategy", manifest["shared_whiteboard_keys"])
            self.assertIn("capability_research_targets", manifest["shared_whiteboard_keys"])

    def test_pipeline_manifest_required_before_dynamic_runner(self) -> None:
        body = function_body(read_source("scripts/telegram_live_bridge.py"), "run_agent_generation_job")

        planner_index = body.find("pipeline_planner_agent.plan_pipeline")
        write_index = body.find("write_pipeline_manifest")
        runner_index = body.find("dynamic_pipeline_runner.run_dynamic_pipeline")
        self.assertGreaterEqual(planner_index, 0)
        self.assertGreater(write_index, planner_index)
        self.assertGreater(runner_index, write_index)

    def test_backend_controls_log_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_memory = bridge.DEFAULT_MEMORY_DIR
            try:
                bridge.DEFAULT_MEMORY_DIR = pathlib.Path(temp_dir) / "memory"
                session_dir = pathlib.Path(temp_dir) / "sessions"
                session = bridge.default_session("chat-control")

                control = bridge.append_backend_control(session_dir, session, "start_generation", payload={"x": 1})
            finally:
                bridge.DEFAULT_MEMORY_DIR = original_memory

        self.assertEqual("BackendControlLog", control["kind"])
        self.assertTrue(control["log_only"])
        self.assertEqual("logged", control["status"])

    def test_packager_is_only_delivery_exit(self) -> None:
        text = read_source("scripts/telegram_live_bridge.py")
        finish = function_body(text, "finish_agent_loop_delivery")
        evidence = function_body(text, "delivery_evidence_state")

        self.assertIn("manifest_path", finish)
        self.assertIn("package_path", finish)
        self.assertIn("send_delivery_from_manifest", finish)
        self.assertIn("package", evidence)
        self.assertNotIn("final_message", finish)
        self.assertNotIn("final_message", evidence)

    def test_kernel_contract_defines_cfo_module_plan(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})

        self.assertIn("CFO-controlled", doc)
        self.assertIn("CFO support agents only inside the manifest", doc)
        self.assertEqual("cfo", manifest["roles"][0]["id"])
        self.assertEqual("cfo_pipeline", manifest["steps"][0]["id"])
        self.assertEqual("context_support", manifest["steps"][1]["id"])
        self.assertEqual("risk_support", manifest["steps"][2]["id"])
        self.assertEqual("CFO_CONTEXT_DB.json", manifest["cfo_contract"]["support_artifacts"]["context_db"])
        self.assertEqual("CFO_RISK_REGISTER.md", manifest["cfo_contract"]["support_artifacts"]["risk_register"])
        self.assertIn("cfo_review", [step["id"] for step in manifest["steps"]])

    def test_local_model_routing_is_not_formal_generation_path(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")

        self.assertIn("local models do not create a new formal generation path", doc)
        self.assertIn("pipeline_manifest", doc)
        self.assertIn("local_packager", doc)
        self.assertIn("Public reply tasks must not alter", doc)
        self.assertTrue(local_model_router.task_is_public_reply_only("customer_public_reply"))
        self.assertFalse(local_model_router.task_affects_generation("customer_public_reply"))
        self.assertTrue(local_model_router.task_affects_generation("context_support"))
        self.assertTrue(local_model_router.task_affects_generation("risk_support"))
        self.assertFalse(local_model_router.DEFAULT_LOCAL_TASKS & local_model_router.LOCAL_GENERATION_TASKS)
        self.assertGreater(local_model_router.local_model_temperature("customer_public_reply"), 0.5)
        self.assertEqual(0.1, local_model_router.local_model_temperature("cfo_pipeline"))

    def test_malformed_agent_json_recovery_stays_inside_manifest_step(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        runner = read_source("scripts/dynamic_pipeline_runner.py")
        parser = read_source("scripts/agent_conversation_loop.py")

        self.assertIn("recover complete actions from malformed or truncated agent JSON", doc)
        self.assertIn("_salvage_complete_write_file_actions", parser)
        self.assertIn("partially recovered from malformed JSON", runner)
        self.assertIn("same manifest step must return strict JSON", runner)


if __name__ == "__main__":
    unittest.main()
