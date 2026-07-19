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
  "production_provenance_ref": "/production/run-001/production_candidate_provenance.json",
  "production_provenance_hash": "sha256:...",
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
| `CGKNProductionCandidateProvenance` | `schemas/production_candidate_provenance_v1.schema.json` | `scripts/telegram_live_bridge.py` | canonical test/runtime/visual producers, public delivery gate, formal mainline acceptance | yes, frozen after provider validation and source-changing post-build work | canonical EvidenceStatus | envelope, production entrypoint and generation function, run/candidate/commit identity, canonical candidate path, independently reproducible source manifest/hash, ordered self-hashed production stage receipts, provider result ref/hash | replaces session booleans, wrapper declarations, provider diagnostics, repository commit hashes, and acceptance-created provenance claims |
| `CGKNTestExecutionEvidence` | `schemas/test_execution_v1.schema.json` | `scripts/real_test_execution.py` | post-build finalization, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, argv, cwd, environment, run/candidate/commit IDs, timing, exit code, counts, categorized skips, stdout/stderr refs and hashes, result hash, profile | replaces ad hoc `ok`, `commands_run`, `exit_code`, and handwritten `TEST_REPORT.md` truth |
| `CGKNCustomerRuntimeEvidence` | `schemas/customer_runtime_v1.schema.json` | `scripts/customer_runtime_runner.py` | runnable project contract, visual evidence, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, startup argv, cwd, clean environment root, dependency setup, PID, URL, health probe, customer action, expected/observed result, observed hash, shutdown result | replaces hand-written `customer_runtime.json` PASS fixtures |
| `CGKNVisualEvidence` | `schemas/visual_evidence_v1.schema.json` | `scripts/browser_visual_evidence.py` | runtime visual evidence collector, public delivery gate, final verdict | yes when GUI/visual output is required | canonical EvidenceStatus | envelope, customer runtime ref/hash, browser engine/version, URL, actions, DOM assertions, network observations, screenshot path/hash, viewport, `formal_evidence=true` | replaces static preview PNG/SVG and placeholder screenshot sidecars |
| `CGKNCanonicalMediaValidationResult` | inline canonical result | `scripts/canonical_media_validation.py` | provider post-build media collector, public delivery gate | yes for generated image/background/sprite/video delivery assets | `PASS`, `FAIL`, `BLOCKED_ENVIRONMENT`, `NOT_EVALUATED` | kind, schema version, media type, requested role, path/relative path, suffix, detected format, sha256, size, decoder/version, dimensions, duration/codec/stream data, decoded frame count, blank/placeholder flags, validated_at | replaces extension/name/file-exists media acceptance |
| `CGKNUserReviewRequest` | `schemas/user_review_request_v1.schema.json` | `scripts/canonical_user_review.py` | user review writer and inspector, local packager, public delivery gate | yes before a required review | canonical EvidenceStatus | frozen candidate/evidence identity, explicit workflow-derived `visual_required`, expected Telegram reviewer, required presentation roles, actual sent artifact refs/hashes, requested/presented timestamps and self-hash | session request dictionaries and artifact presence cannot replace or promote this requirement |
| `CGKNUserReviewEvidence` | `schemas/user_review_v1.schema.json` | `scripts/canonical_user_review.py` | local packager, public delivery gate, final verdict | yes when review is required | canonical EvidenceStatus | envelope, request ref/hash, explicit `visual_required`, event id, Telegram update/message/date/reviewer identity, reviewed candidate, structured evidence refs/hashes, approval text hash, decision, reviewed_at | replaces session approval booleans and substring-based approval; inspector independently checks request, visual scope, time order and durable replay binding |
| `CGKNDeliveryManifest` | `schemas/delivery_manifest_v1.schema.json` | `scripts/local_packager.py` | public delivery gate, Telegram delivery sender, final verdict | yes | `PASS`, `PASS_WITH_LIMITS`, `NEEDS_REWORK` | envelope, source tree hash, package hash, package entries hash, candidate hash, test/runtime/visual evidence plus user review request/review refs and hashes when required | replaces unversioned delivery bundle success records |
| `CGKNDeliveryReceipt` | `schemas/delivery_receipt_v1.schema.json` | `scripts/canonical_delivery_receipt.py` | Telegram final sender, active project binder, final verdict | yes | `PASS`, `FAIL`, `NEEDS_REWORK` | envelope, delivery attempt/candidate/manifest/package binding, frozen requirements, exact attachment kinds, Telegram chat/message/file identities, local hashes, started/sent/finished timestamps | replaces boolean `sent` checks and pre-send delivered markers |
| `CGKNFormalGateStatus` | `schemas/formal_gate_status_v1.schema.json` | `scripts/formal_mainline_acceptance.py` | `scripts/acceptance_verifier.py` | read-only formal acceptance | canonical EvidenceStatus | envelope, candidate or repository scope, authoritative source ref/hash/producer, registered inspector and actual result, failures and blocker code | replaces handwritten wrapper PASS and `source_inspection="PASS"`; cannot replace its canonical source artifact |
| `CGKNFinalVerdict` | `schemas/final_verdict_v1.schema.json` | `scripts/acceptance_verifier.py` | CLIs, reports, final user-visible completion | yes | canonical EvidenceStatus | envelope, required gates, upstream gate statuses, overall status | replaces runner-local final PASS decisions |

`scripts/final_internal_acceptance.py` and its `CGKNInternal*Evidence` files are diagnostic fixtures, not formal artifacts. The producer provenance denylist prevents them, `tests/*`, fixtures, examples, demos, and benchmark-only producers from authorizing a formal Gate PASS.

## Formal Telegram Mainline

```text
customer request
-> API/provider project generation
-> provider output validation
-> source-changing post-build finalization
-> canonical production-candidate provenance
-> canonical test/runtime/visual evidence
-> user review when required
-> local_packager
-> public delivery gate
-> delivery receipt
-> bind active project
-> canonical final verdict
```

`pipeline_manifest` and `dynamic_pipeline_runner` remain the support/experimental planning lane. They may produce upstream evidence, but they are not a second Telegram public delivery route.

## Formal Acceptance Gate Registry

`scripts/formal_mainline_acceptance.py` reads existing artifacts only. It never runs a project team, replan, recovery, provider, packager, Telegram sender, or provenance producer. `candidate_hash` is the canonical customer source hash; repository `commit_sha` is a separate repository-scoped identity.

The Telegram production entry assigns a unique production `run_id` and `candidate_id`, and the provider job freezes ordered `production_entry`, `provider_generation`, `provider_validation`, and `post_build` receipts. After all source-changing repair work and before canonical tests, `scripts/production_candidate_provenance.py` writes `production_candidate_provenance.json` under that production run. Its inspector independently rereads every referenced artifact, validates time and identity continuity, rejects path escape and reparse links, and recomputes both the source manifest hash and the sole canonical candidate source hash. Test, runtime, and visual Gates cannot run their evidence inspector until this provenance inspector passes; a caller boolean or `source_inspection="PASS"` has no authority.

| Gate | Scope | Authoritative producer | Inspector | Source artifact | Current formal availability |
| --- | --- | --- | --- | --- | --- |
| test execution | candidate | `scripts/real_test_execution.py` | `scripts.real_test_execution.inspect_test_report` | `test_execution.json` plus `TEST_REPORT.md` | available |
| customer runtime | candidate | `scripts/customer_runtime_runner.py` | `scripts.customer_runtime_runner.inspect` | `customer_runtime.json` | available |
| visual evidence | candidate | `scripts/browser_visual_evidence.py` | `scripts.browser_visual_evidence.inspect` | `visual_evidence.json` and bound screenshot/runtime | available |
| media evidence | candidate | `scripts/canonical_media_validation.py` | `scripts.canonical_media_validation.validate_media` | no aggregate production artifact contract | `NOT_EVALUATED` until a production artifact binds the validated assets |
| user review | candidate | `scripts/canonical_user_review.py` | `inspect_user_review_request` then `inspect_user_review_evidence` | `user_review_request.json`, `user_review.json`, replay ledger, presented artifacts | available when a real Telegram review exists |
| delivery manifest | candidate | `scripts/local_packager.py` | `scripts.canonical_delivery_manifest.inspect_canonical_delivery_manifest` | `delivery_manifest.json`, final ZIP, evidence refs | available |
| delivery receipt | candidate | `scripts/canonical_delivery_receipt.py` | `scripts.canonical_delivery_receipt.inspect_canonical_delivery_receipt` | `delivery_receipt.json`, manifest, package, exact Telegram receipts | available with frozen send expectations |
| full_all | repository | `scripts/run_test_profile.py` | `scripts.formal_gate_registry.inspect_full_all` | `full_all_result.json`, stdout/stderr hashes | available |
| provider causal trace | candidate | `scripts/agent_real_provider_leaf_builder.py` | none registered | `provider_causal_trace.json` | `NOT_EVALUATED` |
| leaf profile | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| workspace truth | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| replan | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| recovery | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| collaboration timing | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| startup profile | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| deterministic E2E | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| live provider E2E | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |

The production Telegram entry is `scripts.telegram_live_bridge.start_generation_from_income`; its default generation target is `run_provider_generation_job`, followed by provider output validation, source-changing post-build work, canonical production-candidate provenance, canonical test/runtime/visual evidence, canonical review when required, `local_packager.package_project`, public delivery gate, manifest-bound send, `CGKNDeliveryReceipt`, and canonical final verdict. `run_agent_generation_job -> dynamic_pipeline_runner.run_dynamic_pipeline -> agent_conversation_loop.run_agent_loop` remains the support/experimental lane.

## Runtime And Visual Evidence Definitions

Real runtime evidence means a clean environment is created, dependencies are prepared, the generated project starts as a real OS process, a PID is recorded, a health probe succeeds, a customer operation is executed, the observed result is verified and hashed, and the process is stopped.

Real browser visual evidence means Playwright or an equivalent browser automation tool opens the same runtime URL, performs a customer action, verifies DOM assertions and relevant network observations, captures a screenshot, and records the screenshot hash in `CGKNVisualEvidence`.

`PASS_WITH_LIMITS` is not accepted for public final delivery. It may be used for internal evidence that is honest but incomplete, and final delivery must remain `NEEDS_REWORK` until required public artifacts are complete.

## Legacy Boundary

Legacy status names and old compact Product Studio outputs are allowed only under `legacy/` or explicit compatibility notes. Formal code must not consume those names directly; use `legacy/status_adapter.py` when a historical artifact must be interpreted.
