# ITER-107 — Fixed10 Project Generation Closure

## Outcome

The frozen Fixed10 completed on the Usage Beta `codex_surrogate` route with the original manifest SHA `9B470B65970D6A3A33D45CDCAA4646B785F1F348C27F6121573F23E7D57974AF`. All ten cases reached terminal project results without live Provider calls, network attempts, Provider blocks, false passes, or remaining `NOT_EVALUATED` project results. The outcome is `NEEDS_REWORK`: first pass and final pass were both `0/10`.

## Acceptance evidence

- Run: `artifacts/project_generation_benchmark/PGBV1_FIXED10_AFTER_20261014_11`.
- First pass: `0/10`; final pass: `0/10`; project fail: `10/10`.
- Workflow projection: `REWORK_BLOCKED 10`, `FINAL_FAIL 0`, `BLOCKED_PROVIDER 0`.
- Live Provider API calls: `0`; Codex runtime invocations: `0`; network attempts: `0`.
- Dependency clean-root pass: `4/10`; runtime, persistence, integration, and goal-fidelity pass: `0/10`.
- Revisions: four configured, all `NOT_EVALUATED` because no base project passed.
- Targeted regression: `502 passed, 44 skipped, 1 failed`.
- Full regression: `2158 passed, 480 skipped, 4 failed, 26 subtests passed`; the management-artifact schema failure was corrected and directly revalidated afterward.

## Review

The iteration is rejected as a successful closure because post-independent repair never ran. Aggregate `goal_fidelity_failed` classification masked concrete dependency and runtime failures, making all ten failures ineligible for repair. A general classifier-priority correction and focused regression were added after the completed run; they do not retroactively change the recorded Fixed10 evidence.

## Retrospective

The canonical surrogate handshake, multi-emission persistence, Windows evaluator launch, terminal result completion, contamination protection, and audit generation worked. Clean offline dependency preparation, runtime closure, visual-scope preservation, and post-independent repair did not. The next iteration should rerun the exact Fixed10 only after defining a reviewed offline dependency strategy and validating that the corrected classifier causes ordinary failures to enter at most two ProviderJob repair rounds.

Pass 6 long-horizon evidence was not changed, deleted, extended, or reinterpreted.
