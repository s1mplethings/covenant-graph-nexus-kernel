# CGKN Release Candidate Commit Plan

## Recommendation

- Do not commit all dirty files in bulk.
- Commit source, tests, docs, and selected summary artifacts needed for review.
- Exclude runtime run directories, generated trial run trees, historical project memory churn, and temporary probe files unless a reviewer explicitly requests them.
- Suggested commit message: `Prepare CGKN release candidate validation`
- Suggested PR title: `Prepare CGKN release candidate validation`

## Suggested Commit Files

- `artifacts/pr_3_changed_files.txt`
- `artifacts/pr_3_scope_audit.json`
- `artifacts/pr_3_scope_audit.md`

## Suggested Exclude Files

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

## Review Required Files

- none

## Suggested PR Description

### What changed
- Added Customer-Agent Long Journey validation and release candidate gate artifacts.
- Added dirty worktree classification and release candidate acceptance reports.
- Updated CGKN naming in customer-facing README/docs.

### Why
- Move CGKN from feature accumulation to an auditable release-candidate validation state.

### Validation
- Release candidate verdict: `RELEASE_CANDIDATE_READY`
- Customer-Agent Long Journey: `CUSTOMER_ACCEPTED` score `100`
- Commercial readiness: `NEEDS_REWORK`, commercial_ready `False`

### Known gaps
- Commercial production ASR readiness still requires representative real ASR evidence, reference transcripts, reliability runs, and approved human review evidence.

### What is not claimed
- This PR does not claim production ASR or commercial_ready=true.
