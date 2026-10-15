# MVP runtime migration boundary

## Status

Repository cleanup has reached the point where further deletion would remove the only remaining compatibility runtime before a replacement exists.

The cleanup phase is therefore structurally complete, but unverified. This is **not** a functional-readiness claim. GitHub Actions on the isolated branch has reported startup failure, so the product direction gate, focused tests, and full pytest suite remain `NOT_EVALUATED`.

Machine-readable status lives in `governance/mvp_cleanup_boundary.json`.

## Current target architecture

```text
User Goal
  -> high-capability Agent
  -> CapabilityTree
  -> ExecutionDAG
  -> Component / Block
  -> replaceable bounded Executor
  -> Result / Test / Artifact
  -> Project State
  -> Agent checkpoint
```

The structural substrate exists in:

- `cgkn/component/`
- `cgkn/orchestration/capability_tree.py`
- `cgkn/orchestration/execution_dag.py`
- `cgkn/artifacts/`
- `cgkn/runtime/`

It is not yet wired into the default project runtime. The repository must not describe the target architecture as already operational.

## Intentional compatibility boundary

The following entrypoints remain active because they are the only current compatibility path for existing project-generation behavior:

- `scripts/codex_conversation.py`
- `scripts/run_codex_conversation_generation.py`
- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`

Supporting provider, evidence, repair, packaging, test, and publication modules remain available as migration material. Their presence does not make them the MVP planning or composition authority.

Do not remove or substantially rewrite this compatibility runtime until a new CapabilityTree/ExecutionDAG path owns one real vertical slice and can execute, test, persist, and report a bounded project change.

## Cleanup completed

The active repository no longer treats the following as MVP authority:

- Fixed10 and Provider-owned whole-project planning;
- role-driven or autonomous validation ladders;
- Agent Tree/Growth/Pruning experiment stacks;
- stress, soak, long-run, scale, and commercial-readiness gates;
- customer-journey simulations and standalone benchmark launchers;
- fixed Product Studio stage contracts and superseded implementation plans.

Historical material is retained under `legacy/pre_mvp_reset/` and in Git history.

## Feature implementation now required

The next increment is `MVP-002: Wire the common Block execution boundary`.

Required outputs:

1. one canonical Block execution request/result contract;
2. one replaceable Executor adapter protocol;
3. an adapter for deterministic local actions;
4. an ExecutionDAG runtime coordinator that executes ready nodes;
5. focused tests proving a real DAG node executes without delegating project planning to a Provider;
6. persisted run/result state sufficient for a later vertical slice.

Only after this increment exists should migration continue into `codex_conversation.py` and `run_local_pipeline_impl.py`.
