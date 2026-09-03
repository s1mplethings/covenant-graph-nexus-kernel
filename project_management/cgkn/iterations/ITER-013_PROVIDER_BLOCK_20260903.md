# ITER-013 Real Provider Test Evidence — 2026-09-03

- Evidence status: `BLOCKED_PROVIDER`
- Workflow state: `active`
- Scope: one bounded, real Provider attempt for the visual-novel studio through the reviewed Codex conversation generation route.
- Delivery authority: none. This management evidence does not authorize packaging or public delivery.

## Outcome

The Provider endpoint and configured credential were reached, but no model invocation was permitted:

- The configured default model `gpt-5.4-nano` returned HTTP 404 `MODEL_NOT_FOUND`.
- The explicit available-model probe for `qwen3.8-max` returned HTTP 403 `PERMISSION_DENIED`: the free quota is exhausted, and paid use requires adding funds or disabling the Provider console's free-tier-only mode.
- A full Codex conversation E2E attempt was still executed once with `qwen3.8-max` to verify governed failure behavior. It ended with generation state `rework_blocked`, driver `api_provider_project_generation`, `delivery_allowed: false`, and public delivery gate `NEEDS_REWORK`.

No generated candidate, runnable entry point, source tree, generated test suite, test report, screenshot, background image, sprite image, ZIP package, or public delivery receipt was produced. The only project-directory artifacts were the failure-safe README, generation context snapshot, delivery manifest, and packager log. No fake candidate or delivery result was promoted.

## Evidence

- Raw live E2E log: `artifacts/vn_real_provider_e2e_20260903/vn_real_provider_e2e_log_package.json`
- Codex conversation session: `artifacts/vn_real_provider_e2e_20260903/sessions/vn-real-provider-e2e-20260903.json`
- Shared agent session ledger: `artifacts/vn_real_provider_e2e_20260903/sessions/vn-real-provider-e2e-20260903/agent_session.jsonl`
- Connectivity report: `examples/test_results/connectivity_check_result.json`

The raw E2E log was written before the harness's formal-status classifier was corrected and therefore contains `status: FAIL`. Its immutable smoke evidence contains `provider_error_type: PROVIDER_FORBIDDEN` and the Provider's HTTP 403 quota/permission response. Applying the corrected deterministic classifier to that same raw evidence returns `('BLOCKED_PROVIDER', True)`. The raw log was intentionally preserved rather than rewritten.

## Harness and regression evidence

- The live harness now uses Codex conversation identities and canonical artifact receipts, sends the current explicit design-confirmation phrase, selects the reviewed project-generation model policy by default, and maps Provider permission/quota failures to the formal `BLOCKED_PROVIDER` status.
- Focused Codex conversation/public delivery tests: `87 passed`.
- Kernel/generation/delivery contract tests: `46 passed`.
- Final harness/provider-resilience/canonical-receipt regression group: `16 passed`.
- Project-management and local-skill validation group: `20 passed`.
- A test-isolation defect was corrected so the canonical-credential unit test no longer consumes a persisted live connectivity report. Production preflight behavior was not changed.

## Resume condition

Resume ITER-013 after Provider access is restored by adding funds or disabling free-tier-only mode, and after confirming a model available on the configured endpoint. The next run must create fresh artifacts and independently satisfy the existing runtime, browser, media-decoding, test, packaging, and delivery gates; this blocked attempt cannot be reused as PASS evidence.
