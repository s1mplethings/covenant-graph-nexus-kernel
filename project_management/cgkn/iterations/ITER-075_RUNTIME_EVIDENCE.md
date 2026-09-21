# ITER-075 runtime evidence

Formal evidence status: `PASS_WITH_LIMITS`

## Implemented increment

- Added immutable `ArtifactInstance`, portable `ArtifactRef`, local
  `ArtifactStore`, canonical content hashing, provenance, version history,
  lifecycle status, index, lineage, and structural diff.
- Added artifact-flow compilation for required producers, typed ports,
  single-producer rules, DAGs, schemas, projections, implementations, policy
  refs, and effect constraints.
- Added deterministic ArtifactModuleRunner context, fingerprint, cache,
  materialization, ref-only checkpoint, manifest, feed-forward report, effect
  enforcement, Provider schema repair, and stale-input blocking.
- Added affected-only invalidation, partial rerun, delivery-lineage freshness
  checks, four CLIs, the standard refactor flow, and the Todo sample.
- Preserved the reviewed Provider mainline and existing flows; no packaging or
  delivery authority was added.

## Verification

- `python -m pytest tests/test_artifact_driven_kernel.py tests/test_kernel_contract.py -q`
  -> 69 passed.
- `python scripts/validate_bundle.py --root . --schema`
  -> all seven flows, including the three named legacy flows, compile with zero
  reference/schema errors.
- Both management artifacts validate through the deterministic project manager.
- `python scripts/demo_artifact_recompute.py --run-dir
  runs/artifact-v03-demo-final --json` -> unchanged ProjectSnapshot cache hit;
  seven affected descendants reran; maximum artifact context 2,640 characters
  against 12,000 comparison source characters; best ratio 0.0845.
- Full `full_all` profile reached its 1,200-second hard limit and was recorded
  as `TIMEOUT`. Its partial stream already contained unrelated pre-existing
  mainline failures before the v0.3 tests.
- The repository `quick` profile completed with 1,748 passed, 14 failed, 16
  errors, and 464 deselected. Failures include pre-existing Provider surrogate
  state leakage, missing benchmark fixtures/markers, production-tree
  contamination, legacy status text, and frozen-boundary dirty-tree guards.
  The first regression failure expects a missing
  `codex_conversation.pipeline_planner_agent` attribute; this increment did not
  modify or reconnect that experimental planner.

## Review boundary

The v0.3 increment and its directly affected contract/kernel guards pass. The
repository-wide acceptance criterion “all existing tests pass” is not claimed:
the current branch/worktree has unrelated baseline failures and the complete
profile timed out. Those issues were not repaired because doing so would expand
scope into Provider/Codex mainline behavior and existing user work.

## Improvement experiment

For future large kernel increments, record a clean committed-checkout baseline
profile before implementation, then compare the same profile after the commit.
This separates dirty-tree frozen-boundary checks and pre-existing failures from
increment regressions without weakening any guard.
