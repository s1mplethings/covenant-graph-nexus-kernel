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

## Important files

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
python -m pytest tests/test_kernel_contract.py tests/test_codex_conversation.py tests/test_codex_public_delivery_gate.py -q
```

Provider credentials are used only by the reviewed Provider route. No
conversation transport credential is required.

`CGKN_PROVIDER_PARALLELISM` defaults to 4. Normal Provider leaves, retries, and
test failures do not invoke Codex. Project problems return to Provider,
evidence problems rerun canonical verification, and only demonstrated CGKN
bugs can enter the separate governed Codex kernel-repair path.
