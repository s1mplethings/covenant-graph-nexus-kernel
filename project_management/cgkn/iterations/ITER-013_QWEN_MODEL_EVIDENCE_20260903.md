# ITER-013 Qwen Model Comparison Evidence — 2026-09-03

- Evidence status: `NEEDS_REWORK`
- Workflow state: `active`
- Scope: select another Qwen model on the configured Provider and execute fresh real-project attempts through the reviewed Codex conversation route.
- Delivery authority: none. This record does not authorize packaging or public delivery.

## Model discovery and bounded probes

The configured Provider's authenticated `/models` endpoint returned a model catalog containing multiple Qwen families. Minimal structured-response probes produced:

| Model | Probe result |
| --- | --- |
| `qwen3.8-flash` | Passed once; a later full-run preflight received HTTP success but empty structured content |
| `qwen3-coder-plus` | 2/2 valid JSON responses |
| `qwen3.7-plus` | 2/2 valid JSON responses |
| `qwen3.5-plus` | 2/2 valid JSON responses |
| `qwen3.8-27b` | 0/2 valid JSON responses; HTTP succeeded but the expected JSON object was absent |

Probe artifacts are under `artifacts/provider_model_probes_20260903/`. No credential value is stored in this evidence record.

## Full real-project attempts

### qwen3-coder-plus

- Provider smoke: PASS with `{"smoke": true}`.
- Generation state: `rework_blocked`.
- Provider generation result: `BLOCKED`, reason `requirement_decision_needs_rework`.
- Requirement decision: `FAIL`; generated `GoalSpec` and `GoalDrivenProjectPlan` were marked `INSUFFICIENT_GOAL_PLAN` with empty capabilities, flows, entities, interfaces, workstreams, leaves, and acceptance tests.
- Implementation and runtime evidence: `NOT_EVALUATED`.
- Public delivery gate: `NEEDS_REWORK`; `delivery_allowed: false`.
- Raw log: `artifacts/vn_real_provider_e2e_qwen3coderplus_20260903/vn_real_provider_e2e_log_package.json`.

### qwen3.7-plus

- Provider smoke: PASS with `{"smoke": true}`.
- Generation state: `rework_blocked`.
- Provider generation result: `BLOCKED`, reason `requirement_decision_needs_rework`.
- Requirement decision: `FAIL`; the same required planning fields were not produced in the canonical goal and project-plan artifacts.
- Implementation and runtime evidence: `NOT_EVALUATED`.
- Public delivery gate: `NEEDS_REWORK`; `delivery_allowed: false`.
- Raw log: `artifacts/vn_real_provider_e2e_qwen37plus_20260903/vn_real_provider_e2e_log_package.json`.

The earlier `qwen3.8-flash` full attempt also stopped at `requirement_decision_needs_rework`; its raw log is `artifacts/vn_real_provider_e2e_qwen38flash_20260903/vn_real_provider_e2e_log_package.json`.

No attempt created a generated source tree, runnable entry point, generated tests, runtime evidence, visual evidence, background or sprite image, ZIP package, or delivery receipt. The gate correctly prevented false success and public delivery.

## Planning correction and fresh reruns

The live evidence exposed two deterministic planning defects before another paid run was attempted. Standalone `VN` was not recognized as the visual-novel domain, and generic visual workstreams could place owned `frontend/*` outputs in backend `required_paths`. The corrections preserve the existing Provider mainline: the canonical visual-novel plan now requires separate background generation, transparent character-sprite generation, asset binding, and owned HTML/CSS/JavaScript outputs; component enrichment assigns those web outputs only to the frontend component. The related planning, complexity, acceptance, and kernel profile reports `149 passed`.

### qwen3-coder-plus v7

- Provider smoke: PASS.
- Canonical requirement decision: PASS for `visual_novel_editor`.
- Actual model routing: all 54 recorded Provider requests selected `qwen3-coder-plus`; no local fallback occurred.
- Progress: 46 leaf completions were recorded across initial generation and bounded repair rounds.
- Terminal result: `NEEDS_REWORK`. A backend quality-repair round exhausted three attempts for `src/character_editor.py` because each Provider response failed the JSON payload contract.
- Candidate materialization, generated tests, runtime, browser/media evidence, packaging, and delivery: not reached. `delivery_allowed` remained false.
- Raw log: `artifacts/vn_real_provider_e2e_qwen3coderplus_v7_20260903/vn_real_provider_e2e_log_package.json`.

### qwen3.7-plus v8

- Provider smoke: PASS.
- Actual model routing: all three recorded Provider requests selected `qwen3.7-plus`.
- Terminal result: `NEEDS_REWORK`. The remote endpoint disconnected or refused the foundation manifest requests before any project leaf completed.
- Two recorded local fallback routes could not recover because Ollama was unavailable. No candidate was materialized and `delivery_allowed` remained false.
- Raw log: `artifacts/vn_real_provider_e2e_qwen37plus_v8_20260903/vn_real_provider_e2e_log_package.json`.

### qwen3.5-plus v9 bounded run

- Provider smoke and the two foundation file generations completed.
- Of seven recorded remote Provider requests, four reached the transport-timeout fallback path. The backend manifest was eventually supplied by local `qwen2.5-coder:7b`, after which subsequent large `qwen3.5-plus` code requests continued timing out.
- The run was stopped after the repeated fallback pattern made it unsuitable as evidence of `qwen3.5-plus` end-to-end capability. This bounded run is not assigned a terminal formal evidence status and does not authorize delivery.
- Partial phase evidence: `artifacts/vn_real_provider_e2e_qwen35plus_v9_20260903/logs/provider_runs/vn-real-provider-e2e-qwen35plus-v9-20260903/production-ed8ae2dc933845f39c1737a312f61d9b/provider_phase_log.jsonl`.

## Status interpretation and verification

The three raw logs were written while the E2E harness still classified all non-retryable non-PASS outcomes as `FAIL`. The classifier now recognizes a canonical `rework_blocked` generation or `NEEDS_REWORK` public gate as formal `NEEDS_REWORK`, while continuing to classify quota/permission failures as `BLOCKED_PROVIDER` and ungoverned internal failures as `FAIL`. Applying the corrected classifier to all three preserved raw logs returns `('NEEDS_REWORK', False)`.

- Harness/provider-resilience/canonical-receipt regression group: `17 passed`.
- Python compilation: PASS.

## Review conclusion

Switching away from `qwen3.8-max` restored real Provider access, and the corrected canonical plan now reaches real multi-file generation. None of the tested Qwen models completed the governed end-to-end route: `qwen3-coder-plus` is the strongest current candidate but remains unreliable on repeated structured repair output, while `qwen3.7-plus` and `qwen3.5-plus` were transport-unstable at project payload sizes. The active evidence status remains `NEEDS_REWORK`; no package or delivery PASS was produced.
