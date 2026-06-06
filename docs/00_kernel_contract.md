# CGNK Kernel Contract

This contract defines the stable kernel boundary for CovenantGraph Nexus Kernel. Future changes may add capabilities around the kernel, but they must not replace the generation mainline or bypass the safety and delivery boundaries described here.

## Kernel Responsibilities

CGNK Kernel is fixed responsible for:

1. Telegram entry for user project intake and generation confirmation.
2. `agent_session.jsonl` persistence for user messages, backend dialogue events, planner events, runner actions, and tool results.
3. `whiteboard` as the shared state surface for frontdesk, backend dialogue, planner agent, and generation agents.
4. `backend_dialogue_loop` as lightweight analysis and whiteboard update only; it is not a gate.
5. Generating a `pipeline_manifest` after the user confirms generation and before project generation runs.
6. Producing `pipeline_manifest` through `pipeline_planner_agent` from the current `whiteboard` and `agent_session`.
7. Executing project work through `dynamic_pipeline_runner`, which only interprets the `pipeline_manifest`.
8. Using `local_agent_actions` and `local_agent_skills` as the only tool execution boundary.
9. Using `local_packager.package_project` as the only formal delivery exit.
10. Treating `delivery_manifest.json` as the evidence that delivery packaging completed.

## Kernel Prohibitions

CGNK Kernel must not:

1. Reconnect the Telegram formal generation mainline to `generate_project.py`.
2. Reconnect the Telegram formal generation mainline to `run_local_pipeline`.
3. Restore `simulator` as the formal generation mainline.
4. Turn `backend_controls` back into an execution queue.
5. Treat `blocking_questions` or `soft_questions` as a hard gate for generation.
6. Allow `pipeline_manifest` to execute arbitrary Python.
7. Allow generation agents to modify CGNK kernel files.
8. Bypass `local_packager` or forge delivery completion.
9. Enter a fixed project generation flow without first recording a `pipeline_manifest`, except when an explicit `pipeline_fallback` event is recorded.

## Stable Flow

```text
Telegram
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> pipeline_planner_agent
-> pipeline_manifest
-> dynamic_pipeline_runner
-> local_agent_actions / local_agent_skills
-> local_packager
-> delivery_manifest.json
```

The kernel is stable. The pipeline is agent-generated per project. The project itself is fully generated inside the bounded project directory. Skills are controlled capability modules. The whiteboard is the shared communication surface between intake, planning, generation, and delivery.

## Consolidated Kernel Rule

CGNK Kernel does not contain a fixed project generation pipeline. CGNK Kernel requires every formal generation run to first produce a `pipeline_manifest`.

The `pipeline_manifest` is agent-generated from `whiteboard` and `agent_session`. `dynamic_pipeline_runner` interprets that manifest through `local_agent_actions` and `local_agent_skills`.

Fallback to a single agent loop is allowed only when pipeline planning or runner execution fails, and it must record `pipeline_fallback`.

## Legacy Code Policy

Legacy provider pipeline code must not live inside `telegram_live_bridge.py`.

Legacy CLI may exist only under `legacy/` or as a thin wrapper.

Telegram formal generation must never call legacy provider pipeline, `generate_project.py`, `run_local_pipeline`, or `simulator`.

Old `BLOCKED` and gate terminology must not be user-visible.

`backend_controls` are compatibility logs only, never execution queues.
