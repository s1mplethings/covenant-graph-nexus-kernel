# Release Candidate File Classification

- dirty_count: `140`
- policy: do not commit runtime/generated outputs in bulk; review unknown dirty files.

## A_core_code

- `M scripts/check_cgkn_naming_consistency.py`
- `A scripts/customer_agent_scorecard.py`
- `A scripts/customer_agent_simulator.py`
- `A scripts/release_candidate_gate.py`
- `A scripts/run_customer_agent_long_journey_trial.py`

## B_test_code

- `A tests/test_customer_agent_long_journey_trial.py`
- `A tests/test_release_candidate_gate.py`

## C_docs

- `M AGENTS.md`
- `M README.md`
- `A docs/customer_agent_long_journey_trial.md`
- `A docs/release_candidate_acceptance.md`

## D_necessary_artifacts

- `M artifacts/cgkn_naming_consistency_report.md`
- `M artifacts/complexity_scale_acceptance.json`
- `M artifacts/complexity_scale_acceptance_report.md`
- `M artifacts/complexity_scale_gap_analysis.md`
- `M artifacts/complexity_scale_run_summary.json`
- `M artifacts/complexity_scale_run_summary.md`
- `M artifacts/continuous_generation_current_gaps.md`
- `M artifacts/continuous_generation_iterations.jsonl`
- `A artifacts/customer_agent_dialogue.jsonl`
- `A artifacts/customer_agent_gap_report.md`
- `A artifacts/customer_agent_long_journey_summary.md`
- `A artifacts/customer_agent_long_journey_trial.json`
- `A artifacts/customer_agent_rework_report.md`
- `A artifacts/customer_agent_scorecard.json`
- `AM artifacts/full_pytest_result.json`
- `M artifacts/reference_answer_gap_analysis.md`
- `M artifacts/reference_answer_repair_plan.md`
- `M artifacts/reference_answer_trial.json`
- `M artifacts/reference_answer_trial_summary.md`
- `A artifacts/release_candidate_acceptance.json`
- `A artifacts/release_candidate_commit_plan.md`
- `A artifacts/release_candidate_file_classification.json`
- `A artifacts/release_candidate_file_classification.md`
- `A artifacts/release_candidate_known_gaps.md`
- `A artifacts/release_candidate_summary.md`

## E_runtime_generated_artifacts

- `?? artifacts/customer_agent_long_journey_runs/`
- `?? artifacts/full_pytest_output.txt`
- `?? artifacts/reference_answer_project_trial_runs/`
- `?? artifacts/requirement_decision_benchmark_runs/`
- `?? examples/local_studio/conversations/chat-4/`
- `?? examples/local_studio/conversations/chat-b/`
- `?? examples/local_studio/conversations/chat-c/`
- `?? examples/local_studio/conversations/chat-e2e-pipeline/`
- `?? examples/local_studio/conversations/chat-e2e/`
- `?? examples/local_studio/conversations/chat-fallback-e2e/`
- `?? examples/local_studio/conversations/chat-fallback/`
- `?? examples/local_studio/conversations/chat-no-api/`
- `?? examples/local_studio/conversations/chat-pipeline/`
- `?? examples/local_studio/conversations/chat-retry-pass/`
- `?? examples/local_studio/conversations/chat-stage-resume/`

## F_examples_project_memory_or_historical_dirty

- `M examples/project_memory/chat-1/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-1/project_memory.artifact.json`
- `M examples/project_memory/chat-2/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-2/project_memory.artifact.json`
- `M examples/project_memory/chat-3/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-3/project_memory.artifact.json`
- `M examples/project_memory/chat-4/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-4/project_memory.artifact.json`
- `M examples/project_memory/chat-5/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-5/project_memory.artifact.json`
- `M examples/project_memory/chat-6/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-6/project_memory.artifact.json`
- `M examples/project_memory/chat-a/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-a/project_memory.artifact.json`
- `M examples/project_memory/chat-async/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-async/project_memory.artifact.json`
- `M examples/project_memory/chat-attachment/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-attachment/project_memory.artifact.json`
- `M examples/project_memory/chat-b/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-b/project_memory.artifact.json`
- `M examples/project_memory/chat-block/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-block/project_memory.artifact.json`
- `M examples/project_memory/chat-c/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-c/project_memory.artifact.json`
- `M examples/project_memory/chat-control/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-control/project_memory.artifact.json`
- `M examples/project_memory/chat-cs2/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-cs2/project_memory.artifact.json`
- `M examples/project_memory/chat-d/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-d/project_memory.artifact.json`
- `M examples/project_memory/chat-decision/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-decision/project_memory.artifact.json`
- `M examples/project_memory/chat-e2e-pipeline/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-e2e-pipeline/project_memory.artifact.json`
- `M examples/project_memory/chat-e2e/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-e2e/project_memory.artifact.json`
- `M examples/project_memory/chat-fail-rework/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-fail-rework/project_memory.artifact.json`
- `M examples/project_memory/chat-fallback-e2e/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-fallback-e2e/project_memory.artifact.json`
- `M examples/project_memory/chat-fallback/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-fallback/project_memory.artifact.json`
- `M examples/project_memory/chat-force/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-force/project_memory.artifact.json`
- `M examples/project_memory/chat-greeting-delivered/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-greeting-delivered/project_memory.artifact.json`
- `M examples/project_memory/chat-greeting-existing/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-greeting-existing/project_memory.artifact.json`
- `M examples/project_memory/chat-manifest/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-manifest/project_memory.artifact.json`
- `M examples/project_memory/chat-no-api/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-no-api/project_memory.artifact.json`
- `M examples/project_memory/chat-non-pass/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-non-pass/project_memory.artifact.json`
- `M examples/project_memory/chat-old-control/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-old-control/project_memory.artifact.json`
- `M examples/project_memory/chat-partial-no-deliver/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-partial-no-deliver/project_memory.artifact.json`
- `M examples/project_memory/chat-pass/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-pass/project_memory.artifact.json`
- `M examples/project_memory/chat-pipeline/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-pipeline/project_memory.artifact.json`
- `M examples/project_memory/chat-restart/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-restart/project_memory.artifact.json`
- `M examples/project_memory/chat-retry-fail/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-retry-fail/project_memory.artifact.json`
- `M examples/project_memory/chat-retry-pass/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-retry-pass/project_memory.artifact.json`
- `M examples/project_memory/chat-retry/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-retry/project_memory.artifact.json`
- `M examples/project_memory/chat-revise/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-revise/project_memory.artifact.json`
- `M examples/project_memory/chat-stage-resume/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-stage-resume/project_memory.artifact.json`
- `M examples/project_memory/chat-startup/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-startup/project_memory.artifact.json`
- `M examples/project_memory/chat-status-no-restart/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-status-no-restart/project_memory.artifact.json`
- `M examples/project_memory/chat-status-package/PROJECT_MEMORY.md`
- `M examples/project_memory/chat-status-package/project_memory.artifact.json`
- `?? examples/project_memory/candidate-message/`
- `?? examples/project_memory/candidate-review-test/`
- `?? examples/project_memory/candidate-review/`
- `?? examples/project_memory/task-board-review/`

## G_should_not_commit_temporary_outputs

- `?? artifacts/complexity_scale_file_inventory.txt`
- `?? artifacts/pytest_collect_full.txt`
- `?? artifacts/pytest_progress.jsonl`
- `?? artifacts/tmp_integrity_debug/`
- `?? artifacts/write_probe.txt`

## review_required

- none

## Recommended Commit Files

- `AGENTS.md`
- `README.md`
- `artifacts/cgkn_naming_consistency_report.md`
- `artifacts/continuous_generation_current_gaps.md`
- `artifacts/customer_agent_dialogue.jsonl`
- `artifacts/customer_agent_gap_report.md`
- `artifacts/customer_agent_long_journey_summary.md`
- `artifacts/customer_agent_long_journey_trial.json`
- `artifacts/customer_agent_rework_report.md`
- `artifacts/customer_agent_scorecard.json`
- `artifacts/full_pytest_result.json`
- `artifacts/release_candidate_acceptance.json`
- `artifacts/release_candidate_commit_plan.md`
- `artifacts/release_candidate_file_classification.json`
- `artifacts/release_candidate_file_classification.md`
- `artifacts/release_candidate_known_gaps.md`
- `artifacts/release_candidate_summary.md`
- `docs/customer_agent_long_journey_trial.md`
- `docs/release_candidate_acceptance.md`
- `scripts/check_cgkn_naming_consistency.py`
- `scripts/customer_agent_scorecard.py`
- `scripts/customer_agent_simulator.py`
- `scripts/release_candidate_gate.py`
- `scripts/run_customer_agent_long_journey_trial.py`
- `tests/test_customer_agent_long_journey_trial.py`
- `tests/test_release_candidate_gate.py`

## Recommended Exclude Files

- `artifacts/complexity_scale_file_inventory.txt`
- `artifacts/customer_agent_long_journey_runs/`
- `artifacts/full_pytest_output.txt`
- `artifacts/pytest_collect_full.txt`
- `artifacts/pytest_progress.jsonl`
- `artifacts/reference_answer_project_trial_runs/`
- `artifacts/requirement_decision_benchmark_runs/`
- `artifacts/tmp_integrity_debug/`
- `artifacts/write_probe.txt`
- `examples/local_studio/conversations/chat-4/`
- `examples/local_studio/conversations/chat-b/`
- `examples/local_studio/conversations/chat-c/`
- `examples/local_studio/conversations/chat-e2e-pipeline/`
- `examples/local_studio/conversations/chat-e2e/`
- `examples/local_studio/conversations/chat-fallback-e2e/`
- `examples/local_studio/conversations/chat-fallback/`
- `examples/local_studio/conversations/chat-no-api/`
- `examples/local_studio/conversations/chat-pipeline/`
- `examples/local_studio/conversations/chat-retry-pass/`
- `examples/local_studio/conversations/chat-stage-resume/`
- `examples/project_memory/candidate-message/`
- `examples/project_memory/candidate-review-test/`
- `examples/project_memory/candidate-review/`
- `examples/project_memory/chat-1/PROJECT_MEMORY.md`
- `examples/project_memory/chat-1/project_memory.artifact.json`
- `examples/project_memory/chat-2/PROJECT_MEMORY.md`
- `examples/project_memory/chat-2/project_memory.artifact.json`
- `examples/project_memory/chat-3/PROJECT_MEMORY.md`
- `examples/project_memory/chat-3/project_memory.artifact.json`
- `examples/project_memory/chat-4/PROJECT_MEMORY.md`
- `examples/project_memory/chat-4/project_memory.artifact.json`
- `examples/project_memory/chat-5/PROJECT_MEMORY.md`
- `examples/project_memory/chat-5/project_memory.artifact.json`
- `examples/project_memory/chat-6/PROJECT_MEMORY.md`
- `examples/project_memory/chat-6/project_memory.artifact.json`
- `examples/project_memory/chat-a/PROJECT_MEMORY.md`
- `examples/project_memory/chat-a/project_memory.artifact.json`
- `examples/project_memory/chat-async/PROJECT_MEMORY.md`
- `examples/project_memory/chat-async/project_memory.artifact.json`
- `examples/project_memory/chat-attachment/PROJECT_MEMORY.md`
- `examples/project_memory/chat-attachment/project_memory.artifact.json`
- `examples/project_memory/chat-b/PROJECT_MEMORY.md`
- `examples/project_memory/chat-b/project_memory.artifact.json`
- `examples/project_memory/chat-block/PROJECT_MEMORY.md`
- `examples/project_memory/chat-block/project_memory.artifact.json`
- `examples/project_memory/chat-c/PROJECT_MEMORY.md`
- `examples/project_memory/chat-c/project_memory.artifact.json`
- `examples/project_memory/chat-control/PROJECT_MEMORY.md`
- `examples/project_memory/chat-control/project_memory.artifact.json`
- `examples/project_memory/chat-cs2/PROJECT_MEMORY.md`
- `examples/project_memory/chat-cs2/project_memory.artifact.json`
- `examples/project_memory/chat-d/PROJECT_MEMORY.md`
- `examples/project_memory/chat-d/project_memory.artifact.json`
- `examples/project_memory/chat-decision/PROJECT_MEMORY.md`
- `examples/project_memory/chat-decision/project_memory.artifact.json`
- `examples/project_memory/chat-e2e-pipeline/PROJECT_MEMORY.md`
- `examples/project_memory/chat-e2e-pipeline/project_memory.artifact.json`
- `examples/project_memory/chat-e2e/PROJECT_MEMORY.md`
- `examples/project_memory/chat-e2e/project_memory.artifact.json`
- `examples/project_memory/chat-fail-rework/PROJECT_MEMORY.md`
- `examples/project_memory/chat-fail-rework/project_memory.artifact.json`
- `examples/project_memory/chat-fallback-e2e/PROJECT_MEMORY.md`
- `examples/project_memory/chat-fallback-e2e/project_memory.artifact.json`
- `examples/project_memory/chat-fallback/PROJECT_MEMORY.md`
- `examples/project_memory/chat-fallback/project_memory.artifact.json`
- `examples/project_memory/chat-force/PROJECT_MEMORY.md`
- `examples/project_memory/chat-force/project_memory.artifact.json`
- `examples/project_memory/chat-greeting-delivered/PROJECT_MEMORY.md`
- `examples/project_memory/chat-greeting-delivered/project_memory.artifact.json`
- `examples/project_memory/chat-greeting-existing/PROJECT_MEMORY.md`
- `examples/project_memory/chat-greeting-existing/project_memory.artifact.json`
- `examples/project_memory/chat-manifest/PROJECT_MEMORY.md`
- `examples/project_memory/chat-manifest/project_memory.artifact.json`
- `examples/project_memory/chat-no-api/PROJECT_MEMORY.md`
- `examples/project_memory/chat-no-api/project_memory.artifact.json`
- `examples/project_memory/chat-non-pass/PROJECT_MEMORY.md`
- `examples/project_memory/chat-non-pass/project_memory.artifact.json`
- `examples/project_memory/chat-old-control/PROJECT_MEMORY.md`
- `examples/project_memory/chat-old-control/project_memory.artifact.json`
- `examples/project_memory/chat-partial-no-deliver/PROJECT_MEMORY.md`
- `examples/project_memory/chat-partial-no-deliver/project_memory.artifact.json`
- `examples/project_memory/chat-pass/PROJECT_MEMORY.md`
- `examples/project_memory/chat-pass/project_memory.artifact.json`
- `examples/project_memory/chat-pipeline/PROJECT_MEMORY.md`
- `examples/project_memory/chat-pipeline/project_memory.artifact.json`
- `examples/project_memory/chat-restart/PROJECT_MEMORY.md`
- `examples/project_memory/chat-restart/project_memory.artifact.json`
- `examples/project_memory/chat-retry-fail/PROJECT_MEMORY.md`
- `examples/project_memory/chat-retry-fail/project_memory.artifact.json`
- `examples/project_memory/chat-retry-pass/PROJECT_MEMORY.md`
- `examples/project_memory/chat-retry-pass/project_memory.artifact.json`
- `examples/project_memory/chat-retry/PROJECT_MEMORY.md`
- `examples/project_memory/chat-retry/project_memory.artifact.json`
- `examples/project_memory/chat-revise/PROJECT_MEMORY.md`
- `examples/project_memory/chat-revise/project_memory.artifact.json`
- `examples/project_memory/chat-stage-resume/PROJECT_MEMORY.md`
- `examples/project_memory/chat-stage-resume/project_memory.artifact.json`
- `examples/project_memory/chat-startup/PROJECT_MEMORY.md`
- `examples/project_memory/chat-startup/project_memory.artifact.json`
- `examples/project_memory/chat-status-no-restart/PROJECT_MEMORY.md`
- `examples/project_memory/chat-status-no-restart/project_memory.artifact.json`
- `examples/project_memory/chat-status-package/PROJECT_MEMORY.md`
- `examples/project_memory/chat-status-package/project_memory.artifact.json`
- `examples/project_memory/task-board-review/`

## Review Required

- none
