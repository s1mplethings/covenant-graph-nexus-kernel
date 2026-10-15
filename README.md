# CGKN

CGKN is a composable autonomous project-team kernel.

## MVP target

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

The high-capability Agent owns project-level decisions and composition. Cheap models, local models, APIs, search, scripts, browsers, and test tools execute bounded node work; they do not redefine project intent.

Roles such as Project Manager, Developer, Tester, Researcher, Release, or Marketing are optional capability bundles/views over the same tree and DAG, not mandatory pipeline stages.

## Current implementation state

The Component, CapabilityTree, ExecutionDAG, artifact, and deterministic runtime substrate exists, but the target architecture is **not yet wired into the default project runtime**.

The remaining compatibility entrypoints are:

- `scripts/codex_conversation.py`
- `scripts/run_codex_conversation_generation.py`
- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`

They remain callable only to preserve existing behavior while the new runtime is implemented. They are not the MVP planning or composition authority.

Cleanup status and the exact migration boundary are recorded in:

- `docs/MVP_RUNTIME_MIGRATION_BOUNDARY.md`
- `governance/mvp_cleanup_boundary.json`

## Current feature increment

The next implementation step is `MVP-002: Wire the common Block execution boundary`:

1. canonical Block execution request/result contracts;
2. replaceable Executor adapter protocol;
3. deterministic local-action executor adapter;
4. ExecutionDAG runtime coordinator;
5. persisted run/result state;
6. focused execution tests for a real DAG node.

Only after that path owns one real vertical slice should migration continue into the large compatibility runtime.

## Current reusable substrate

- `cgkn/component/` — component, port, execution, and result contracts
- `cgkn/orchestration/` — CapabilityTree and ExecutionDAG structures
- `cgkn/artifacts/` — artifact identity and materialization
- `cgkn/runtime/` — deterministic component/artifact runtime
- `scripts/local_agent_actions.py` — bounded deterministic action compatibility adapter
- `scripts/provider_jobs.py` — Provider execution/PatchSet compatibility adapter
- `scripts/real_test_execution.py` — real test/runtime support
- `scripts/local_packager.py` — packaging support
- `scripts/canonical_repo_publish.py` — guarded repository publication

## Authority and verification

Product authority lives in `PRODUCT_GOAL.md`, `MVP_SCOPE.md`, `governance/product_invariants.json`, and `governance/current_architecture.json`.

Run the direction gate with:

```bash
python scripts/product_direction_gate.py
```

The cleanup worktree passes the local direction gate, focused CapabilityTree MVP
tests, retained compatibility import smoke, and full pytest collection. A full
pytest execution and product functional readiness remain `NOT_EVALUATED`;
repository cleanup is not a functional-readiness claim.

Historical Fixed10, role-driven validation, Agent Tree/Growth experiments, stress/soak/scale gates, commercial-readiness gates, and superseded fixed-flow contracts remain available in Git history only and must not return as MVP authority.
