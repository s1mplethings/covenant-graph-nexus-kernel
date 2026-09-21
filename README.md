# CGKN Codex Edition

CGKN Codex Edition is operated only through the Codex conversation in this
workspace. There is no standalone chat listener, polling service, secondary
customer UI, or external messaging delivery adapter.

## Use

Open this repository in Codex and describe the project or change you want. The
active Codex task is the sole user-facing interaction surface. Uploaded files,
status updates, review decisions, previews, and final local artifact links all
remain in that task.

The production generation route remains:

```text
Codex conversation
-> requirements and whiteboard/agent_session state
-> Provider Planner API and minimal ProviderJob DAG
-> parallel isolated Provider work, ownership check, deterministic merge
-> Provider integration/semantic repair
-> Provider output validation
-> post-build finalization
-> canonical test/runtime/visual evidence as applicable
-> sparse read-only Codex False-Pass audit at positive checkpoints
-> user review in the active Codex task when required
-> local_packager
-> public_delivery_gate
-> delivery_manifest.json and conversation-bound delivery receipt
-> Codex result with local artifact links
```

`local_packager` is the only delivery exit. `pipeline_manifest` and
`dynamic_pipeline_runner` remain support/experimental planning components and
must not become a second production or delivery route.

## Artifact-driven pipeline kernel (v0.3 capability)

CGKN includes an additive local artifact-runtime lane for typed, incremental
module execution. Feed-forward means that a validated output
`ArtifactInstance` becomes a downstream module's typed input; replaying the
whole conversation is not feed-forward.

The reference flow is `flow.artifact_driven_project_refactor@1`. It provides
immutable artifact history and `ArtifactRef` identities, deterministic hashes
and provenance, module-scoped context projections and budgets, local execution
fingerprints and cache, lineage, stale marking, affected-only invalidation,
effect cardinality, and ref-only checkpoints.

```text
python scripts/demo_artifact_recompute.py --run-dir runs/artifact-v03-demo --json
python scripts/artifact_lineage.py --run-dir runs/artifact-v03-demo --artifact ai.delivery-judgment.002
python scripts/explain_flow.py --flow flow.artifact_driven_project_refactor@1
```

The Todo demo shows an unchanged project snapshot cache hit while
requirement-dependent descendants recompute. This lane does not replace the
reviewed Provider generation mainline, canonical evidence producers,
`local_packager`, or the public delivery gate. See
`docs/artifact-driven-migration.md` for migration and compatibility details.

## Important files

- `cgkn/` — typed Artifact Kernel source: artifact models, compiler, and runtime.
- `specs/` — authoritative machine-readable Artifact, Module, Flow, Policy,
  Migration, and Context Pack registry.
- `schemas/` and `contracts/` — JSON schemas and stable interface contracts.
- `examples/` — small human-readable inputs and expected summaries only.
- `evidence/` — curated claims, metrics, hashes, reproduction commands, and
  known limits; raw runs are excluded.
- `tests/fixtures/` — small deterministic test-only fixtures.
- `scripts/codex_conversation.py` — import-only conversation orchestration,
  generation entry, guarded replies, evidence gates, and delivery handoff.
- `scripts/provider_jobs.py` — minimal deterministic DAG executor and PatchSet ownership boundary.
- `scripts/cgkn_runtime_supervisor.py` — persistent read-only False-Pass Auditor host.
- `scripts/cgkn_supervision_router.py` — deterministic project/evidence/kernel routing.
- `scripts/governed_kernel_repair.py` — isolated allowlisted kernel-repair execution.
- `scripts/local_packager.py` — sole package and delivery exit.
- `docs/00_kernel_contract.md` — kernel invariants.
- `docs/01_contract_registry.md` — authoritative formal artifact registry.
- `docs/14_codex_cgkn_runtime_supervision_baseline.md` — runtime ownership.

## Verification

```powershell
python scripts/kernel_contract_check.py
python scripts/validate_bundle.py --root . --schema
python scripts/repository_hygiene.py
python -m pytest tests/test_kernel_contract.py tests/test_codex_conversation.py tests/test_codex_public_delivery_gate.py -q
```

Local output belongs under ignored `runs/`, `artifacts/`, `generated/`, or
`workspaces/`. Promote a durable claim with `scripts/promote_evidence.py`; do
not commit complete run workspaces or live `.cgkn` state. See
`docs/repository_guide.md` for the retention model.

Provider credentials are used only by the reviewed Provider route. No
conversation transport credential is required.

`CGKN_PROVIDER_PARALLELISM` defaults to 4. Normal Provider leaves, retries, and
test failures do not invoke Codex. Project problems return to Provider,
evidence problems rerun canonical verification, and only demonstrated CGKN
bugs can enter the separate governed Codex kernel-repair path.
