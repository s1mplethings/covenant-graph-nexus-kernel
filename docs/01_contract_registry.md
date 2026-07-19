# CGKN Contract Registry

This registry is the authoritative list of formal CGKN evidence and delivery contracts. Every formal artifact uses the canonical envelope:

```json
{
  "kind": "CGKNTestExecutionEvidence",
  "schema_version": "1.0",
  "run_id": "run-001",
  "candidate_id": "candidate-001",
  "candidate_hash": "sha256:...",
  "commit_sha": "abc123",
  "producer": "scripts/real_test_execution.py",
  "created_at": "2026-07-13T00:00:00Z",
  "status": "PASS",
  "artifact_hash": "sha256:...",
  "argv": ["python", "-m", "pytest", "tests"],
  "cwd": "/workspace/project",
  "environment": "clean_temp_env",
  "started_at": "2026-07-13T00:00:00Z",
  "finished_at": "2026-07-13T00:00:05Z",
  "exit_code": 0,
  "timeout": false,
  "collected": 1,
  "passed": 1,
  "failed": 0,
  "skipped": 0,
  "skip_reasons": {},
  "stdout_artifact": "stdout.txt",
  "stdout_hash": "sha256:...",
  "stderr_artifact": "stderr.txt",
  "stderr_hash": "sha256:...",
  "result_artifact_hash": "sha256:...",
  "test_profile": "repo_default"
}
```

Canonical EvidenceStatus values:

```text
PASS
PASS_WITH_LIMITS
NOT_EVALUATED
BLOCKED
BLOCKED_PROVIDER
BLOCKED_LOCAL_MODEL
BLOCKED_ENVIRONMENT
NEEDS_REWORK
FAIL
```

WorkflowState values are separate and must not be consumed as EvidenceStatus:

```text
queued
running
validating
waiting_user_review
packaging
delivery_sending
delivery_send_failed
rework_blocked
final_delivered
```

## Formal Artifacts

| Artifact kind | Schema | Producer | Formal consumers | Mainline | Status enum | Required fields | Legacy replacement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CGKNTestExecutionEvidence` | `schemas/test_execution_v1.schema.json` | `scripts/real_test_execution.py` | post-build finalization, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, argv, cwd, environment, run/candidate/commit IDs, timing, exit code, counts, categorized skips, stdout/stderr refs and hashes, result hash, profile | replaces ad hoc `ok`, `commands_run`, `exit_code`, and handwritten `TEST_REPORT.md` truth |
| `CGKNCustomerRuntimeEvidence` | `schemas/customer_runtime_v1.schema.json` | `scripts/customer_runtime_runner.py` | runnable project contract, visual evidence, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, startup argv, cwd, clean environment root, dependency setup, PID, URL, health probe, customer action, expected/observed result, observed hash, shutdown result | replaces hand-written `customer_runtime.json` PASS fixtures |
| `CGKNVisualEvidence` | `schemas/visual_evidence_v1.schema.json` | `scripts/browser_visual_evidence.py` | runtime visual evidence collector, public delivery gate, final verdict | yes when GUI/visual output is required | canonical EvidenceStatus | envelope, customer runtime ref/hash, browser engine/version, URL, actions, DOM assertions, network observations, screenshot path/hash, viewport, `formal_evidence=true` | replaces static preview PNG/SVG and placeholder screenshot sidecars |
| `CGKNCanonicalMediaValidationResult` | inline canonical result | `scripts/canonical_media_validation.py` | provider post-build media collector, public delivery gate | yes for generated image/background/sprite/video delivery assets | `PASS`, `FAIL`, `BLOCKED_ENVIRONMENT`, `NOT_EVALUATED` | kind, schema version, media type, requested role, path/relative path, suffix, detected format, sha256, size, decoder/version, dimensions, duration/codec/stream data, decoded frame count, blank/placeholder flags, validated_at | replaces extension/name/file-exists media acceptance |
| `CGKNUserReviewRequest` | `schemas/user_review_request_v1.schema.json` | `scripts/canonical_user_review.py` | user review writer and inspector, local packager, public delivery gate | yes before a required review | canonical EvidenceStatus | frozen candidate/evidence identity, explicit workflow-derived `visual_required`, expected Telegram reviewer, required presentation roles, actual sent artifact refs/hashes, requested/presented timestamps and self-hash | session request dictionaries and artifact presence cannot replace or promote this requirement |
| `CGKNUserReviewEvidence` | `schemas/user_review_v1.schema.json` | `scripts/canonical_user_review.py` | local packager, public delivery gate, final verdict | yes when review is required | canonical EvidenceStatus | envelope, request ref/hash, explicit `visual_required`, event id, Telegram update/message/date/reviewer identity, reviewed candidate, structured evidence refs/hashes, approval text hash, decision, reviewed_at | replaces session approval booleans and substring-based approval; inspector independently checks request, visual scope, time order and durable replay binding |
| `CGKNDeliveryManifest` | `schemas/delivery_manifest_v1.schema.json` | `scripts/local_packager.py` | public delivery gate, Telegram delivery sender, final verdict | yes | `PASS`, `PASS_WITH_LIMITS`, `NEEDS_REWORK` | envelope, source tree hash, package hash, package entries hash, candidate hash, test/runtime/visual evidence plus user review request/review refs and hashes when required | replaces unversioned delivery bundle success records |
| `CGKNDeliveryReceipt` | `schemas/delivery_receipt_v1.schema.json` | `scripts/canonical_delivery_receipt.py` | Telegram final sender, active project binder, final verdict | yes | `PASS`, `FAIL`, `NEEDS_REWORK` | envelope, delivery attempt/candidate/manifest/package binding, frozen requirements, exact attachment kinds, Telegram chat/message/file identities, local hashes, started/sent/finished timestamps | replaces boolean `sent` checks and pre-send delivered markers |
| `CGKNFinalVerdict` | `schemas/final_verdict_v1.schema.json` | `scripts/acceptance_verifier.py` | CLIs, reports, final user-visible completion | yes | canonical EvidenceStatus | envelope, required gates, upstream gate statuses, overall status | replaces runner-local final PASS decisions |
| `CGKNInternal*Evidence` | inline gate-specific canonical envelope | `scripts/final_internal_acceptance.py` | `scripts/final_contract_unification_acceptance.py`, final verdict | acceptance only | canonical EvidenceStatus | envelope plus immutable source refs/hashes and the gate-specific Leaf/workspace/collaboration/replan/recovery/startup/E2E execution facts | replaces handwritten acceptance PASS JSON; this producer cannot send Telegram, create a delivery receipt, or produce the final verdict |

## Formal Telegram Mainline

```text
customer request
-> API/provider project generation
-> provider output validation
-> post-build finalization
-> canonical test/runtime/visual evidence
-> user review when required
-> local_packager
-> public delivery gate
-> delivery receipt
-> bind active project
-> canonical final verdict
```

`pipeline_manifest` and `dynamic_pipeline_runner` remain the support/experimental planning lane. They may produce upstream evidence, but they are not a second Telegram public delivery route.

## Runtime And Visual Evidence Definitions

Real runtime evidence means a clean environment is created, dependencies are prepared, the generated project starts as a real OS process, a PID is recorded, a health probe succeeds, a customer operation is executed, the observed result is verified and hashed, and the process is stopped.

Real browser visual evidence means Playwright or an equivalent browser automation tool opens the same runtime URL, performs a customer action, verifies DOM assertions and relevant network observations, captures a screenshot, and records the screenshot hash in `CGKNVisualEvidence`.

`PASS_WITH_LIMITS` is not accepted for public final delivery. It may be used for internal evidence that is honest but incomplete, and final delivery must remain `NEEDS_REWORK` until required public artifacts are complete.

## Legacy Boundary

Legacy status names and old compact Product Studio outputs are allowed only under `legacy/` or explicit compatibility notes. Formal code must not consume those names directly; use `legacy/status_adapter.py` when a historical artifact must be interpreted.
