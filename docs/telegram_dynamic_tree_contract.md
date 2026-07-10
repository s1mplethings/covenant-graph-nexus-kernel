# Telegram / Dynamic Tree Contract

## Current status

Telegram mainline is not directly connected to the Dynamic Agent Tree evaluation lane. `telegram_mainline_not_connected` is an expected contract state for Dynamic Real Project evidence.

## Why this is intentional

Telegram is the frontdesk and public delivery surface. Dynamic Tree is the formal project generation runner. They must not be implicitly coupled through the legacy provider pipeline. The existing `pipeline_manifest` and `dynamic_pipeline_runner` support lane does not replace Telegram's reviewed default generation and delivery route.

## Allowed path

```text
telegram session / whiteboard
 -> explicit adapter contract
 -> dynamic tree manifest
 -> run_dynamic_pipeline
 -> delivery_manifest
 -> public_delivery_gate
 -> emit_public_delivery
```

Any explicit adapter must preserve `agent_session`, whiteboard communication, `local_packager` as the delivery exit, and the public gate.

## Forbidden shortcuts

- Telegram must not call the legacy provider pipeline as formal generation.
- Telegram must not bypass `public_delivery_gate`.
- Telegram must not send an internal manifest, local path, or raw JSON as final user delivery.
- Dynamic Tree must not depend on Telegram runtime or token.

## Future integration rule

Only an explicit adapter with tests may connect Telegram to Dynamic Tree. Until then, `telegram_mainline_not_connected` remains expected for the evaluation lane, and no support-lane call may silently become the Telegram default public delivery route.
