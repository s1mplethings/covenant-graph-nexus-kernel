# ITER-TASK-GATED-LEVEL3-CLOSURE-030

## 1. Git Identity

- Base: `origin/codex/supervised-provider-multitype-20261019`
- Base evidence: `60aac0906bea3d622812c8ae032aa39dea882c24`
- Branch: `codex/task-gated-level3-closure-20261019`
- Worktree: `D:\CGKN\.service_worktree\task-gated-level3`
- Source and remote publication SHA: pending canonical publication

## 2. Protected Baseline

`BASELINE-SELF-GROWN-LEAVES-001` remains unchanged.

## 3. Previous State

Provider supervision was functional, but the Canary result was 1/4 and one global `gate_pass` prevented P01–P04 from entering the project phase.

## 4. Global Gate Root Cause

The previous runner executed `run_phase(..., "projects")` only when the aggregate Canary gate passed. The replacement computes one immutable decision per task class; P04 ran and passed despite all Domain qualifications being degraded.

## 5. TaskClass Gates

- Patch: Qwen, production-qualified, P04 PASS.
- Persistent: Grok, project qualification allowed, no admitted Candidate.
- Simple: Grok with frozen Qwen transport backup, no Candidate.
- Library: Grok, provider response rejected by the Worker envelope validator, no Candidate.

## 6. Prompt Audit

The old Domain path repeated the complete BundleSpec, Project Contract and frozen interface through both `goal` and the learning-layer authoritative wrapper. It also made project-wide CLI facts reachable. The new projection carries only the project/domain goal, target, domain interface, obligation references, controlled errors, dependency policy and relevant lessons.

## 7. Production Prompt Projection

Before/after character counts were P01 5092/2624, P02 7158/2642 and P03 4906/2738. All stayed below their versioned caps. Hidden source, CLI source, tests, package data, campaign history and credentials are excluded; overflow fails closed.

## 8. DEADLINE_ONLY Semantics

`DEADLINE_ONLY` now terminates at the predicted deadline as `PROVIDER_PREDICTED_DEADLINE_REACHED`, never as a fake first-progress timeout. Cold-start minimums are 240s for Simple/Library and 300s for Persistent, with hard limits 300/360s. Streaming was not enabled because strict-schema streaming support was not established by evidence.

## 9. P04 Existing Repo

Frozen Qwen route; one call; one allowed file modified; interface and scope preserved; existing tests, Oracle, Hidden and snapshot passed. Final: PASS.

## 10. Persistent Qualification

The ITER-029 Candidate could not be reused because the new projection/authority hashes did not exist and therefore could not match P02. P02 ran once with Grok and returned `PROVIDER_SCHEMA_FAILURE`; no Candidate Revision was admitted. A runner defect briefly started a Qwen backup despite the non-transport failure; it was cancelled immediately, counted, and the authority classifier was fixed and regression-tested. Final: FAIL.

## 11. Simple Qualification

The existing selector chose Grok because Qwen had two production no-Candidate results. Grok failed transport before Candidate creation, authorizing the one frozen Qwen backup. Qwen reached the predicted deadline at 286 seconds without a Candidate. Final: FAIL.

## 12. Library Qualification

The selector chose Grok from related production candidate-materialization and interface evidence over the degraded Qwen library route. The response failed Worker envelope admission after 48 seconds; no Candidate Revision existed, so neither backup nor repair was authorized. Final: FAIL.

## 13. Qualification Candidate Reuse

The exact hash contract is implemented and tested. No Domain Candidate was admitted in this run, so no duplicate project generation occurred and no reuse claim was fabricated.

## 14. Backup / Repair

P01 used its one authorized frozen backup. P02's incorrectly started backup was operator-cancelled during the framework authority fix and remains visible in usage. P03 used no extra action. No Candidate-based repair was possible.

## 15. Provider Profiles

Only future routes consume these outcomes. Qwen Patch remains production-qualified. Simple, Persistent and Library remain degraded without Candidate.

## 16. Self-Growth

Registry reuse smoke passed with growth calls 0, builder calls 0 and admission calls 0. `self_growth_v1 = COMPLETE_FROZEN`.

## 17. Provider Usage

Six calls were started: Qwen 3 (one Patch PASS, one Simple deadline, one cancelled Persistent backup) and Grok 3 (Simple transport failure, Persistent schema failure, Library invalid envelope). DeepSeek 0. Known Qwen tokens: 8340; remaining token/cost data unavailable.

## 18. Tests

- Targeted authority/supervision: 43 passed.
- Small regression: 130 passed (within the 140 target).
- Additional diagnostic regression: 146 passed, 1 skipped.
- Product direction gate: PASS.
- Kernel/Application/Active Repository Full: NOT_RUN_BY_POLICY.

## 19. Security

Credentials and hidden sources were not persisted or sent. CLI Provider calls, manual Candidate edits, whole replans, silent fallback, unsafe admissions, accepted interface breaks, hidden leakage and orphan workers were all zero. The one backup-authority defect was detected, cancelled, disclosed and fixed.

## 20. Functional Level

`LEVEL_3_MULTI_TYPE_PROJECT_GENERATION_NEEDS_REWORK` (1/4 PASS; mandatory P01 failed).

## 21. Checkpoint

`FUNCTIONAL-CHECKPOINT-TASK-GATED-MULTITYPE-LEVEL3-001` was not established. Permanent baseline unchanged; Full Closure pending.

## 22. Remaining Limits

Domain Providers still fail to reliably materialize schema-valid Candidates for project-shaped requests. Full closure, larger projects, long-cycle tests, UI, stress and soak remain out of scope.

## 23. Commits

Canonical publication commit and remote SHA are recorded after tests and publication complete.
