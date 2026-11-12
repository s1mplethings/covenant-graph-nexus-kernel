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

## 17. Ratcheted source boundaries

Source-bound evidence is partitioned into Kernel, Application, and Experiment
boundaries. Kernel evidence covers only L0-L5 production packages, their tests,
and Kernel authority/governance scripts. Application evidence covers
`cgkn.application`, its production support, acceptance fixtures, and tests.
Canonical requirement admission support such as
`scripts/obligation_traceability_gate.py` belongs to the Application boundary,
even though the boundary classifier itself remains Kernel governance.
Experiment evidence covers isolated experiments, experiment tests, and their
runner. A change in one boundary cannot stale a receipt owned exclusively by a
different boundary.

Every promoted baseline names its parent, binds a committed source identity,
records the applicable receipts and regression profiles, and carries forward
all protected guarantees. `removed_guarantees` must remain empty; a non-empty
value is a `BREAKING_BASELINE_CHANGE` and requires human approval rather than
automatic promotion.

## 18. Local Provider gateway boundary

`GatewayCompletionClient` is a transport adapter for the existing
`CompletionClient` contract. It may connect only to an explicitly configured
`http://127.0.0.1` API Lab gateway. The gateway's ephemeral bearer token is a
process credential and must not enter routing configuration, run snapshots,
project artifacts, logs, or repository state. Vendor API credentials remain
owned exclusively by the independent API Lab.

Agent and worker routes are Provider IDs (`qwen`, `deepseek`, or `grok`) in one
validated `CGKNModelRouting`. A run writes one immutable
`ModelRoutingSnapshot`; model output cannot modify that snapshot, select a URL,
increase a budget, or request another Provider. Automatic cross-Provider
fallback is denied. Gateway calls reserve from the existing process-safe
Provider budget ledger before transport and settle actual usage when the
gateway reports it; missing usage remains unavailable rather than becoming
zero.

The gateway gains no composition, execution, evidence, acceptance, packaging,
or delivery authority. `CapabilityTree`, `ExecutionDAG`, bounded Executor
validation, real tests, external acceptance, and the canonical delivery route
remain unchanged. When gateway mode is not explicitly enabled, the reviewed
`OpenAICompatibleClient` path remains the default.

## Bounded graph commits (ITER-088)

Ordinary `DAGRunner.run(resume=True)` requires the saved graph, including node
configuration and dependencies. `AgentProjectLoop` explicitly commits edits with
`accept_edits=True`: it may append executable nodes and change unfinished nodes.
Changing a succeeded node or its affected succeeded dependents requires the
existing explicit `retry_node` contract. Goal changes and node removals within
an existing run are rejected. This is a bounded runtime capability addition,
not a claim that arbitrary incremental edits were previously supported.

The committed DAG, graph revision and node records are atomically saved in the
canonical `RunState`. Existing definition files remain readable mirrors. A
legacy state must have its matching saved definition to be resumed; missing or
incompatible records fail closed. Attempts and unaffected successful results
are retained. A failed commit cannot authorize execution against a different
graph. No second scheduler, state store or planner is introduced.

## Rejected Agent decisions (ITER-089)

Model decision parsing and pre-execution tree-edit validation failures are
recorded verbatim and returned at the next bounded Agent decision. A rejected
edit batch commits no partial tree and executes no tools. Rejected decisions
consume the existing decision/request budget; no silent semantic repair or
extra decision allowance is introduced. Transport, store and runtime failures
are not recategorized as model syntax errors. The experiment's timeout recovery
policy is separate from this canonical decision contract.

### ITER-090 engineering DEV adapter

The optional compact Agent interface binds a selected catalog capability to its
unique executor and emits ordinary tree edits. Agent-authored summaries are
preserved; this is not a second planner or scheduler. The same canonical DAG,
executor registry and FileRunStore execute and persist all nodes. The project
loop accepts a caller-specified positive decision resource bound; the former
four-decision constructor ceiling is removed. Paid callers must enforce their
shared request/token/time/cost limits across Agent and worker calls.

Success and failure outputs enter the next Agent checkpoint. A mechanical six
result window avoids replaying all source content; the isolated engineering
adapter publishes complete own-run result references. Compact requests include
unmodified Agent action summaries and bounded raw prefixes with hashes for long
results. No host semantic context selection or business summaries are supplied.

Failed/timed-out/blocked nodes are not replayed by an ordinary continuation.
Explicit retry or validated edit invalidation is required. Successful nodes
retain the prior reuse and affected-subgraph checks. Bounded workers may read
iteratively, then return their own write/patch actions; completed outputs retain
read observations, modified paths and expected outputs. Runtime action failures
are not transactional filesystem rollback; partial effects must be inspected
before explicit retries. Entire proposal field validation precedes action use.

ITER-090 is engineering DEV with exposed feedback and versioned continuations,
not a blind benchmark or public publication route. Candidate development remains
isolated; shipping/publication continues to use the existing reviewed gates.


### Goal-driven execution time window

The normal `scripts/run_goal_driven.py` entry persists its original wall-clock
execution window in the existing FileRunStore run directory. `resume` retains
that deadline, including downtime, and cannot grant a fresh `max_seconds`.
Expired windows reject new dispatch; `status` and `report` remain available.
Missing historical windows require explicit reconciliation; no fresh window is
synthesized on resume. This is deadline accounting, not OS sandbox isolation.


### Goal-driven contract and lifecycle continuation (2026-11-12)

`GoalComposer` publishes executor fields from the same definition used by its
compiler. A failed compilation rolls back temporary local declarations. New
business actions require an explicit requirement/Gap binding or an explicit
exploration reason, budget and observable measure. Alternatives are optional.
A local batch may contain the configured number of new nodes, bounded by the
existing admission policy; the model still chooses its decomposition.

Repeated admission failures, empty blocked runs and unverified finish claims
stop after two occurrences without progress. Existing continuation history is
retained across restart.

The executable `OpenAICompatibleClient` facade has been removed. Provider callers
use `completion_client_from_environment`; absent explicit Gateway configuration
fails immediately. Historical client names in older evidence are not runtime
entries. This replaces the former compatibility execution behavior.

An admitted `remove_node` archives only a node declared `optional_strategy=true`,
with no current consumers, goal task references, running/pending work or UNKNOWN.
The existing RunState retains archived node definitions and execution records;
raw attempts remain untouched. `add_node` can restore a strategy through current
admission, but it executes anew with continued attempt numbering. It does not
inherit a historical PASS. Planner context provides readable archive references.

The normal `run_goal_driven.py extend --config <new-config>` command records an
additive user requirement revision in the same FileRunStore. Supply
`requirement_extension.parent_config_identity` from `status` and an explicit
`authority_reference`. Existing goals, requirements, inputs, models, resource
limits, source identities and deadline cannot be changed by this command.
Only new requirement IDs and a versioned completion checker/interface may be
added. The existing GoalAcceptance keeps old plans and checks; Host appends a
new goal for the added obligations. The Agent selects its next work and invokes
`goal.acceptance@1` with the appropriate `acceptance_goal_id`. Checker arguments
are frozen configuration, never Worker-provided code.

A configured `budget_ledger` is honored by both Planner feedback and actual
Provider dispatch. It must be outside the product workspace and permits a
campaign to share the existing ledger across separate projects. This does not
supply authorization or silently enlarge its limits.

These changes remain under offline qualification; no real RunLens delivery or
cross-project Skill use is implied by this description.


### RunLens continuation: dependency ownership and acceptance assembly

The Host composes GoalAcceptance through `runtime.acceptance.open_goal_acceptance`.
The existing state class remains the sole acceptance owner and requires its scoped
ExecutionAuthority for governed evidence. Direct unbound state construction cannot
produce a governed view. Existing consumers now use this assembly.
Evidence identity encodings and the OS file lock moved intact to artifact utilities;
execution no longer imports state for hashing or creates a temporary FileRunStore
just to acquire a publication lock. Offline Oracle qualification belongs to the
application; runtime telemetry does not import it. Runtime package exports are lazy
so importing the receipt authority cannot import a scheduler through __init__.
Layer declarations use the longest matching module/package prefix; reverse imports
and same-layer cycles remain errors, including narrower module declarations.
The monetary cap for the unstarted RunLens campaign is CNY20 by explicit user update;
this is a ceiling, not a spending target. Prior failed checks remain historical evidence.


### Goal-driven live source and recovery evidence (2026-11-12)

The finite CLI `scripts/run_goal_driven.py revise-sources --revision PATH` delegates to the existing FileRunStore revision/event chain. It accepts exact before/after Host source hashes only before business materialization, with unchanged configuration, checker, Core, settled ledger identity and explicit authority. It grants no business PASS and does not reset the original execution window. `resume --feedback PATH` forwards explicit redecision evidence to ProjectSession; consumed revisions, interrupted contexts and UNKNOWN safeguards remain authoritative.

Gateway input reservations use the existing exact-wire conservative bound for each request, not the full campaign input ceiling. Settlement still uses supplier usage. Real RunLens qualification remains blocked: goal_driven currently assembles HostPlanningScope with its default one-call decision permit, insufficient for a paid context-fetch exchange followed by planning. Offline qualification must not be cited as proof that this live path completes. Current source changes have affected-suite evidence; the pre-live full worktree receipt is historical after source revisions.


### In-place continuation and retired generation owners (2026-11-12)

Goal-driven planning allocates the existing protocol context allowance plus one final response, independently of Worker call limits; all calls still share the original campaign ledger. The final context turn exposes only the business response schema. Permit rejection before transport is recorded as known not sent, with the requested resource and allowed limit.

Explicit redecision advances past every immutable interrupted context. A locally rejected context protocol response closes its Permit. Recovery of an older active Permit requires the matching Host rejection event, exact planning context identity and settled request records; unresolved calls remain blocked. Source revisions can also retain failed, unmaterialized runs, but reject successful/UNKNOWN history or existing product bytes. No previous failure is rewritten or promoted.

The conversation retry/validation loop, simulator starter, direct-executor MVP baseline and ten old whole-project/component generation/repair functions have been removed. Local CLI and dynamic adapters continue delegating to SoftwareProjectGenerationService/ProjectSession. Existing post-build, typed-artifact and media/packaging helpers remain because they still have current consumers; they are not alternate generation owners. The old component-pipeline smoke script was removed. Current route guards check the session and existing finalization chain, rather than requiring the retired scheduler.

Scope evidence is reports/runlens-refactor-20261112/code-completion in the VeriArbor workspace. Historical whole-project generation tests referring to the removed APIs are inventoried separately and are not a claim of current qualification. No whole-history green status or successful RunLens delivery follows from these code changes.
