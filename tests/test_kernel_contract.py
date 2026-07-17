from __future__ import annotations

import pathlib
import re
import os
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
    def test_kernel_contract_preserves_provider_pass_checkpoints(self) -> None:
        contract = read_source("docs/00_kernel_contract.md")

        self.assertIn("PASS checkpoints", contract)
        self.assertIn("Failed attempts use separate diagnostics", contract)

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

    def test_generation_confirmation_only_dispatches_generation_starter(self) -> None:
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

    def test_soft_questions_do_not_prevent_auto_start(self) -> None:
        analysis = {
            "needs_direction_confirmation": False,
            "soft_questions": ["第一版按本地网页可以吗？"],
            "critical_questions": [],
            "missing_required_inputs": [],
            "confidence": 0.95,
        }

        self.assertEqual((False, "unclear_project_request"), bridge.should_auto_start_generation({}, analysis, "做一个系统"))
        self.assertEqual((True, "actionable_project_request"), bridge.should_auto_start_generation({}, analysis, "做一个本地工具，可以整理和导出报告"))
        self.assertEqual((True, "explicit_start_requested"), bridge.should_auto_start_generation({}, analysis, "按默认假设开始生成"))

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

    def test_telegram_default_generation_uses_provider_route_with_gate(self) -> None:
        source = read_source("scripts/telegram_live_bridge.py")
        start = function_body(source, "start_agent_generation")
        agent_job = function_body(source, "run_agent_generation_job")
        provider_job = function_body(source, "run_provider_generation_job") + function_body(source, "run_provider_execute_with_retries")

        self.assertIn('"driver": "api_provider_project_generation"', start)
        self.assertIn("target=run_provider_generation_job", start)
        self.assertNotIn("target=run_agent_generation_job", start)
        self.assertIn("pipeline_planner_agent.plan_pipeline", agent_job)
        self.assertIn("dynamic_pipeline_runner.run_dynamic_pipeline", agent_job)
        self.assertIn("finish_agent_loop_delivery", agent_job)
        self.assertIn("provider_project_pipeline.execute", provider_job)
        self.assertIn("api-provider-project-generated", provider_job)
        self.assertIn("provider-output-validated", provider_job)
        self.assertIn("provider-project-files-written", provider_job)
        self.assertIn("runtime-artifacts-written", provider_job)
        self.assertIn("local_packager.package_project", provider_job)
        self.assertIn("evaluate_public_delivery_gate", provider_job)
        self.assertIn("provider_success_artifact_audit", provider_job)
        self.assertIn("mark_public_delivery_rework", provider_job)
        self.assertIn("finish_agent_loop_delivery", provider_job)

    def test_support_pipeline_manifest_required_before_dynamic_runner(self) -> None:
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

    def test_final_delivery_recomputes_canonical_package_without_mutating_manifest(self) -> None:
        bridge_source = read_source("scripts/telegram_live_bridge.py")
        packager_source = read_source("scripts/local_packager.py")
        canonical_source = read_source("scripts/canonical_delivery_manifest.py")
        gate = function_body(bridge_source, "evaluate_public_delivery_gate")
        sender = function_body(bridge_source, "send_delivery_from_manifest")

        self.assertIn("canonical_delivery_manifest.build_canonical_package", packager_source)
        self.assertIn("inspect_canonical_delivery_manifest", gate)
        self.assertIn("inspect_canonical_delivery_manifest", sender)
        self.assertNotIn("write_json(manifest_path, manifest)", sender)
        self.assertIn("package_approval", sender)
        self.assertIn("package_changed_before_send", bridge_source)
        self.assertIn("visual_required=browser_visual_required", bridge_source)
        self.assertIn("media_required=media_evidence_required", bridge_source)
        self.assertIn("candidate_source_hash", canonical_source)
        self.assertIn("inspect_zip_entries", canonical_source)
        self.assertIn("RESERVED_FIELDS", canonical_source)
        self.assertIn("evidence_changed_during_packaging", canonical_source)
        self.assertIn('canonical_json_hash(manifest, ("artifact_hash",))', canonical_source)

    def test_user_review_is_candidate_bound_canonical_evidence(self) -> None:
        review_source = read_source("scripts/canonical_user_review.py")
        bridge_source = read_source("scripts/telegram_live_bridge.py")
        packager_source = read_source("scripts/canonical_delivery_manifest.py")
        contract = read_source("docs/00_kernel_contract.md")

        self.assertIn("record_user_review_approval", review_source)
        self.assertIn("inspect_user_review_evidence", review_source)
        self.assertIn("from_user_id", bridge_source)
        self.assertIn("message_context", bridge_source)
        self.assertIn("user_review_required", packager_source)
        self.assertIn("session booleans and text substrings are not review truth", contract)

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
        router_source = read_source("scripts/local_model_router.py")

        self.assertIn("local models do not create a new formal generation path", doc)
        self.assertIn("CGNK_AUTO_START_OLLAMA", doc)
        self.assertIn("Auto-starting Ollama does not enable additional tasks", doc)
        self.assertIn("pipeline_manifest", doc)
        self.assertIn("local_packager", doc)
        self.assertIn("Public reply tasks must not alter", doc)
        self.assertIn("ensure_ollama_running", router_source)
        self.assertTrue(local_model_router.task_is_public_reply_only("customer_public_reply"))
        self.assertFalse(local_model_router.task_affects_generation("customer_public_reply"))
        self.assertTrue(local_model_router.task_affects_generation("context_support"))
        self.assertTrue(local_model_router.task_affects_generation("risk_support"))
        self.assertFalse(local_model_router.DEFAULT_LOCAL_TASKS & local_model_router.LOCAL_GENERATION_TASKS)
        self.assertGreater(local_model_router.local_model_temperature("customer_public_reply"), 0.5)
        self.assertEqual(0.1, local_model_router.local_model_temperature("cfo_pipeline"))

    def test_ollama_auto_start_can_be_disabled_without_enabling_generation_tasks(self) -> None:
        original_auto_start = os.environ.get("CGNK_AUTO_START_OLLAMA")
        original_available = local_model_router.ollama_available
        try:
            os.environ["CGNK_AUTO_START_OLLAMA"] = "0"
            local_model_router.ollama_available = lambda host: False
            runtime = local_model_router.ensure_ollama_running("http://127.0.0.1:11434", wait_seconds=1)
        finally:
            local_model_router.ollama_available = original_available
            if original_auto_start is None:
                os.environ.pop("CGNK_AUTO_START_OLLAMA", None)
            else:
                os.environ["CGNK_AUTO_START_OLLAMA"] = original_auto_start

        self.assertFalse(runtime["ok"])
        self.assertEqual("disabled", runtime["status"])
        self.assertFalse(local_model_router.DEFAULT_LOCAL_TASKS & local_model_router.LOCAL_GENERATION_TASKS)

    def test_public_delivery_gate_receipt_and_final_verdict_are_part_of_kernel_contract(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        bridge_source = read_source("scripts/telegram_live_bridge.py")
        send_manifest = function_body(bridge_source, "send_delivery_from_manifest")
        send_checkpoint = function_body(bridge_source, "send_evidence_checkpoint")

        self.assertIn("canonical test/runtime/visual evidence", doc)
        self.assertIn("public_delivery_gate", doc)
        self.assertIn("delivery_receipt", doc)
        self.assertIn("final_verdict.json", doc)
        self.assertIn("PASS_WITH_LIMITS", doc)
        self.assertIn("BLOCKED_*", doc)
        self.assertIn("NO TEST EXECUTED", doc)
        self.assertIn("any_zip_found", doc)
        self.assertIn("final_package_exists", doc)
        self.assertIn("must not mark final delivery as delivered until", doc)
        self.assertIn("PUBLIC_DELIVERY_SUFFIXES", bridge_source)
        self.assertIn("evaluate_public_delivery_gate", send_manifest)
        self.assertIn("evaluate_public_delivery_gate", send_checkpoint)
        self.assertIn("emit_public_delivery", send_manifest)
        self.assertIn("emit_public_delivery", send_checkpoint)

    def test_build_qa_and_checkpoint_rework_are_part_of_kernel_contract(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        runner = read_source("scripts/dynamic_pipeline_runner.py")
        bridge_source = read_source("scripts/telegram_live_bridge.py")

        self.assertIn("app.py` or `main.py`", doc)
        self.assertIn("requirements.txt", doc)
        self.assertIn("pipeline_step_result.status=rework_blocked", doc)
        self.assertIn("NO TEST EXECUTED", doc)
        self.assertIn("`NOT_EVALUATED` is non-final", doc)
        self.assertIn("_build_completion_audit", runner)
        self.assertIn("_qa_completion_audit", runner)
        self.assertIn('"status": "rework_blocked"', runner)
        self.assertIn('"status": "rework_blocked"', bridge_source)

    def test_public_narration_is_expression_layer_only(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        bridge = read_source("scripts/telegram_live_bridge.py")

        self.assertIn("Public narration is allowed only at Telegram reply boundaries", doc)
        self.assertIn("does not create a new formal generation path", doc)
        self.assertIn("public_narration", bridge)
        self.assertIn("pipeline_manifest", doc)
        self.assertIn("dynamic_pipeline_runner", doc)
        self.assertIn("local_packager", doc)

    def test_malformed_agent_json_recovery_stays_inside_manifest_step(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        runner = read_source("scripts/dynamic_pipeline_runner.py")
        parser = read_source("scripts/agent_conversation_loop.py")

        self.assertIn("recover complete actions from malformed or truncated agent JSON", doc)
        self.assertIn("_salvage_complete_write_file_actions", parser)
        self.assertIn("partially recovered from malformed JSON", runner)
        self.assertIn("same manifest step must return strict JSON", runner)

    def test_local_project_team_layer_is_state_only(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")

        self.assertIn("Local Project Team Layer", doc)
        self.assertIn("do not create a second formal generation path", doc)
        self.assertIn("failed revision", doc)
        self.assertIn("model_policy", doc)

    def test_simulator_and_media_evidence_cannot_fake_delivery(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        bridge_source = read_source("scripts/telegram_live_bridge.py")
        packager_source = read_source("scripts/local_packager.py")

        self.assertIn("preflight-only", doc)
        self.assertIn("never generating fallback media", doc)
        self.assertIn("run_simulator_preflight", bridge_source)
        self.assertNotIn("create_fallback_generated_asset", bridge_source)
        self.assertIn("build_canonical_package", packager_source)
        self.assertIn('"inclusion_manifest"', read_source("scripts/canonical_delivery_manifest.py"))
        self.assertIn('"startup_entrypoint"', packager_source)


if __name__ == "__main__":
    unittest.main()
