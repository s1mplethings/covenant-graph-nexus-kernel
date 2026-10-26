# CGNK Slimming and Rule Guard

This document freezes the subtraction direction for CGNK without weakening the Codex conversation delivery path.

## One Default Route

Codex conversation default generation has one reviewed route:

```text
Codex conversation intake
-> agent_session / whiteboard
-> Provider Planner API
-> deterministic ProviderJob DAG scheduler
-> parallel isolated Provider outputs / PatchSets
-> ownership check and deterministic merge
-> Provider integration and semantic repair when needed
-> provider output validation
-> post-build finalization
-> canonical verification/evidence
-> sparse Codex False-Pass audit at positive checkpoints only
-> local_packager
-> delivery_fact_check
-> agent_delivery_judgment (`public_delivery_gate` compatibility wrapper)
-> delivery_manifest.json
```

`pipeline_manifest` and `dynamic_pipeline_runner` remain a support/experimental planning lane. They must not become a second public delivery route unless the kernel contract and tests are updated together.

## Slimming Rules

1. Keep `codex_conversation.py` as a bridge: Codex conversation intake, session persistence, generation dispatch, user-visible delivery, and guarded replies only.
2. Move project/domain-specific repair logic into skills, adapters, or legacy modules. Do not keep adding one-off generated-project hotfixes to the bridge.
3. Public delivery must send only user-facing package/media artifacts by default. Internal reports, manifests, ledgers, logs, and Markdown files stay in the evidence bundle unless explicitly requested.
4. Any new fallback must record `pipeline_fallback`, stay behind validation, and pass `local_packager`, factual checking, and adaptive delivery judgment before user delivery.
5. If a change increases bridge size or adds domain labels as a route decision, add or update a guard test in the same commit.
6. Customer-project semantic repair always returns to Provider; kernel code may only perform generic deterministic infrastructure work.
7. Ordinary Provider failures, leaf completion, test failures, and API retries cannot emit a Codex audit checkpoint.
8. The guard protects one canonical audit action model, deterministic routing, ProviderJob ownership, and the local-packager-only exit; it does not protect retired `advise`, pre-generation Codex gating, or project-specific compatibility patches.

## Cleanup Order

1. Freeze route terms in `AGENTS.md`, `docs/00_kernel_contract.md`, and guard tests.
2. First reduce authority and call-graph edges; extract bridge helpers only after the mainline is green.
3. Delete or isolate generated-project compatibility patches after their call sites route to Provider.
4. Delete stale wrappers only after tests prove no Codex conversation path calls them.

Run:

```bash
python scripts/cgnk_slim_rule_guard.py
python scripts/cgnk_slim_rule_guard.py --json
```
