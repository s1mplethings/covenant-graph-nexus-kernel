# CGKN Kernel Contract

This contract is intentionally small. Historical project-studio, role-driven validation, Fixed10, stress, and long-horizon contracts are not current MVP authority.

## 1. Product authority

PRODUCT_GOAL.md, MVP_SCOPE.md, governance/product_invariants.json, and governance/current_architecture.json are the only current product-definition authorities.

## 2. Responsibility split

The high-capability Agent owns project-level understanding, decomposition choices, capability selection, and cross-node replanning.

CGKN owns stable state, composition validation, DAG compilation, deterministic dependency handling, execution bookkeeping, bounded context projection, and result/test recording.

Executors own bounded work only. An executor may be a cheap model, local model, API, provider, browser/search tool, script, test runner, or other adapter. Executors cannot silently redefine user intent or create a competing canonical project plan.

## 3. Canonical substrate

ComponentSpec and PortSpec are the reusable executable boundary. CapabilityTree is the Agent-facing composition structure. ExecutionDAG is the runtime dependency structure. Tree and DAG are intentionally different objects: composition is not execution order.

## 4. One execution graph

CGKN must not maintain competing production task graphs. ProviderJob, WorkNode, module contracts, and future adapters may project to or from the canonical capability/DAG substrate, but they must not create a second project-level composition authority.

## 5. Context rule

Every executor receives the smallest useful task packet: node goal, declared inputs, direct relevant dependencies, required project/file context, constraints, and expected output/acceptance. Unrelated conversation and project history is not copied by default.

## 6. Failure and repair

A failed node invalidates only itself and the smallest downstream affected subgraph that can be identified safely. Repair may replace an executor, node configuration, capability, or local dependency. Whole-project regeneration is not the default recovery strategy.

## 7. Project-team rule

Project Manager, Developer, Tester, Researcher, Release, Marketing, and similar labels are role views or capability bundles. They are not required kernel stages and do not receive independent scheduling authority merely because they are roles.

## 8. Self-growth

Self-growth is capability acquisition: gap -> search -> trial/integrate -> validate -> register/reuse. It cannot weaken this contract or create new kernel authorities silently.

## 9. Maturity rule

Real tests and runtime checks remain important, but Fixed10, role-driven validation ladders, stress, latency, and 24-hour soak are not MVP readiness authorities before repeated functional substrate success.

## 10. Compatibility stack

The repository still contains substantial pre-reset Provider generation, formal evidence, packaging, public-delivery, and false-pass code. It is retained as compatibility/future material while the new substrate is integrated. It must not be expanded as the default answer to new MVP requirements.

The retired autonomous-validation ladder and its project-acceptance wrapper are
not part of that compatibility boundary. Project-level goal, test, runtime,
visual, packaging, false-pass, and public-delivery controls remain in force.

## 11. Publication

scripts/canonical_repo_publish.py remains the guarded repository publication authority. Routine work uses normal non-force publication and remote-SHA verification.

## 12. Direction gate

Architecture work must pass: python scripts/product_direction_gate.py

A change that violates product invariants is an architecture failure even when unit tests pass.

## 13. MVP runtime authorities

The operational MVP route is now bounded by these single authorities:

- `CapabilityTree` owns composition and `compile_tree` owns the one `ExecutionDAG`;
- `ComponentSpec` and `PortSpec` remain the reusable capability interface truth;
- `BlockExecutionRequest` and `BlockExecutionResult` are the runtime envelopes around bounded Component work, not replacement Component specifications;
- `ExecutorRegistry` is the only executor-resolution authority for the new runtime;
- `FileRunStore` owns human-readable project/run state, immutable attempt history, and append-only events;
- `DAGRunner` serially executes, resumes, and explicitly retries the smallest affected DAG subgraph;
- `CapabilityRegistry` owns versioned capability lifecycle and observed execution evidence.
- `GrowthLoop` owns bounded capability-gap handling; `LocalSandbox` produces trial evidence and `CapabilityAdmissionReceipt` is the only V0 admission decision record.

Self-Growth V0 is limited to allowlisted local discovery and cannot write kernel
source, use Provider work, or access the network. External candidates retain
the canonical External Executor Discovery trust requirements and cannot be
admitted while license, maintenance, exact-version security, metadata,
compatibility, or bounded-trial evidence is `REVIEW`, `BLOCK`, or `UNKNOWN`.

The compatibility conversation and generation entrypoints remain callable and
are not replaced by this isolated MVP runtime.

The reviewed Codex conversation route remains API/provider project generation,
provider output validation, post-build finalization, local_packager,
public_delivery_gate, and delivery_manifest.json. Runtime checks such as
delivery_fact_check and agent_delivery_judgment remain bounded validation
layers; they do not become packaging or delivery authorities.

## 14. Pipeline Module Mutation Contract

Any capability that proposes directly modifying, generating, or deleting bounded modules must remain behind reviewed contracts and the canonical runtime
boundary. It cannot modify truth modules, manufacture formal evidence, or write
a candidate bundle. Compatibility module mutation is never an alternate
project-generation or delivery authority.

## 15. Source-bound kernel evidence

Kernel completion uses two phases. A Source Closure commit freezes implementation,
tests, gates, and test configuration. Machine-generated coverage and test receipts
then bind to that exact source commit, source tree, and core-source hash. A following
Evidence Closure commit may change only the declared governance evidence and bounded
project-management records; it cannot change kernel source, core tests, or core gates.
`local_packager` remains the only product delivery exit and repository evidence does
not authorize packaging or public delivery.

The Agent + cheap LLM MVP preserves the same authority split. `AgentComposer`
may emit only validated `TreeEdit` decisions and is capped at four decisions
per project loop. `LLMExecutor` remains a replaceable `Executor` behind
`BlockExecutionRequest` and `BlockExecutionResult`; its model may propose only
read/list/write/patch actions, while deterministic code validates paths and
applies effects. It cannot alter the goal, tree, DAG, registry, package, or
delivery state. Agent and worker model roles must be configured independently.

## 16. L6 application boundary

An L6 application bundle may assemble admitted Components and Capabilities over
the existing `AgentProjectLoop`, `CapabilityTree`, `ExecutionDAG`,
`ExecutorRegistry`, `DAGRunner`, and `FileRunStore`. An L6 application bundle
does not become a kernel authority, a second planner, a second runtime, or a
delivery exit.

`cgkn.application` is outside the frozen L0-L5 core-source identity. An L6
change therefore cannot silently invalidate or redefine L0-L5 evidence;
changes to the identity rule, layer manifest, or any L0-L5 package still
require a new source-bound kernel receipt. L6 may be `PARTIAL` while the kernel
foundation remains `COMPLETE`, but an individual bundle may be `COMPLETE` only
when its own external acceptance evidence is source-bound and green.

After an L6 Source Closure, its bounded status, receipt, active backlog,
iteration closure, and summary records are evidence-only paths. They may not
modify application source, tests, benchmark acceptance logic, scripts, or
configuration.
