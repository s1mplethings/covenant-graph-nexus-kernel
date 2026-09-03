# ITER-054 Runtime Evidence

This support record cannot authorize a customer candidate, package, delivery,
or formal public PASS.

## Production closure

- `codex_conversation.run_supervision_recovery_cycle` consumes the exact
  hash-bound router receipt and clears its matching pending receipt.
- Integration recovery reuses the existing Provider same-run resume and
  split-file leaf executor, repeats Provider validation, re-emits
  `integration_complete`, and re-audits.
- Evidence recovery moves affected stale canonical receipts out of the active
  chain, invokes no Provider, reruns the canonical producer/verifier, re-emits
  the original checkpoint, and re-audits.
- Kernel recovery invokes `governed_kernel_repair.execute_repair`, requires its
  regression checks, re-emits the original checkpoint, and re-audits.
- Two consecutive refusals stop as `NEEDS_REWORK`; user decision waits and halt
  stops explicitly.
- `provider_jobs.py` contains only ProviderJob/PatchSet contracts and
  validation. The production worker pool remains solely in
  `run_local_pipeline_impl.py`.
- Exact leaf-id repair targeting was verified: `backend:a` maps only to
  `src/a.py` and does not widen to the adjacent `src/b.py` leaf.

## Regression evidence

- Production recovery A-E: all five passed. A and B used two auditor calls;
  C used two auditor calls plus one governed repair; D used two auditor calls
  and one repair attempt before `NEEDS_REWORK`; E used zero Codex calls.
- Expanded focused suite: 436 passed, 3 skipped in 335.29 seconds.
- Strict slimming/kernel rule guard: PASS.
- Initial quick run: 1403 passed, 6 failed, 461 deselected. It exposed one
  over-narrow evidence invalidation role and five stale support-lane tests that
  patched duplicate bare/package module instances.
- Corrected quick run: 1409 passed, 0 failed, 461 deselected in 873.08 seconds.
- Final quick run after the exact leaf-id mapping correction: 1410 passed,
  0 failed, 461 deselected in 550.45 seconds; profile artifact status is PASS.
- Post-commit quick run bound to code commit `80ac2fb`: 1410 passed, 0 failed,
  461 deselected in 569.39 seconds; profile artifact status and artifact hash
  validation are PASS.

## Provider live status

- No live Provider call was required for this bounded local closure.
- The latest retained Qwen run remains `PROVIDER_TRANSPORT_UNSTABLE` because of
  TLS transport failure. This is a live-provider limitation, not a local
  recovery-loop failure.

## Experience usage

- `EXP-CGKN-QUALITY-001`: kept recovery receipts and workflow outcomes separate
  from formal evidence and delivery authority.
- `EXP-CGKN-LIBRARIAN-001`: preserved bounded affected-only Provider repair
  context through the existing pending repair plan instead of copying the full
  run into a second scheduler.

Both items were useful. No new enterprise experience candidate is proposed
from this single iteration.
