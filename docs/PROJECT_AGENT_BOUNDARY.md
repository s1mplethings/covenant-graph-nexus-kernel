# Project Agent Boundary

Status: revised design direction. Implemented and unit-tested in the Host; it is
not yet evidence of end-to-end benefit.

## Layers

- **Layer A — Project Agent** (replaceable): OpenCode, Codex, SuperAgent, or the
  `EmbeddedProjectAgent` fallback. It reads the project, proposes the next
  operation, selects a resource preference and explains the expected progress.
- **Layer B — VeriArbor Kernel**: `CapabilityTree`, `TreeEdit`, leaf contracts,
  effects, admission, `GoalAcceptance`, `FileRunStore`, impact/invalidation,
  execution progress, budget/UNKNOWN, lifecycle.
- **Layer C — Executors**: deterministic tools, existing capabilities, API/model
  workers.

## Proposal flow

```
Project Agent
  -> ProjectProposal
  -> admit_proposal()
  -> ADMITTED | structured rejection
  -> TreeEdit
  -> authoritative CapabilityTree
```

`ProjectProposal` lives in `cgkn/agent/project_agent.py`. The external bridge is
a file (`project_agent_proposal.json`) loaded by `ExternalFileProjectAgent`; no
network service or second RPC stack is introduced.

Admission checks, at minimum:

- `base_tree_version` equals the current version;
- incremental mode admits one new frontier node per proposal;
- capability is in the current catalog;
- node identity and dependencies resolve;
- the leaf contract exists and its effect domains are allowed;
- remote external effects are rejected unless explicitly admitted;
- a blocked budget rejects new model resources.

Rejections are structured (`STALE_BASE_TREE_VERSION`, `UNKNOWN_CAPABILITY`,
`INVALID_DEPENDENCY`, `INCREMENTAL_LIMIT`, `BUDGET_BLOCKED`, ...) so the Project
Agent can replan from the real reason.

## Execution progress

`cgkn/agent/progress.py` classifies every attempt:

`SUCCESS`, `PROGRESS`, `NO_PROGRESS`, `REGRESSION`, `PROTOCOL_REPAIRABLE`,
`BUSINESS_REPAIRABLE`, `INFRA_BLOCKED`, `BUDGET_BLOCKED`, `UNKNOWN`.

Fingerprints combine node strategy, failure identity, relevant artifact and
evidence delta. Repeated identical attempts are quarantined instead of being
retried indefinitely. Budget denial stops the project before another planner
call; it is never rewritten as a business failure. Transport failures remain
`INFRA_BLOCKED`, not model-capability evidence.

## Worker protocol

- `LLMExecutor` supports bounded multi-round read/write work (default 4), stops
  after two identical read-only rounds, and records the local no-progress reason.
- A schema rejection whose business actions are intact is repaired only at the
  protocol envelope; the filled fields are recorded and the actions are
  preserved. Missing business actions are not invented.
- Writing tasks that return no action are blocked; inspection tasks may return
  an empty action list and are judged by their independent checker.

## Authorities preserved

`DAGRunner`, `FileRunStore`, `GoalAcceptance`, the provider budget ledger and
recovery remain the only execution, state and acceptance authorities. The
refactor adds no second scheduler, DAG runtime, store, budget ledger or
acceptance authority.
