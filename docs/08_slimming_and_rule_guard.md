# CGNK Slimming and Rule Guard

This document freezes the cleanup direction for CGNK so the repo can become smaller without weakening the Telegram delivery path.

## One Default Route

Telegram default generation has one reviewed route:

```text
Telegram intake
-> agent_session / whiteboard
-> API/provider project generation
-> provider output validation
-> post-build finalization
-> local_packager
-> public_delivery_gate
-> delivery_manifest.json
```

`pipeline_manifest` and `dynamic_pipeline_runner` remain a support/experimental planning lane. They must not become a second public delivery route unless the kernel contract and tests are updated together.

## Slimming Rules

1. Keep `telegram_live_bridge.py` as a bridge: Telegram intake, session persistence, generation dispatch, user-visible delivery, and guarded replies only.
2. Move project/domain-specific repair logic into skills, adapters, or legacy modules. Do not keep adding one-off generated-project hotfixes to the bridge.
3. Public delivery must send only user-facing package/media artifacts by default. Internal reports, manifests, ledgers, logs, and Markdown files stay in the evidence bundle unless explicitly requested.
4. Any new fallback must record `pipeline_fallback`, must stay behind validation, and must pass `local_packager` plus `public_delivery_gate` before user delivery.
5. If a change increases bridge size or adds domain labels as a route decision, add or update a guard test in the same commit.

## Cleanup Order

1. Freeze route terms in `AGENTS.md`, `docs/00_kernel_contract.md`, and guard tests.
2. Extract bridge helpers into focused modules: Telegram transport, session store, public delivery assets, provider route, and post-build finalizers.
3. Move generated-project compatibility patches into capability skills or adapters.
4. Delete stale wrappers only after tests prove no Telegram path calls them.

Run:

```bash
python scripts/cgnk_slim_rule_guard.py
python scripts/cgnk_slim_rule_guard.py --json
```
