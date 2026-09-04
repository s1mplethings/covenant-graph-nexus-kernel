# ITER-057 Runtime Evidence

This support record cannot authorize a customer candidate, package, delivery,
or formal public PASS.

## ProviderJob ownership planning

- The existing `ProviderJob` schema now uses its canonical `owns` tuple for one
  or more paths. New leaf graphs store `paths` and `owns`; old `path` values are
  adapted at read boundaries.
- The deterministic heuristic considers component ownership, directory and
  interface boundary, dependency compatibility, estimated combined output, and
  independent verifiability. It caps one unit at four files and uses bounded
  type/complexity output estimates.
- Browser JavaScript is no longer split from symbol count alone. Explicit
  submodules require `fragmentation_reason`; automatic JavaScript splitting is
  permitted only for an explicit reason or expected output above the safe
  threshold.
- Output caps remain between 1,200 and 7,000 tokens. Provider timeout and retry
  policy did not change.

## Frozen DAG result

- Before: 16 jobs, waves `[2, 6, 1, 1, 1, 4, 1]`, critical path seven waves,
  average 1.0 file/job, fragmentation ratio 1.0.
- After: six jobs, waves `[1, 3, 1, 1]`, critical path four waves, average 2.0
  files/job, fragmentation ratio 0.5.
- The graph passes ownership and acyclic validation, retains a ready width of
  three, and contains no `app_part_01..04` synthetic fragments.

## Execution, repair, and compatibility

- The unchanged production `ThreadPoolExecutor` reached measured peak four for
  four ready jobs with configured parallelism four.
- `fallback_considered` retained peak four. Only `fallback_executed` selected
  the local concurrency limit.
- Repairing `src/b.py` reran its stable ownership unit
  `src/a.py + src/b.py`; `backend/unrelated.py` was reused from its passing
  checkpoint.
- Old single-path ProviderJob input and old per-file checkpoints remain
  readable.
- `scripts/provider_jobs.py` remains contract/helper-only. The production split
  executor remains the only ProviderJob scheduler.

## Verification

- Focused: 426 passed in 13.09 seconds.
- Strict slim rule guard: PASS, including the single-scheduler guard.
- Quick final: 1,426 passed, 462 deselected, zero failed in 539.90 seconds.
- Bounded enterprise-experience retrieval selected no applicable item.

## Live Provider limit

- Job: `frontend/index.html + frontend/styles.css + frontend/app.js`.
- Model: `qwen3.8-max`; request body 8,569 bytes; prompt 7,825 characters;
  output cap 6,800 tokens; timeout remained 90 seconds.
- Model Studio returned HTTP 403 `PERMISSION_DENIED` after 0.329 seconds because
  free quota was exhausted. No file was generated. This is a Provider account
  blocker, not multi-file latency, so the full E2E was not started.

## Experience usage

Bounded retrieval for Provider planning and fragmentation found no applicable
validated or approved enterprise-experience item, so no unrelated experience
was injected or promoted.
