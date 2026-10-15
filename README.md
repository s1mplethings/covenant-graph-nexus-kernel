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

The Component, CapabilityTree, ExecutionDAG, bounded executor, file-backed
state, and deterministic DAG runtime substrate now owns an isolated real
vertical slice. It supports resume, explicit retry, affected-subgraph rerun,
controlled tree edits, and a versioned Capability Registry. It has **not**
replaced the default compatibility project-generation runtime.

Self-Growth V0 can now discover the allowlisted Python standard-library
`json.loads` implementation for a missing `json.parse@1` capability, run a
bounded local trial, issue an admission receipt, persist the registry, resume
the original DAG, and reuse the admitted capability in a later run. It cannot
modify kernel files and makes no Provider or network calls.

The LEVEL 4 Agent MVP adds a sparse high-capability composition loop and a
separately configured low-cost LLM executor. Agent outputs are validated
TreeEdits; worker outputs are restricted to read/list/write/patch proposals
that deterministic code applies. A real Provider run repaired a broken Python
function and passed real pytest through the existing Block, DAG, registry, and
FileRunStore authorities. Run it with `python scripts/run_agent_mvp.py
--run-root <isolated-dir> --benchmark --json`.

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

`MVP-013` is complete in the isolated runtime. The next minimal increment is a
real-Provider controlled repair run plus aggregate budget/context telemetry;
migration into the large compatibility runtime remains a separate, later
decision.

## Current reusable substrate

- `cgkn/component/` — component, port, execution, and result contracts
- `cgkn/orchestration/` — CapabilityTree and ExecutionDAG structures
- `cgkn/artifacts/` — artifact identity and materialization
- `cgkn/runtime/` — deterministic component/artifact runtime
- `cgkn/execution/` — bounded Block request/result envelopes
- `cgkn/state/` — project/run state, attempt history, and event log
- `cgkn/executors/` — replaceable executor protocol, registry, and local adapters
- `cgkn/capabilities/` — versioned capability lifecycle registry
- `cgkn/growth/` — local gap, discovery, sandbox trial, admission, and reuse loop
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

The runtime foundation passes the local direction gate, focused Component,
execution, state, executor, DAG runtime, capability registry, publication, and
kernel-contract checks. The deterministic vertical slice and local repair path
are `PASS`; replacement of the compatibility mainline and full production
readiness remain `NOT_EVALUATED`.

Historical Fixed10, role-driven validation, Agent Tree/Growth experiments, stress/soak/scale gates, commercial-readiness gates, and superseded fixed-flow contracts remain available in Git history only and must not return as MVP authority.
