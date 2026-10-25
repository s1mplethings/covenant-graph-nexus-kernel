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

The current software-project MVP uses that same coordinator to design and freeze one minimal `ProjectBlueprint`, then compiles cohesive blueprint units into the existing CapabilityTree/DAG. Workers use exact-owns `FileBundle` generation and file-unique `PatchBundle` v2 repair over a non-empty owned subset. Deterministic code owns failure stage/origin/owner attribution, baseline-gated retry-versus-repair routing, scope, syntax, interface guards, atomic application, evidence, and affected-only continuity.

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

The compatibility L6 application bundle lives under `cgkn/application/software_project/`.
It assembles the existing Agent, tree, DAG, executor, state, and test
authorities to generate isolated stdlib-only projects with file-scoped workers,
deterministic snapshots, and external acceptance. Its deterministic contract
and harness tests pass, but the bounded real-Provider Stage 1 run did not reach
a final project PASS after two application repair rounds. The bundle therefore
remains `PARTIAL` at `GENERATION_LEVEL_0`; this does not change LEVEL 4 product
readiness or the completed L0-L5 kernel foundation.

The replacement L6 adapter in `cgkn/application/project_blueprint.py` and
`cgkn/application/project_loop.py` now accepts a minimal semantic design
payload and deterministically supplies executor metadata, scope limits,
compile/pytest/runtime/acceptance checks, protected paths, and timeouts. The
versioned API Lab raw-defer route preserves Provider text and transport
metadata while CGKN remains the sole structured-answer selector. A failed unit
generation is retried as generation until it establishes a hash-bound materialized
baseline; only later compile, test, runtime, or acceptance failures may enter
repair. Fresh live generation and repair receipts remain required before the MVP
status can advance. Run the bounded profiles through `python
scripts/run_project_mvp.py`.

The read-only Conversation product surface in
`cgkn/application/conversation/` consumes the existing `cgnk_knowledge`
store and retrieval authority through the common Component/Block boundary.
It performs localized retrieval, bounded raw-evidence drill-down when exact
details are required, and returns model answers separately from evidence and
provenance. Provider failure degrades to `EVIDENCE_ONLY`; absent evidence is
reported as `INSUFFICIENT_EVIDENCE`. The `cgkn_conversation` MCP tool exposes
this capability without writing memory or creating another retrieval store.

Knowledge growth now uses the same `ProjectKnowledgePack` authority through
`knowledge.internalize@1.0`. Raw evidence remains byte-faithful and
provenance-bound; deterministic hot-path updates classify relations and mark
only actual dependent abstractions stale. Derived summaries refresh explicitly
on demand or in a batch rather than rebuilding globally on every write. See
`docs/KNOWLEDGE_GROWTH_INTERNALIZATION.md` and run the 100/1000/5000-entry
comparison with `python scripts/run_knowledge_growth_evaluation.py --profile final --json`.

Promotion Studio in `cgkn/application/promotion/` is a local-first capability
branch over the same kernel authorities. It projects explicit public-safe
evidence into approved claims, detects material signals, produces bounded
platform drafts and deterministic PNG/FFmpeg media, and records exact-hash
approval-bound publication plans and receipts. Publication is `DRAFT_ONLY` by
default; credentials remain opaque local references and browser click
automation is unsupported. Run the offline qualification with `python
scripts/run_promotion_studio.py --profile promotion-evaluate --json`.

Community Operator in `cgkn/application/community/` adds bounded public
discussion discovery, thread normalization, precision-first opportunity
ranking, separate engage/project-mention decisions, evidence-grounded reply
drafting, exact-hash `APPROVED_TO_REPLY`, idempotent official-API transport,
follow-up tracking, and moderation suppression. Public thread text is always
untrusted data. Unknown community rules fail closed to human review, and every
external reply still requires explicit approval. Run the offline evaluation
with `python scripts/run_community_operator.py --profile evaluate --json`; the
`real-read` profile performs bounded public API reads and never posts.

Cleanup status and the exact migration boundary are recorded in:

- `docs/MVP_RUNTIME_MIGRATION_BOUNDARY.md`
- `governance/mvp_cleanup_boundary.json`

## Current feature increment

`ITER-054` is the active isolated increment. It qualifies Community Operator
contracts, policy/value/claim gates, approval-bound fake reply lifecycles,
official adapter contracts, and real read-only dogfood without modifying
production routing, Registry, Knowledge, Runtime, DAG, or scheduler authority.

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
- `cgkn/application/conversation/` — evidence-grounded read-only Conversation surface
- `cgkn/application/knowledge_growth/` — local-lazy ProjectKnowledgePack update capability
- `cgkn/application/promotion/` — evidence-grounded promotion, media, approval, and publishing capabilities
- `cgkn/application/community/` — policy-safe community discovery, ranking, reply, follow-up, and experience capabilities
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
