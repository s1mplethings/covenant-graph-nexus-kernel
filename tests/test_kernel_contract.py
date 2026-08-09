from __future__ import annotations

import json
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

    def test_production_candidate_provenance_is_frozen_before_canonical_evidence(self) -> None:
        source = read_source("scripts/telegram_live_bridge.py")
        finalize = function_body(source, "post_build_finalize_provider_project")
        contract = read_source("docs/00_kernel_contract.md")

        provenance_index = finalize.find("production_candidate_provenance.produce")
        test_index = finalize.find("run_provider_project_tests(", provenance_index)
        runtime_index = finalize.find("customer_runtime_runner.run", provenance_index)
        self.assertGreaterEqual(provenance_index, 0)
        self.assertGreater(test_index, provenance_index)
        self.assertGreater(runtime_index, provenance_index)
        self.assertIn("CGKNProductionCandidateProvenance", contract)
        self.assertIn("Session/context booleans", contract)
        self.assertIn("short-circuits canonical evidence inspection", contract)

    def test_provider_response_is_staged_and_causally_applied_before_evidence(self) -> None:
        source = read_source("scripts/telegram_live_bridge.py")
        provider_job = function_body(source, "run_provider_generation_job")
        finalize = function_body(source, "post_build_finalize_provider_project")
        contract = read_source("docs/00_kernel_contract.md")

        self.assertIn("provider_response_staging", provider_job)
        self.assertIn("out_dir=str(provider_staging_dir)", provider_job)
        self.assertIn("provider_causal_trace.begin_provider_request", provider_job)
        self.assertIn("provider_causal_trace.consume_provider_response", provider_job)
        self.assertIn("provider_causal_trace.finalize", finalize)
        self.assertLess(
            provider_job.find("provider_causal_trace.begin_provider_request"),
            provider_job.find("run_provider_execute_with_retries"),
        )
        self.assertLess(
            provider_job.find("provider_causal_trace.consume_provider_response"),
            provider_job.find("validate_provider_generation_output"),
        )
        self.assertIn("CGKNProviderCausalTrace", contract)
        self.assertIn("direct provider writes to the final candidate cannot substitute", contract)

    def test_candidate_hash_prunes_excluded_environment_directories(self) -> None:
        source = read_source("scripts/canonical_evidence_hash.py")
        contract = read_source("docs/00_kernel_contract.md")

        iterator = function_body(source, "iter_candidate_source_files")
        self.assertIn("os.walk(project, followlinks=False)", iterator)
        self.assertIn("ROOT_TOOL_DIRS", iterator)
        self.assertIn("ANY_DEPTH_CACHE_DIRS", iterator)
        self.assertIn(".cgkn_test_env", contract)
        self.assertIn("must not be recursively scanned", contract)

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
        pipeline_source = read_source("scripts/run_local_pipeline_impl.py")
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
        self.assertIn("def validate_frontend_dom_contract", pipeline_source)
        self.assertIn("def javascript_import_specifiers", pipeline_source)
        self.assertIn("frontend DOM contract mismatch", pipeline_source)
        self.assertIn("def validate_task_board_interaction_contract", pipeline_source)
        self.assertIn("task-board interaction contract mismatch", pipeline_source)
        self.assertIn("def validate_javascript_const_reassignment", pipeline_source)
        self.assertIn("provider_result=result", function_body((ROOT / "scripts" / "telegram_live_bridge.py").read_text(encoding="utf-8"), "finish_agent_loop_delivery"))
        self.assertIn('body_text_length") or 0) < 8', pipeline_source)
        self.assertIn('set(doc) == {"component"}', pipeline_source)
        self.assertIn('"num_predict": local_model_num_predict(task, system=system)', read_source("scripts/local_model_router.py"))
        self.assertNotIn("The frontend must use fetch", pipeline_source)
        self.assertIn("def provider_manifest_component_id", pipeline_source)
        self.assertIn("def validate_frontend_asset_contract", pipeline_source)
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
        self.assertIn("canonical_screenshot_path_or_hash_changed", bridge_source)
        self.assertIn("telegram_screenshot_send_failed_or_invalid", bridge_source)
        self.assertIn("normalized successful Telegram returns", contract)

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
        self.assertTrue(local_model_router.task_affects_generation("component_generation"))
        self.assertTrue(local_model_router.task_affects_generation("component_repair"))
        self.assertIn("component_generation", local_model_router.LOCAL_CODE_TASKS)
        self.assertFalse(local_model_router.DEFAULT_LOCAL_TASKS & local_model_router.LOCAL_GENERATION_TASKS)
        self.assertGreater(local_model_router.local_model_temperature("customer_public_reply"), 0.5)
        self.assertEqual(0.1, local_model_router.local_model_temperature("cfo_pipeline"))
        starter = read_source("start_customer_service.py")
        self.assertIn('"hybrid_safe"', starter)
        self.assertIn("HYBRID_SAFE_LOCAL_TASKS", starter)
        self.assertIn("HYBRID_SAFE_API_TASKS", router_source)
        self.assertIn("CGNK_MODEL_ROUTING_PROFILE", starter)
        self.assertIn("CGNK_OLLAMA_CODE_MODEL", starter)
        pipeline_source = read_source("scripts/run_local_pipeline_impl.py")
        pipeline_facade_source = read_source("scripts/run_local_pipeline.py")
        post_build_repair_source = read_source("scripts/post_build_repair.py")
        self.assertIn("local_provider_contract_error", pipeline_source)
        self.assertIn("CGNK_LOCAL_COMPONENT_MAX_PROMPT_CHARS", pipeline_source)
        self.assertIn("component_required_manifest_paths", pipeline_source)
        self.assertIn("CURRENT COMPONENT REQUIRED PATHS (highest precedence)", pipeline_source)
        self.assertIn("required_manifest_paths", pipeline_source)
        self.assertIn("normalize_local_provider_doc", pipeline_source)
        self.assertIn("normalize_provider_doc", pipeline_source)
        self.assertIn("PROJECT_ROOT = SCRIPT_DIR.parent", pipeline_source)
        self.assertIn('("file_manifest", "manifest")', pipeline_source)
        self.assertIn("parse_provider_manifest_doc", pipeline_source)
        self.assertIn("ProviderOutputContractError", pipeline_source)
        self.assertIn("bounded_provider_diagnostic_output", pipeline_source)
        self.assertIn("write_provider_component_failure_attempt", pipeline_source)
        self.assertIn("PROVIDER_OUTPUT_CONTRACT", pipeline_source)
        self.assertIn("component_review_blocker_in_scope", pipeline_source)
        self.assertIn("normalize_semantic_blocker_evidence", pipeline_source)
        self.assertIn("validate_frontend_module_self_import", pipeline_source)
        self.assertIn("without URL query/fragment syntax", pipeline_source)
        self.assertIn("omit console scripts whose target module", pipeline_source)
        self.assertIn('"SimpleHTTPRequestHandler" in backend_source', pipeline_source)
        self.assertIn("Use only the Python standard library at runtime", pipeline_source)
        self.assertIn("query_generation_context_librarian", pipeline_source)
        self.assertNotIn('"prior_component_contract_excerpts":', pipeline_source)
        self.assertIn("component_file_manifest", pipeline_source)
        self.assertIn("local split-file Python syntax invalid", pipeline_source)
        self.assertIn("local task-board HTML missing stable data-testid attributes", pipeline_source)
        self.assertIn("expects_main_function", pipeline_source)
        self.assertIn("local task-board tests do not inspect required generated sources", pipeline_source)
        self.assertIn("Python launcher implementation text in index.html instead of main.py", pipeline_source)
        self.assertIn("For this test repair, read all three exact files", pipeline_source)
        self.assertIn("test_generated_contracts", pipeline_source)
        self.assertIn("every binding that is later assigned with = must be declared with let", pipeline_source)
        self.assertIn("rejected_errors", pipeline_source)
        self.assertIn("component {component_id} generation failed", pipeline_source)
        self.assertIn("references project files absent from supplied context", pipeline_source)
        self.assertIn("requirement_discovery_alignment", pipeline_source)
        self.assertIn("explicit_pipeline_stages_from_goal", pipeline_source)
        self.assertIn("enrich_component_pipeline_with_complexity_contract", pipeline_source)
        self.assertIn("adaptive_project_management_context.enrich_component_pipeline", pipeline_source)
        self.assertIn("component_management_projection", pipeline_source)
        self.assertIn("CGKNAdaptiveProjectManagementContext", doc)
        self.assertIn("CGKNAdaptiveComponentManagementProjection", doc)
        self.assertIn("build_integration_feedforward_snapshot", pipeline_source)
        self.assertIn("CGKNIntegrationFeedforwardSnapshot", pipeline_source)
        self.assertIn("integration_feedforward_checkpoint_hash", pipeline_source)
        self.assertIn("integration_feedforward_snapshot", pipeline_source)
        self.assertIn("compact_integration_feedforward", pipeline_source)
        self.assertIn("build_component_leaf_work_graph", pipeline_source)
        self.assertIn("CGKNComponentLeafWorkGraph", pipeline_source)
        self.assertIn("component_leaf_ready_batches", pipeline_source)
        self.assertIn("component_leaf_downstream_closure", pipeline_source)
        self.assertIn('in {".css", ".scss"}', pipeline_source)
        self.assertIn("expand_component_manifest_submodules", pipeline_source)
        self.assertIn("automatic_test_manifest_submodules", pipeline_source)
        self.assertIn("automatic_manifest_submodules", pipeline_source)
        self.assertIn('source_suffix not in {".py", ".js", ".mjs"}', pipeline_source)
        self.assertIn("provider_auto_submodule_policy", pipeline_source)
        self.assertIn("split_file_manifest_entry_hash", pipeline_source)
        self.assertIn("manifest_entry_sha256", pipeline_source)
        self.assertIn("compatibility_facade", pipeline_source)
        self.assertIn("bounded_submodule", pipeline_source)
        self.assertIn("build_leaf_interface_contract", pipeline_source)
        self.assertIn("CGKNLeafInterfaceContract", pipeline_source)
        self.assertIn("build_project_interface_registry", pipeline_source)
        self.assertIn("CGKNProjectInterfaceRegistry", pipeline_source)
        self.assertIn("build_leaf_boundary_check_receipt", pipeline_source)
        self.assertIn("CGKNLeafBoundaryCheckReceipt", pipeline_source)
        self.assertIn("validate_generated_component_quality", pipeline_source)
        self.assertIn("CGKNGeneratedComponentQualityValidation", pipeline_source)
        self.assertIn("validate_assembled_project_quality", pipeline_source)
        self.assertIn("CGKNAssembledProjectQualityValidation", pipeline_source)
        self.assertIn("component_checkpoint_quality_invalidated", pipeline_source)
        self.assertIn("independent deterministic component quality validation", doc)
        self.assertIn("CGKN_PROVIDER_LEAF_MAX_WORKERS", pipeline_source)
        self.assertIn("CGNK_LOCAL_PROVIDER_LEAF_MAX_WORKERS", pipeline_source)
        self.assertIn("def provider_task_timeout_cap", pipeline_source)
        self.assertIn("hard_cap = 240 if local_generation else api_hard_cap", pipeline_source)
        self.assertIn("cap=provider_component_manifest_timeout_cap()", pipeline_source)
        self.assertIn("provider_component_file_timeout_cap()", pipeline_source)
        self.assertIn("provider_semantic_review_timeout_cap()", pipeline_source)
        self.assertIn('prepared["raw_user_goal"] = user_goal', pipeline_source)
        self.assertIn('prepared["component_pipeline"] = component_pipeline', pipeline_source)
        self.assertNotIn('pending_repair_plan.setdefault("raw_user_goal"', pipeline_source)
        self.assertIn("def local_model_request_timeout", router_source)
        self.assertIn("hard_cap = 240 if generation_task else 120", router_source)
        self.assertNotIn("min(int(timeout), 120)", router_source)
        self.assertIn("build_generation_context_librarian_index", pipeline_source)
        self.assertIn("query_generation_context_librarian", pipeline_source)
        self.assertIn("CGKNGenerationContextLibrarianIndex", pipeline_source)
        self.assertIn("CGKNLibrarianContextPack", pipeline_source)
        self.assertIn("CGKN_PROVIDER_LIBRARIAN_MAX_ITEMS", pipeline_source)
        self.assertIn("CGKN_PROVIDER_LIBRARIAN_MAX_CHARS", pipeline_source)
        self.assertIn("CGKN_PROVIDER_LIBRARIAN_SPLIT_PROMPT_CHARS", pipeline_source)
        self.assertIn("write_generation_librarian_artifacts", pipeline_source)
        self.assertIn("leaf_implementation_depth_contract", pipeline_source)
        self.assertIn("analyze_leaf_implementation_depth", pipeline_source)
        self.assertIn("CGKNLeafImplementationDepthContract", pipeline_source)
        self.assertIn("CGKNLeafImplementationDepthReceipt", pipeline_source)
        self.assertIn("implementation depth contract mismatch", pipeline_source)
        self.assertIn("CGNK_PROVIDER_COMPONENT_MANIFEST_MAX_TOKENS", pipeline_source)
        self.assertIn("CGNK_PROVIDER_COMPONENT_FILE_MAX_TOKENS", pipeline_source)
        self.assertIn("CGKN_PROVIDER_BOUNDED_SUBMODULE_MAX_LINES", pipeline_source)
        self.assertIn("CGKN_PROVIDER_TEST_LEAF_MAX_LINES", pipeline_source)
        self.assertIn("CGKN_PROVIDER_TEST_FIXTURE_MAX_LINES", pipeline_source)
        self.assertIn("project-wide invariants", pipeline_source)
        self.assertIn("three to six focused pytest tests", pipeline_source)
        self.assertIn("raw_user_goal_reference", pipeline_source)
        self.assertIn("component_leaf_attempt_failed", pipeline_source)
        self.assertIn("semantic_repair_escalation", pipeline_source)
        self.assertIn("repair_acceptance", pipeline_source)
        self.assertIn("split file contains placeholder wording", pipeline_source)
        self.assertIn("measured character count rather than a synthetic zero length", doc)
        self.assertIn("HTML measures meaningful semantic/content", doc)
        self.assertIn('suffix == ".html"', pipeline_source)
        self.assertIn("html_semantic_structure_contract", pipeline_source)
        self.assertIn("required_symbol_contract", pipeline_source)
        self.assertIn("CURRENT TARGET SYMBOL CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("CURRENT PYTHON DEPENDENCY API ALLOWLIST (highest precedence)", pipeline_source)
        self.assertIn("Do not invent helper classes", pipeline_source)
        self.assertIn("receiver_bindings", pipeline_source)
        self.assertIn("never move a", pipeline_source)
        self.assertIn("CURRENT REPAIR REJECTION (highest precedence)", pipeline_source)
        self.assertIn("ALL REJECTED CANDIDATE VIOLATIONS", pipeline_source)
        self.assertIn("component_checkpoint_contract_invalidated", pipeline_source)
        self.assertIn("component_manifest_resume_contract_invalidated", pipeline_source)
        self.assertIn("pending_component_leaf_repair_completed", pipeline_source)
        self.assertIn("elif isinstance(node, ast.ImportFrom)", pipeline_source)
        self.assertIn("normalize_test_manifest_dependency_contract", pipeline_source)
        self.assertIn('and child.name.startswith("test_")', pipeline_source)
        self.assertIn("affected_files.update(existing_design_docs)", pipeline_source)
        self.assertIn("CURRENT DESIGN DOCUMENTATION CONTRACT (highest precedence)", pipeline_source)
        self.assertIn('"exact_selected_direction_name": selected_direction_name', pipeline_source)
        self.assertIn('"minimum_distinct_source_urls": 3', pipeline_source)
        self.assertIn("required_anti_copying_statement", pipeline_source)
        self.assertIn("seen_blockers", pipeline_source)
        self.assertIn("owner = legal_owner_for_path(path, pipeline_components)", pipeline_source)
        self.assertIn("Repair the evidenced semantic blocker in this exact file", pipeline_source)
        self.assertIn('raw_files = blocker.get("files_hint", [])', pipeline_source)
        self.assertIn("structured_blockers or blockers", pipeline_source)
        self.assertIn("CURRENT STAGE ARTIFACT SCHEMA CONTRACT (highest precedence)", pipeline_source)
        self.assertIn('"required_fields_exact": required_artifact_fields', pipeline_source)
        self.assertIn("do not store opaque bytes only", pipeline_source)
        self.assertIn("stage artifact schema contract mismatch", pipeline_source)
        self.assertIn("ArtifactStore still stores opaque bytes", pipeline_source)
        self.assertIn("artifact documentation contains a pass-only example", pipeline_source)
        self.assertIn("CURRENT PYTHON LOCAL IMPORT CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("Librarian source excerpts are context, not import permission", pipeline_source)
        self.assertIn("normalize_executable_media_manifest_contract", pipeline_source)
        self.assertIn("CURRENT EXECUTABLE MEDIA CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("capture workflow does not verify the adapter-written PNG", pipeline_source)
        self.assertIn("does not validate the PNG signature", pipeline_source)
        self.assertIn("raise ValueError('invalid PNG signature')", pipeline_source)
        self.assertIn("Path.write_text(json.dumps(...), encoding='utf-8')", pipeline_source)
        self.assertIn("offline PNG generator has no concrete PNG write operation", pipeline_source)
        self.assertIn("Capture validation is based on written-byte evidence", doc)
        self.assertIn("required_constant_name", pipeline_source)
        self.assertIn("REQUIRED_STAGE_ARTIFACTS", pipeline_source)
        self.assertIn("startup = initialize_app()", pipeline_source)
        self.assertIn("Do not construct or reference ProjectOrchestrator", pipeline_source)
        self.assertIn('re.fullmatch(r"test_[A-Za-z0-9_]+"', pipeline_source)
        self.assertIn('nested_pending = pending.get("repair_plan")', pipeline_source)
        self.assertIn("executable media contract mismatch", pipeline_source)
        self.assertIn("media workflow still simulates image success", pipeline_source)
        self.assertIn("executable_media_contract_incomplete", pipeline_source)
        self.assertIn("offline image adapter does not implement real background", pipeline_source)
        self.assertIn("normalize_backend_stage_dependency_contract", pipeline_source)
        self.assertIn('"main.py": ["backend/orchestrator.py", "backend/stages.py"]', pipeline_source)
        self.assertIn('"backend/story_graph.py": []', pipeline_source)
        self.assertIn('"backend/stages.py": [', pipeline_source)
        self.assertIn('"backend/orchestrator.py": ["backend/stages.py", "backend/artifact_store.py"]', pipeline_source)
        self.assertIn("CURRENT MEDIA RUNTIME DEPENDENCY CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("media runtime dependency contract mismatch", pipeline_source)
        self.assertIn("PIL is imported but the Pillow distribution is absent", pipeline_source)
        self.assertIn("semantic_resume_upstream_components", pipeline_source)
        self.assertNotIn("or semantic_resume_goal_matches\n                or component_id in resume_upstream_components", pipeline_source)
        self.assertIn("CURRENT STAGE CALLABLE EXECUTION CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("orchestrator calls stage.execute(state)", pipeline_source)
        self.assertIn("demo/run_fixture.py has no __main__ execution guard", pipeline_source)
        self.assertIn('entry["expected_symbols"] = ["initialize_app"]', pipeline_source)
        self.assertIn('normalized.setdefault("component_id", component)', pipeline_source)
        self.assertIn("CURRENT UNIFORM STAGE CALLABLE CONTRACT (highest precedence)", pipeline_source)
        self.assertIn("uniform stage callable contract mismatch", pipeline_source)
        self.assertIn("must accept exactly one state parameter", pipeline_source)
        self.assertIn("returns state instead of a stage result", pipeline_source)
        self.assertIn("constructs ProjectOrchestrator with an empty or opaque stage graph", pipeline_source)
        self.assertIn("uses unsafe dynamic execution", pipeline_source)
        self.assertIn("constructor-injected local class types", pipeline_source)
        self.assertIn('"contract mismatch",', pipeline_source)
        self.assertIn("pyproject TOML contract mismatch", pipeline_source)
        self.assertIn('"toml_syntax",', pipeline_source)
        self.assertIn("has invalid TOML syntax", pipeline_source)
        self.assertIn("cached component current contract validation failed", pipeline_source)
        self.assertIn('required_paths.extend(["backend/stages.py", "backend/orchestrator.py"])', pipeline_source)
        self.assertIn('entry["expected_symbols"] = ["ProjectOrchestrator"]', pipeline_source)
        self.assertIn("overrides any different historical name", pipeline_source)
        self.assertIn("CURRENT TARGET IMPLEMENTATION DEPTH (mandatory)", pipeline_source)
        self.assertIn("one-statement save/load/preview wrappers are rejected", pipeline_source)
        self.assertIn("Repair the current consumer leaf", pipeline_source)
        self.assertIn("do not create or regenerate an upstream component", pipeline_source)
        self.assertIn("pending_semantic_repair_plan_refreshed", pipeline_source)
        self.assertIn("repair_plan_refreshed_on_resume", pipeline_source)
        self.assertIn("semantic_resume_goal_matches", pipeline_source)
        self.assertIn("allow_spec_mismatch=bool(recover_manifest_from_checkpoints)", pipeline_source)
        self.assertIn("javascript_local_import_contract", pipeline_source)
        self.assertIn("frontend_dom_binding_contract", pipeline_source)
        self.assertIn("EXACT DOM BINDING CONTRACT", pipeline_source)
        self.assertIn("testid_to_element_id", pipeline_source)
        self.assertIn("EXACT EXISTING CONTROL BINDINGS", pipeline_source)
        self.assertIn('"imports missing local modules"', pipeline_source)
        self.assertIn('"frontend module self-import contract mismatch"', pipeline_source)
        self.assertIn("HTTP or server-rendered adapter contract", pipeline_source)
        self.assertNotIn("Use the backend shared-core API", pipeline_source)
        self.assertIn("prepare_semantic_repair_retry_plan", pipeline_source)
        self.assertIn("repair_target_files_for_component", pipeline_source)
        self.assertIn("generation_safety_target_nonblank_lines", pipeline_source)
        self.assertIn("component_reasoning_repair", pipeline_source)
        self.assertIn("component_reasoning_repair", router_source)
        self.assertIn('"component_reasoning_repair",\n    "foundation",', router_source)
        self.assertIn("configuration_syntax_failure", post_build_repair_source)
        self.assertIn("stage_artifact_failure", post_build_repair_source)
        self.assertIn("media_generation_failure", post_build_repair_source)
        self.assertIn("target_limit = 5", post_build_repair_source)
        self.assertIn("provider_required_failure_types", post_build_repair_source)
        self.assertIn('provider_actions[:target_limit]', post_build_repair_source)
        self.assertIn('finalize_result.get("fixture_result", {})', post_build_repair_source)
        self.assertIn("run_generated_project_fixture", pipeline_source)
        self.assertIn("CGKNGeneratedProjectFixtureReceipt", pipeline_source)
        self.assertIn("fixture produced fewer than four decoder-valid PNG files", pipeline_source)
        self.assertIn("real_fixture_png_file", pipeline_source)
        self.assertIn("the screenshot geometry threshold must not reject valid square sprites", doc)
        self.assertIn("python_test_dependency_context", post_build_repair_source)
        self.assertIn("exact_dependency_context", post_build_repair_source)
        self.assertIn("following facade re-exports", doc)
        self.assertIn("candidate_ui_domain_keywords", pipeline_source)
        self.assertIn("never applies a fixed sample-domain vocabulary", doc)
        self.assertIn("validated_existing_candidate_video", pipeline_source)
        self.assertIn("must not erase earlier valid evidence", doc)
        self.assertIn("candidate_ui_capability_groups", pipeline_source)
        self.assertIn("required_capabilities_missing", pipeline_source)
        self.assertIn("browser evidence must prove a real workspace", doc)
        self.assertIn("ui_quality_failure", post_build_repair_source)
        self.assertIn("accepted_sibling_replacements", post_build_repair_source)
        self.assertIn("pipeline_fallback", pipeline_source)
        self.assertIn("provider_code_fallback_reason", pipeline_source)
        self.assertIn("call_text_task_fallback", router_source)
        self.assertIn("does not change configured ownership", doc)
        self.assertIn("generated_frontend_workspace_source_violations", post_build_repair_source)
        self.assertIn("ui_acceptance_contract", post_build_repair_source)
        self.assertIn("UI diagnostics are isolated", doc)
        self.assertIn("ui_repair_brief", post_build_repair_source)
        self.assertIn("may not return the existing shell unchanged", doc)
        self.assertIn("required_javascript_behaviors", post_build_repair_source)
        self.assertIn("accepted_dom_ids", post_build_repair_source)
        self.assertIn("paired with concrete local behaviors", doc)
        self.assertIn("rejected_replacement_content", post_build_repair_source)
        self.assertIn("preserves already-satisfied UI behaviors", doc)
        self.assertIn("stagnation_detected", post_build_repair_source)
        self.assertIn("ownership-normalized rejected replacement", doc)
        self.assertIn("latest_rejected_repair_feedback", post_build_repair_source)
        self.assertIn("prior_rejected_leaf_revalidated", post_build_repair_source)
        self.assertIn("required_body_identity_line", post_build_repair_source)
        self.assertIn("run librarian may retrieve", doc)
        self.assertIn("post_build_rejections", post_build_repair_source)
        self.assertIn("cannot authorize a PASS", doc)
        self.assertIn("discard_existing_shell", post_build_repair_source)
        self.assertIn("JavaScript workspace leaf must not import itself", post_build_repair_source)
        self.assertIn("discards its old shell content", doc)
        self.assertIn("HTML must load the modular src/app.js owner", post_build_repair_source)
        self.assertIn("must preserve modular ownership", doc)
        self.assertIn("normalize_ui_repair_html_ownership", post_build_repair_source)
        self.assertIn("ownership normalization never creates", doc)
        self.assertIn("minimum_concrete_css_rules", post_build_repair_source)
        self.assertIn("Source-boundary feedback must be executable", doc)
        self.assertIn("post_build_candidate_review_ready", post_build_repair_source)
        self.assertIn("cannot promote review readiness", doc)
        self.assertIn('"domain_keywords": keywords', pipeline_source)
        self.assertIn("HTML body has", post_build_repair_source)
        self.assertIn("console.log as workspace behavior", post_build_repair_source)
        self.assertIn("source and browser acceptance use the same visible-body", doc)
        self.assertIn("frontend_repair_set_violations", post_build_repair_source)
        self.assertIn("workspace_visual_density_too_low", pipeline_source)
        self.assertIn("undersized_control_count", pipeline_source)
        self.assertIn("oversized_media_count", pipeline_source)
        self.assertIn('"screenshot_evidence_unavailable"', pipeline_source)
        self.assertIn("loss of visual evidence cannot silently disable", doc)
        self.assertIn("Browser design diagnostics also measure", doc)
        self.assertIn("ui_semantic_adapter", post_build_repair_source)
        self.assertIn("pipeline_fallback", post_build_repair_source)
        self.assertNotIn("Game Team Task and Bug Dashboard", post_build_repair_source)
        self.assertNotIn("def repair_page_blank_demo_ui", post_build_repair_source)
        self.assertNotIn('{"action": "repair_page_blank_demo_ui"', post_build_repair_source)
        self.assertIn("legacy fixed-domain scaffold actions are not allowed", post_build_repair_source)
        self.assertIn("Do not substitute a sample product or fixed-domain scaffold", pipeline_source)
        self.assertIn("workspace regions containing only headings/buttons", post_build_repair_source)
        self.assertIn("CSS selectors cover only", post_build_repair_source)
        self.assertIn("blocking browser modal behavior", post_build_repair_source)
        self.assertIn('"required_region_content": region_content_contract', post_build_repair_source)
        self.assertIn('"maximum_heading_button_only_regions": 1', post_build_repair_source)
        self.assertNotIn('"story graph edit and validation"', post_build_repair_source)
        self.assertIn("HTML contains duplicate DOM ids", post_build_repair_source)
        self.assertIn("frontend_dom_action_contract", post_build_repair_source)
        self.assertIn("frontend_css_selector_contract", post_build_repair_source)
        self.assertIn("accepted_css_selector_contract", post_build_repair_source)
        self.assertIn("frontend_stagnation_escape_contract", post_build_repair_source)
        self.assertIn("apply_frontend_repair_librarian_slice", post_build_repair_source)
        self.assertIn("CGKNPostBuildFrontendLibrarianSlice", post_build_repair_source)
        self.assertIn("frontend_repair_validation_distance", post_build_repair_source)
        self.assertIn("better_rejected_candidate_retained", post_build_repair_source)
        self.assertIn("closest_rejected_candidate", post_build_repair_source)
        self.assertIn('"single_source": True', post_build_repair_source)
        self.assertIn("rejected_replacement_content_ref", post_build_repair_source)
        self.assertIn("normalized_prior_content", post_build_repair_source)
        self.assertIn("required_visual_asset_properties", post_build_repair_source)
        self.assertIn("preview_surface_selectors", post_build_repair_source)
        self.assertIn("retargeted_invalid_canvas_html_write_to_output_interface", read_source("scripts/ui_semantic_adapter.py"))
        self.assertIn("canvas preview ids that JavaScript never draws", post_build_repair_source)
        self.assertIn("remains a single-column stack", post_build_repair_source)
        self.assertIn("accepted_leaf_revalidated", post_build_repair_source)
        self.assertIn("validated_pending_atomic_commit", post_build_repair_source)
        self.assertIn("javascript_repair_interface", post_build_repair_source)
        self.assertIn("Remove invented or approximate selectors", post_build_repair_source)
        self.assertIn("normalize_frontend_repair_against_accepted_html", post_build_repair_source)
        self.assertIn("workspace_regions_lack_visual_hierarchy", pipeline_source)
        self.assertIn("unstyled_workspace_region_count", pipeline_source)
        self.assertIn("max_workspace_regions_in_row", pipeline_source)
        self.assertIn("blank_canvas_count", pipeline_source)
        self.assertIn("flat_canvas_count", pipeline_source)
        self.assertIn("unthemed_header_count", pipeline_source)
        self.assertIn("browser_default_button_count", pipeline_source)
        self.assertIn("workspace_layout_remains_single_column", pipeline_source)
        self.assertIn("preview_canvas_blank", pipeline_source)
        self.assertIn("preview_canvas_lacks_content_detail", pipeline_source)
        self.assertIn("product_header_lacks_visual_treatment", pipeline_source)
        self.assertIn("controls_use_browser_default_theme", pipeline_source)
        self.assertIn("preview_action_exercised", pipeline_source)
        self.assertIn("desktop_region_min_width_px", post_build_repair_source)
        self.assertIn("estimated_column_width", post_build_repair_source)
        self.assertIn("desktop columns are estimated", post_build_repair_source)
        self.assertIn("desktop_region_min_width_px * column_count", post_build_repair_source)
        self.assertIn("distinct design tokens", post_build_repair_source)
        self.assertIn("CSS body theme", post_build_repair_source)
        self.assertIn("generic geometry operation", post_build_repair_source)
        self.assertIn("canvas_preview_contract", post_build_repair_source)
        self.assertIn("allowed_content_bearing_operations", post_build_repair_source)
        self.assertIn("input/select/textarea controls", post_build_repair_source)
        self.assertIn("adapt_complex_workspace_css", post_build_repair_source)
        self.assertIn("retargeted_unowned_semantic_class_to_region_tag", read_source("scripts/ui_semantic_adapter.py"))
        semantic_adapter_source = read_source("scripts/ui_semantic_adapter.py")
        self.assertIn('POLICY_VERSION = "interface_ownership_only_v2"', semantic_adapter_source)
        self.assertIn('"policy_version": ui_semantic_adapter.POLICY_VERSION', post_build_repair_source)
        self.assertNotIn("inserted_minimum_story_graph_nodes", semantic_adapter_source)
        self.assertNotIn("inserted_missing_capability_action_controls", semantic_adapter_source)
        self.assertNotIn("inserted_missing_region_state_surfaces", semantic_adapter_source)
        self.assertNotIn("retargeted_missing_result_owner_to_workspace_status", semantic_adapter_source)
        self.assertNotIn("added_form_control_hit_target_floor", semantic_adapter_source)
        self.assertIn("stable id to an already-existing status interface", doc)
        self.assertIn("must not create user-visible product content", doc)
        self.assertIn("policy version", doc)
        self.assertIn("part of the existing post-build repair lane", doc)
        self.assertIn("design-system and cross-owner interface gate", doc)
        self.assertIn("generated fixture declared failure while exiting successfully", pipeline_source)
        self.assertIn("persisted_leaf_plan = load_pending_repair_plan(run_dir)", pipeline_source)
        self.assertIn("recover_pending_leaf_target_from_phase_log", pipeline_source)
        self.assertIn("leaf_target_recovered_from_phase_log", pipeline_source)
        self.assertIn("css_quality_contract", pipeline_source)
        self.assertIn("component_quality_targeted_repair_planned", pipeline_source)
        self.assertIn("machine-readable semantic-structure contract", doc)
        self.assertIn("exact language-aware publication contract", doc)
        self.assertIn("cannot classify ordinary prose", doc)
        self.assertIn("retries only those paths", doc)
        self.assertIn("provider_response_finish_reason", pipeline_source)
        self.assertIn("provider output truncated before contract validation", pipeline_source)
        self.assertIn("complexity-aware implementation metrics", doc)
        self.assertIn("defaults to 5000 tokens and is capped at 7000", doc)
        self.assertIn("at most 320 nonblank implementation lines", doc)
        self.assertIn("compatibility facade", doc)
        self.assertIn("normalized manifest-entry hash", doc)
        self.assertIn("CGKN_PROVIDER_MAX_DYNAMIC_LEAVES", pipeline_source)
        self.assertIn("python_leaf_interface_violations", pipeline_source)
        self.assertIn("python leaf interface contract mismatch", pipeline_source)
        self.assertIn("expected signature", pipeline_source)
        self.assertIn("Every return statement must directly return a literal mapping", pipeline_source)
        self.assertIn("inside `for stage in self.stages`", pipeline_source)
        self.assertIn("CGKN_PROVIDER_HIGH_JS_LEAF_MAX_LINES", pipeline_source)
        self.assertIn("CGKN_PROVIDER_BOUNDED_JS_MAX_CHARS", pipeline_source)
        self.assertIn("target_files = repair_target_files_for_component", pipeline_source)
        self.assertIn("required_html_id_contract", pipeline_source)
        self.assertIn("required_css_custom_property_contract", pipeline_source)
        self.assertIn("frontend_design_system_contract", pipeline_source)
        self.assertIn("manifest_symbol_publication", pipeline_source)
        self.assertIn("javascript_module_interfaces", pipeline_source)
        self.assertIn("exact_implemented_dependency_symbols", pipeline_source)
        self.assertIn("use only names listed for that provider path", pipeline_source)
        self.assertIn("component_leaf_cache_invalidated", pipeline_source)
        self.assertIn("component_leaf_cache_scanned", pipeline_source)
        self.assertIn("component_leaf_resume_identity_restored", pipeline_source)
        self.assertIn("upstream_component_resume_checkpoint_reused", pipeline_source)
        self.assertIn("component_manifest_resume_checkpoint_reused", pipeline_source)
        self.assertIn("CGKNGenerationPlanCheckpoint", pipeline_source)
        self.assertIn("CGKNSameRunResume", pipeline_source)
        self.assertIn("RESUME_PLAN_GOAL_MISMATCH", pipeline_source)
        self.assertIn('bool(str(details.get("page_title", "")).strip())', pipeline_source)
        self.assertIn('task_enabled("planning")', pipeline_source)
        self.assertIn("non_contiguous_component_checkpoint", pipeline_source)
        self.assertIn("frontend_generation_dependency_normalized", pipeline_source)
        self.assertIn('parser.add_argument("--resume-run-dir"', pipeline_facade_source)
        self.assertIn('str(nested.get("stage", "")) == "component_file_generation"', pipeline_source)
        self.assertIn("_python_callable_contract", pipeline_source)
        self.assertIn("_python_class_constructor_contract", pipeline_source)
        self.assertIn("calls incompatible", pipeline_source)
        self.assertIn("constructor and method signatures", doc)
        self.assertIn("one owned text file per leaf", doc)
        self.assertIn("function-scoped local instances", doc)
        self.assertIn("complexity_contract_slice", pipeline_source)
        self.assertIn("deterministic_complexity_blockers", pipeline_source)
        self.assertIn("semantic_review_failed_without_structured_blocker", pipeline_source)
        self.assertIn("generation_only_success_boundary", pipeline_source)
        self.assertIn('"evidence_status": "NOT_EVALUATED"', pipeline_source)
        self.assertIn('"post_build_required": True', pipeline_source)
        self.assertIn('"not_final_delivery": True', pipeline_source)
        post_build_source = read_source("scripts/post_build_finalize.py")
        self.assertIn('old_reason in {"not_requested", "capture_failed"}', post_build_source)
        self.assertIn('legacy_kwargs.pop("video_requested", None)', post_build_source)
        self.assertIn("apply_complexity_contract_gate", post_build_source)
        self.assertIn("require_final_bundle=False", post_build_source)
        self.assertIn("complexity contract is phase-aware", doc)
        self.assertIn("complexity_project_contract_not_passed", post_build_source)
        bridge_source = read_source("scripts/telegram_live_bridge.py")
        self.assertIn('session["generation"]["production_entry_receipt_ref"]', bridge_source)
        self.assertIn("visual_evidence.capture_candidate_video", bridge_source)
        self.assertIn("infer_explicit_minimum_test_count", bridge_source)
        real_test_source = read_source("scripts/real_test_execution.py")
        self.assertIn("minimum_collected_required", real_test_source)
        self.assertIn("_declared_pytest_paths", real_test_source)
        self.assertIn("declared_testpaths", real_test_source)
        self.assertIn("[tool.pytest.ini_options].testpaths", doc)
        runtime_source = read_source("scripts/customer_runtime_runner.py")
        self.assertIn("observed_result = observed[:4000]", runtime_source)
        self.assertIn("_sha256_text(observed_result)", runtime_source)
        self.assertIn("undefined pytest fixtures", pipeline_source)
        self.assertIn("PyflakesUndefinedName", pipeline_source)
        self.assertIn('"data": {', pipeline_source)
        requirement_source = read_source("scripts/requirement_decision_lane.py")
        discovery_source = read_source("scripts/discovery_selection_lane.py")
        self.assertIn("DELIVERY_EVIDENCE_TERMS", requirement_source)
        self.assertIn("goal_has_task_board_product", requirement_source)
        self.assertIn("DELIVERY_EVIDENCE_TERMS", discovery_source)
        self.assertIn("local_task_board", discovery_source)
        self.assertIn('"media review"', discovery_source)
        self.assertIn('"media evidence"', discovery_source)
        self.assertIn('"media production"', discovery_source)
        self.assertIn('"切片工作台"', requirement_source)
        self.assertIn('"切片工作台"', discovery_source)
        self.assertIn("VISUAL_NOVEL_PRODUCT_TERMS", requirement_source)
        self.assertIn("local_visual_novel_studio_requirement", requirement_source)
        self.assertIn("VISUAL_NOVEL_PRODUCT_TERMS", discovery_source)
        self.assertIn("local_visual_novel_studio", discovery_source)
        compose_source = read_source("scripts/compose_local_pipeline.py")
        self.assertIn('"database storage"', compose_source)
        self.assertIn('"image preview"', compose_source)
        self.assertIn('"切片工作台"', compose_source)
        self.assertIn("local_model_guided_canonical_component_routing", compose_source)
        self.assertIn("managed_phase_routing", compose_source)
        self.assertIn("selected requirement domain and discovery direction must agree", doc)
        self.assertIn("Visual-novel authoring is a first-class explicit product domain", doc)
        self.assertIn("goal-derived specialized-analysis domain", doc)
        self.assertIn("goal_derived_specialized_analysis_requirement", requirement_source)
        self.assertIn("goal_derived_specialized_analysis_workbench", discovery_source)
        self.assertIn("protocol_method_ids", pipeline_source)
        self.assertIn("promote_component_file_retry_plan", pipeline_source)
        self.assertIn("required_pipeline_stages=(", pipeline_source)
        self.assertIn("pending_file_manifest_for_component", pipeline_source)
        self.assertIn('suffix in {".css", ".scss"}', pipeline_source)
        self.assertIn('"authoritative_interface_catalog_chars"', pipeline_source)
        self.assertIn("CGKN_PROVIDER_INTERFACE_CATALOG_MAX_CHARS", pipeline_source)
        self.assertIn("builds a deterministic `CGKNIntegrationFeedforwardSnapshot`", doc)
        self.assertIn("Manifest paths are always project-root relative", doc)
        self.assertIn("parses the current Python consumer and its direct local providers", doc)
        self.assertIn("Stable stage artifacts are mapped to their semantic producer", doc)
        self.assertIn("Every path is relative to the project root", pipeline_source)
        self.assertIn("paths_to_parse", pipeline_source)
        materializer_source = read_source("scripts/implementation_structure_materializer.py")
        self.assertIn("stage_artifact_pairs", materializer_source)
        self.assertIn("changed upstream implementations or contracts invalidate stale downstream reuse", doc)
        self.assertIn("unrelated passed component checkpoints remain reusable", doc)
        self.assertIn("direct script entry adds both the repository root and scripts directory", doc)
        self.assertIn("failed forced repair cannot overwrite the last validated component checkpoint", doc)
        self.assertIn("non-empty bare object array", doc)
        self.assertIn("{current_component: [file_object, ...]}", doc)
        self.assertIn("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", pipeline_source)
        self.assertIn("30–120 seconds", doc)
        self.assertIn("CGNK_LOCAL_MODEL_MANIFEST_NUM_PREDICT", read_source("scripts/local_model_router.py"))
        self.assertIn("512–4096 token prediction budget", doc)
        self.assertIn("normalizes comma- or conjunction-separated component labels", doc)
        self.assertIn("cannot silently replace one persistence boundary with the other", doc)
        self.assertIn("Complexity requirements are architecture-scaled", doc)
        self.assertIn("Feedforward and feedback must use the same architecture mode", doc)
        self.assertIn("16K context window and a 4K prediction budget", doc)
        self.assertIn("`hybrid_safe`", doc)
        self.assertIn("Formal component generation, repair, and semantic QA go directly to the API provider", doc)

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
        receipt_schema = json.loads((ROOT / "schemas" / "delivery_receipt_v1.schema.json").read_text(encoding="utf-8"))
        for field in ("delivery_attempt_id", "delivery_manifest_file_hash", "package_entries_hash", "telegram_receipts"):
            self.assertIn(field, receipt_schema["required"])
        registry = (ROOT / "docs" / "01_contract_registry.md").read_text(encoding="utf-8")
        self.assertIn("scripts/canonical_delivery_receipt.py", registry)
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

    def test_rework_blocked_clears_session_package_path(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        bridge = read_source("scripts/telegram_live_bridge.py")
        marker = function_body(bridge, "mark_public_delivery_rework")

        self.assertIn("must clear `generation.package_path`", doc)
        self.assertIn('"package_path": ""', marker)

    def test_internal_acceptance_cannot_replace_delivery_truth(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        source = read_source("scripts/final_internal_acceptance.py")
        registry = read_source("scripts/formal_gate_registry.py")
        producer = read_source("scripts/formal_mainline_acceptance.py")

        self.assertIn("diagnostic fixture exerciser", doc)
        self.assertIn("cannot authorize a formal Gate `PASS`", doc)
        self.assertIn("DIAGNOSTIC_FIXTURE_ONLY = True", source)
        self.assertNotIn("send_delivery_from_manifest", source)
        self.assertNotIn("canonical_delivery_receipt", source)
        self.assertNotIn("produce_canonical_final_verdict", source)
        self.assertIn('"scripts/final_internal_acceptance.py"', registry)
        self.assertNotIn("build_internal_acceptance", producer)

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

    def test_provider_credentials_have_one_canonical_rotation_source(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        connectivity = read_source("scripts/check_connectivity.py")
        credentials = read_source("scripts/provider_credentials.py")

        self.assertIn("canonical persistent credential", doc)
        self.assertIn("CGKN_OPENAI_API_KEY_OVERRIDE", connectivity)
        self.assertNotIn('out["api_key"]', function_body(connectivity, "_load_local_notes_defaults"))
        self.assertIn("api_key_conflict_sources", connectivity)
        self.assertIn("LEGACY_USER_NAMES", credentials)
        self.assertIn("scrub_legacy_note_keys", credentials)
        self.assertIn("getpass.getpass", credentials)

    def test_design_discovery_stays_inside_provider_and_librarian_route(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        registry = read_source("docs/01_contract_registry.md")
        pipeline = read_source("scripts/run_local_pipeline_impl.py")
        design = read_source("scripts/design_research_agent.py")

        self.assertIn("runs design discovery before component generation", doc)
        self.assertIn("cannot replace canonical browser visual evidence", doc)
        self.assertIn("CGKNDesignResearchManifest", registry)
        self.assertIn("CGKNBoundedDesignContext", registry)
        self.assertIn("CGKNGeneratedDesignQualityValidation", registry)
        self.assertIn("apply_design_context_to_component_pipeline", pipeline)
        self.assertIn("build_generation_context_librarian_index", pipeline)
        self.assertIn("validate_generated_design_quality", pipeline)
        self.assertIn("run_design_research", design)
        self.assertNotIn("local_packager", design)
        self.assertNotIn("telegram_live_bridge", design)

    def test_generated_test_and_png_fixture_boundaries_are_kernel_contracts(self) -> None:
        doc = read_source("docs/00_kernel_contract.md")
        pipeline = read_source("scripts/run_local_pipeline_impl.py")

        self.assertIn("never as the second `pytest.mark.parametrize` argument", doc)
        self.assertIn("Compressed PNG offsets are container bytes", doc)
        self.assertIn("pytest_fixture_argvalue_references", pipeline)
        self.assertIn("compressed_byte_vars", pipeline)
        self.assertIn("getchannel('A').getextrema()", pipeline)
        post_build_repair = read_source("scripts/post_build_repair.py")
        self.assertIn("evidenced_tests", post_build_repair)
        self.assertIn("fixture_traceback_self", post_build_repair)
        self.assertIn('target_limit = 5 if failure_types', post_build_repair)
        self.assertIn("CGNK_POST_BUILD_OUTPUT_REPAIR_ATTEMPTS", post_build_repair)
        self.assertIn("previous_validation_errors", post_build_repair)
        self.assertIn("for target_file in target_files", post_build_repair)
        self.assertIn("python_undefined_names", post_build_repair)
        self.assertIn("CGNK_POST_BUILD_COMMAND_OUTPUT_CHARS", pipeline)
        self.assertIn("generated_fixture_source_violations", pipeline)
        self.assertIn("artifact_path.write_text(json.dumps(receipt)", post_build_repair)
        self.assertIn("write_positions", pipeline)
        self.assertIn("focused_failure_excerpt", post_build_repair)
        self.assertIn("target_diagnostic", post_build_repair)
        self.assertIn("required_stage_artifact_write_shape", post_build_repair)
        self.assertIn("Do not preserve or add any artifact_path.is_file()", post_build_repair)


if __name__ == "__main__":
    unittest.main()
