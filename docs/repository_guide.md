# CGKN Repository Guide

This guide defines the Repository Layout v1 retention model. It does not replace
`AGENTS.md`, `docs/00_kernel_contract.md`, or the formal registry in
`docs/01_contract_registry.md`.

## Directory responsibilities

| Area | Responsibility | Retention |
| --- | --- | --- |
| `cgkn/`, `src/`, `scripts/` | Kernel and reviewed operational source | Track reviewed source and tests. |
| `specs/` | Formal machine Artifact, Module, Flow, Policy, Migration, and Context Pack definitions | Authoritative registry; loaders read it first. |
| `schemas/`, `contracts/` | Schemas and stable interface contracts | Track reviewed contracts. |
| `examples/` | Small inputs and expected summaries a user can read and reproduce | Never store live memory, Provider output, checkpoints, caches, or generated copies. |
| `tests/fixtures/` | Small, deterministic, purpose-specific test data | Track only fixtures required by tests. |
| `benchmarks/` | Case definitions, evaluators, runners, and small fixtures | Write executions to `runs/benchmarks/`; promote durable results to `evidence/benchmarks/`. |
| `evidence/` | Curated claim, formal status, metrics, hashes, test result, reproduction command, and known limits | Keep bundles small; no raw Provider responses or complete workspaces. |
| `project_management/current/` | Current backlog, risks, active iteration, and reusable experience | Support planning only; cannot authorize formal delivery. |
| `project_management/summaries/` | Version-level capability, decision, failure, evidence, risk, and commit summaries | Detailed iteration history remains in Git history. |
| `plugins/`, `skills/`, `tools/` | Reviewed integrations and operating methods | Track source and small deterministic tests only. |
| `legacy/` | Isolated compatibility code | Do not reconnect to the production mainline. |
| `runs/` | Local run manifests, artifact indexes, checkpoints, cache, and reports | Ignored runtime only. |
| `artifacts/` | Raw run artifacts and diagnostics | Ignored runtime only. |
| `generated/` | Generated customer output | Ignored runtime only. |
| `.cgkn/`, `workspaces/` | Live local state and work areas | Ignored local state; never commit. |

The boundary is explicit:

```text
Source != Spec != Example != Evidence != Runtime

Runtime -> Promotion -> Curated Evidence -> Git
```

## Formal spec migration

Formal definitions formerly stored under `examples/artifacts`,
`examples/modules`, `examples/flows`, `examples/policies`, and
`examples/migrations` now live under matching `specs/` directories. Internal
loaders are specs-first. A deprecated examples fallback exists only for older
external workspaces; it emits a warning and must not receive new definitions.

## Evidence promotion

Promote only a bounded summary from a local run:

```powershell
python scripts/promote_evidence.py `
  --run-dir runs/<run-id> `
  --output evidence/<category>/<version> `
  --claim "bounded claim" `
  --status PASS_WITH_LIMITS `
  --reproduction-command "python ..."
```

Promotion excludes caches, complete artifacts, checkpoints, raw Provider
responses, duplicate generated files, and raw logs. A curated bundle is support
evidence and cannot replace canonical evidence, `local_packager`, or delivery
authority.

## Cleanup and hygiene

Audit and preview cleanup without changing files:

```powershell
python scripts/repository_cleanup.py --audit
python scripts/repository_cleanup.py --dry-run
python scripts/repository_hygiene.py --json
```

`--apply` is branch-restricted and performs `git mv` plus `git rm --cached`;
it does not delete local runtime data. Repository hygiene fails on tracked raw
runtime, live `.cgkn` state, runtime data under examples, files over 10 MB
unless allowlisted, and missing navigation/ignore boundaries. Files over 2 MB,
evidence bundles over 5 MB, and example bundles over 5 MB are warnings.

## Validation

```powershell
python scripts/validate_bundle.py --root . --schema
python scripts/repository_hygiene.py
python -m pytest tests/test_artifact_driven_kernel.py tests/test_kernel_contract.py tests/test_repository_hygiene.py -q
```
