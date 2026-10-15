# Autonomous Project Acceptance Integration

## Scope and authority

`scripts/autonomous_project_acceptance.py` is the minimum generated-project acceptance layer for the reviewed CGKN Provider route. It does not generate a project, package a candidate, authorize formal evidence, or replace `local_packager` and the public delivery gate. Its recommendation is one of `ACCEPTED`, `REPAIR_REQUIRED`, `BLOCKED`, or `NOT_EVALUATED`; the accompanying formal evidence status remains `NOT_EVALUATED`.

The existing conversation mainline invokes it after Provider generation and the pre-seal project test run, before provenance, packaging, and delivery. An acceptance veto stops that finalization. Independently reproduced project findings may re-enter only through the existing observed-project-failure ProviderJob repair route, with a maximum of two repair rounds, followed by a complete acceptance rerun.

## Testability Contract

A generated project opts into executable acceptance with a root `testability_contract.json` conforming to `schemas/testability_contract_v1.schema.json`. When the public goal explicitly requests this file, the canonical GoalDrivenProjectPlan assigns it to the existing delivery/docs workstream; no parallel generator is created.

The contract declares:

- the public project goal and CLI, Python API, or file adapter;
- operation ids, JSON input schemas, direct argv templates, expected exit codes, and independent oracles;
- observable state files and final artifacts;
- user-task scenarios and deterministic success conditions;
- network, shell, operation-count, and timeout limits.

Every operation invokes the real business entrypoint with `shell=False`. Test-only paths, unknown operations, schema-invalid arguments, absolute output paths, drive-qualified paths, and parent traversal are rejected before queue admission. Unsupported proposals are recorded and never silently mapped to another operation.

## Execution and evidence

The default run combines deterministic contract scenarios with one semantic model call. Additional semantic rounds remain disabled. The runner copies the candidate to isolated source and execution workspaces, preserves full raw observations, emits compressed observations with an evidence-loss audit, applies deterministic exit/output/state/artifact oracles, and reproduces every finding in another fresh copy.

The report is `autonomous_acceptance_report.json`, validated by `schemas/autonomous_project_acceptance_report_v1.schema.json`. Raw execution is saved separately as `raw_execution.json`; independently confirmed failures also produce `observed_project_failure.json` and per-finding reproduction traces.

Programmatic use:

```python
from scripts.autonomous_project_acceptance import run_acceptance

report = run_acceptance(
    project_dir="path/to/generated-candidate",
    run_dir="path/to/isolated-acceptance-run",
    public_goal="The project's public goal",
    model="qwen3.5-flash",
)
```

The model is replaceable through the existing Pass 3 `ModelClient` contract. Model receipts record provider, model, token counts, duration, and configured cost when available.

## 2026-10-14 real closure trial

The reviewed `codex_surrogate` generation route created a new Pocket Expense Ledger candidate with atomic `ledger.json` persistence, add/list/summary CLI operations, tests, documentation, and a v1.0 Testability Contract. The generated regression test passed (`1 passed`), and an isolated acceptance rerun executed eight real operations with one model call (684 tokens, 3.96 seconds) and returned recommendation `ACCEPTED`, formal status `NOT_EVALUATED`, zero findings, zero invalid executions, and no repair round. A separate clean usability copy then ran two `add` commands, `list --json`, and `summary --out summary.json`; the persisted ledger contained both records and the final artifact reported `count=2`, `total=20`, `food=12.5`, and `travel=7.5`.

The first isolated acceptance run exposed an acceptance-runner isolation bug: a semantic proposal supplied an absolute `--out` path and was executed because a plain string schema admitted it. The attempted external write was denied by the operating system. CGKN now rejects declared output/path arguments that are absolute, drive-qualified, or contain parent traversal before execution. A regression test covers this boundary. This was a validator repair, not a customer-project repair, and no Oracle or public goal was weakened.

The full generation process did not reach packaging or public delivery during this trial. Before the new acceptance hook, the existing post-build path stopped making progress after the split semantic-review aggregate exceeded its context budget (`110850` prompt characters against `56000`) and `post_build_finalize` began. No autonomous-acceptance artifact was created inside that production run, and no delivery manifest was issued. Therefore the auditable end-to-end integration result is `BLOCKED`, while the candidate's separately isolated acceptance recommendation is `ACCEPTED`. These facts must not be conflated.

## Current decision

Continue development only on the narrow mainline blocker: make the existing split semantic-review/post-build transition bounded and resumable, then rerun the same new-project closure. Do not add Persona, GUI, HTTP, or another generation framework. Until one production run automatically reaches the acceptance report and delivery gate, CGKN cannot claim unattended generate-and-accept closure.

The unrelated historical `max_tokens` assertion failure remains a separately recorded baseline and was not changed or counted as this integration's result.
