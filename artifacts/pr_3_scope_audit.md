# PR #3 Scope Audit

- verdict: `PR_SCOPE_CLEAN`
- changed_file_count: `185`
- cleanup_required: `False`
- PR: https://github.com/s1mplethings/covenant-graph-nexus-kernel/pull/3

## Counts
- expected_source: `67`
- expected_tests: `55`
- expected_docs: `20`
- expected_review_artifacts: `42`
- questionable_runtime_artifacts: `1`
- generated_run_dirs: `0`
- temp_or_probe_files: `0`
- example_memory_churn: `0`
- unrelated_or_should_remove: `0`

## Blocking Findings
- none

## Explicit Noise Checks
- artifacts_runs_dirs_present: `False`
- zip_files_present: `False`
- temp_or_probe_files_present: `False`
- example_memory_churn_present: `False`
- local_studio_conversation_churn_present: `False`
- stale_old_name_product_docs_detected: `False`

## Notes
- PR includes a broad but coherent release-candidate hardening diff from previous commits plus the RC validation commit.
- No generated run directories, zip files, temp/probe files, examples/project_memory churn, or examples/local_studio conversation churn are present in the PR changed-file list.
- Local dirty/untracked runtime files remain excluded and are not part of PR #3.

## expected_source
- `pytest.ini`
- `scripts/artifact_integrity.py`
- `scripts/asr_evidence_tier.py`
- `scripts/asr_quality_gate.py`
- `scripts/asr_reference_transcript_eval.py`
- `scripts/candidate_materializer.py`
- `scripts/candidate_review_delivery.py`
- `scripts/candidate_sanitizer.py`
- `scripts/capability_manifest_check.py`
- `scripts/check_cgkn_naming_consistency.py`
- `scripts/check_connectivity.py`
- `scripts/check_test_environment.py`
- `scripts/commercial_promotion_gate.py`
- `scripts/commercial_ready_gate.py`
- `scripts/commercial_warning_policy.py`
- `scripts/complexity_project_contract_check.py`
- `scripts/continuous_generation_ledger.py`
- `scripts/customer_agent_scorecard.py`
- `scripts/customer_agent_simulator.py`
- `scripts/customer_status.py`
- `scripts/delivery_evidence_builder.py`
- `scripts/discovery_selection_lane.py`
- `scripts/final_delivery_truth.py`
- `scripts/final_promotion.py`
- `scripts/implementation_structure_materializer.py`
- `scripts/local_media_adapter.py`
- `scripts/local_model_adapter.py`
- `scripts/local_packager.py`
- `scripts/local_transcription_fixture_adapter.py`
- `scripts/pipeline_contracts.py`
- `scripts/planning_docs_materializer.py`
- `scripts/post_build_finalize.py`
- `scripts/post_build_repair.py`
- `scripts/product_acceptance.py`
- `scripts/product_studio_reply.py`
- `scripts/production_media_decode_contract.py`
- `scripts/production_reliability_gate.py`
- `scripts/provider_generation.py`
- `scripts/provider_resilience.py`
- `scripts/pytest_hang_diagnostics.py`
- `scripts/real_asr_adapter_contract.py`
- `scripts/real_asr_multi_sample_eval.py`
- `scripts/release_candidate_gate.py`
- `scripts/requirement_acceptance_check.py`
- `scripts/requirement_decision_lane.py`
- `scripts/run_candidate_smoke_benchmark.py`
- `scripts/run_commercial_readiness.py`
- `scripts/run_complexity_scale_benchmark.py`
- `scripts/run_complexity_scale_workbench_benchmark.py`
- `scripts/run_continuous_verified_generation.py`
- `scripts/run_customer_agent_long_journey_trial.py`
- `scripts/run_live_project_regression.py`
- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`
- `scripts/run_reference_answer_project_trial.py`
- `scripts/run_requirement_decision_benchmark.py`
- `scripts/sandbox_security.py`
- `scripts/shared_gui_cli_core_checker.py`
- `scripts/stage_artifact_schema_checker.py`
- `scripts/telegram_delivery/__init__.py`
- `scripts/telegram_delivery/telegram_candidate_review_sender.py`
- `scripts/telegram_delivery/telegram_final_delivery_sender.py`
- `scripts/telegram_delivery/telegram_retry_recovery.py`
- `scripts/telegram_delivery/telegram_status_renderer.py`
- `scripts/telegram_live_bridge.py`
- `scripts/user_media_pipeline_contract.py`
- `scripts/visual_evidence.py`

## expected_tests
- `tests/conftest.py`
- `tests/test_agent_test_integrated_behavior.py`
- `tests/test_artifact_integrity_check.py`
- `tests/test_asr_evidence_tier.py`
- `tests/test_asr_quality_gate.py`
- `tests/test_asr_reference_transcript_eval.py`
- `tests/test_capability_manifest_check.py`
- `tests/test_cgkn_naming_consistency.py`
- `tests/test_commercial_promotion_gate.py`
- `tests/test_commercial_readiness.py`
- `tests/test_commercial_ready_gate.py`
- `tests/test_commercial_warning_policy.py`
- `tests/test_complexity_discovery_selection.py`
- `tests/test_complexity_project_contract.py`
- `tests/test_complexity_scale_benchmark.py`
- `tests/test_continuous_verified_generation.py`
- `tests/test_contract_driven_materialization.py`
- `tests/test_customer_agent_long_journey_trial.py`
- `tests/test_customer_status.py`
- `tests/test_delivery_evidence_builder.py`
- `tests/test_final_promotion.py`
- `tests/test_fixture_media_project_enhancer.py`
- `tests/test_full_suite_stability.py`
- `tests/test_implementation_structure_materializer.py`
- `tests/test_kernel_contract.py`
- `tests/test_local_media_adapter.py`
- `tests/test_local_model_adapter.py`
- `tests/test_local_transcription_fixture_adapter.py`
- `tests/test_pipeline_module_contracts.py`
- `tests/test_planning_docs_materializer.py`
- `tests/test_product_acceptance.py`
- `tests/test_product_acceptance_pipeline_mode.py`
- `tests/test_production_media_decode_contract.py`
- `tests/test_production_reliability_gate.py`
- `tests/test_provider_api_transport.py`
- `tests/test_provider_post_build_finalize.py`
- `tests/test_provider_resilience.py`
- `tests/test_real_asr_adapter_contract.py`
- `tests/test_real_asr_multi_sample_eval.py`
- `tests/test_reference_answer_project_trial.py`
- `tests/test_release_candidate_gate.py`
- `tests/test_requirement_acceptance_layers.py`
- `tests/test_requirement_decision_lane.py`
- `tests/test_requirement_decision_pipeline_integration.py`
- `tests/test_run_local_pipeline_usage.py`
- `tests/test_sandbox_security.py`
- `tests/test_shared_gui_cli_core_checker.py`
- `tests/test_stage_artifact_schema_checker.py`
- `tests/test_startup_visual_contracts.py`
- `tests/test_telegram_bridge_generation_e2e.py`
- `tests/test_telegram_customer_bridge.py`
- `tests/test_telegram_delivery_split.py`
- `tests/test_telegram_generation_timeout_result.py`
- `tests/test_telegram_public_delivery_gate.py`
- `tests/test_user_media_pipeline_contract.py`

## expected_docs
- `AGENTS.md`
- `README.md`
- `docs/00_kernel_contract.md`
- `docs/09_openai_compatible_api_usage.md`
- `docs/60_pipeline_module_agent_guide.md`
- `docs/61_startup_and_visual_evidence_contract.md`
- `docs/62_agent_failure_routing_cheatsheet.md`
- `docs/70_commercial_hardening_plan.md`
- `docs/71_commercial_readiness_gate.md`
- `docs/72_provider_resilience.md`
- `docs/73_sandbox_security.md`
- `docs/74_product_acceptance.md`
- `docs/75_customer_status_and_telegram_delivery.md`
- `docs/agent_test_integrated_behavior.md`
- `docs/complexity_discovery_selection_lane.md`
- `docs/continuous_verified_generation_loop.md`
- `docs/customer_agent_long_journey_trial.md`
- `docs/release_candidate_acceptance.md`
- `docs/requirement_decision_first.md`
- `docs/requirement_decision_lane.md`

## expected_review_artifacts
- `artifacts/cgkn_naming_consistency_report.md`
- `artifacts/complexity_scale_acceptance.json`
- `artifacts/complexity_scale_acceptance_report.md`
- `artifacts/complexity_scale_benchmark_plan.md`
- `artifacts/complexity_scale_gap_analysis.md`
- `artifacts/complexity_scale_pipeline_result.json`
- `artifacts/complexity_scale_repair_plan.md`
- `artifacts/complexity_scale_run_summary.json`
- `artifacts/complexity_scale_run_summary.md`
- `artifacts/continuous_generation_current_gaps.md`
- `artifacts/continuous_generation_iterations.jsonl`
- `artifacts/continuous_generation_repo_status.md`
- `artifacts/customer_agent_dialogue.jsonl`
- `artifacts/customer_agent_gap_report.md`
- `artifacts/customer_agent_long_journey_summary.md`
- `artifacts/customer_agent_long_journey_trial.json`
- `artifacts/customer_agent_rework_report.md`
- `artifacts/customer_agent_scorecard.json`
- `artifacts/discovery_selection_entrypoints.md`
- `artifacts/discovery_selection_repo_status.md`
- `artifacts/full_pytest_result.json`
- `artifacts/pytest_hang_diagnostics.json`
- `artifacts/pytest_hang_diagnostics.md`
- `artifacts/reference_answer_gap_analysis.md`
- `artifacts/reference_answer_repair_plan.md`
- `artifacts/reference_answer_trial.json`
- `artifacts/reference_answer_trial_summary.md`
- `artifacts/reference_name_leak_report.md`
- `artifacts/release_candidate_acceptance.json`
- `artifacts/release_candidate_commit_plan.md`
- `artifacts/release_candidate_file_classification.json`
- `artifacts/release_candidate_file_classification.md`
- `artifacts/release_candidate_known_gaps.md`
- `artifacts/release_candidate_summary.md`
- `artifacts/requirement_decision_benchmark.json`
- `artifacts/requirement_decision_benchmark_summary.md`
- `artifacts/requirement_decision_entrypoints.md`
- `artifacts/requirement_decision_repo_status.md`
- `artifacts/stale_test_update_report.md`
- `benchmarks/complexity_scale_pipeline_benchmark.json`
- `detected_entrypoints.md`
- `repo_status.md`

## questionable_runtime_artifacts
- `artifacts/complexity_scale_command_log.txt`

## generated_run_dirs
- none

## temp_or_probe_files
- none

## example_memory_churn
- none

## unrelated_or_should_remove
- none
