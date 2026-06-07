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
7. Using a CFO-controlled module plan inside `pipeline_manifest`: the `cfo` role owns module planning, handoff order, acceptance interpretation, evidence review, and delivery readiness.
8. Allowing CFO support agents only inside the manifest as advisory context/risk maintainers, such as a context database and risk register. Support agents do not own scope, route, implementation authority, or final delivery readiness.
9. Executing project work through `dynamic_pipeline_runner`, which only interprets the `pipeline_manifest`.
10. Using `local_agent_actions` and `local_agent_skills` as the only tool execution boundary.
11. Using `local_packager.package_project` as the only formal delivery exit.
12. Treating `delivery_manifest.json` as the evidence that delivery packaging completed.
13. Allowing `dynamic_pipeline_runner` to recover complete actions from malformed or truncated agent JSON only inside the same manifest step, record the parse failure, and require a repair turn before that step can pass.
14. Allowing configured local models only as a model-source optimization. By default, local models may write public frontdesk/status replies only; generation-affecting local tasks such as backend dialogue, planner, CFO planning, context support, risk support, foundation, or QA must be explicitly enabled and must remain inside the same manifest/runner/evidence boundary.
15. Recording critical setup questions for any explicitly required external, local, hosted, data, model, automation, security, storage, or runtime capability. These questions are shared context and acceptance constraints, not a new gate or generation route.
16. Recording a project-level capability strategy for core capabilities, advanced-method candidates, obvious route differences, and acceptance limits. This is universal planning context for the same manifest/runner flow, not a project-type-specific generator.
17. Requiring every formal `pipeline_manifest` to cover Product Studio evidence stages: `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`.
18. Auditing quality evidence before `package_project`, including `TEST_REPORT.md` and `DELIVERY_NOTES.md`, and recording missing evidence as warnings instead of hiding it.
19. Waiting for explicit user start confirmation when backend dialogue finds soft questions, critical questions, missing required inputs, or complex/high-uncertainty domains. These questions are not hard gates once the user explicitly starts; they become assumptions and delivery warnings.

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
10. Count any fallback preview, placeholder, stub, procedural substitute, simulated result, or basic implementation as satisfying an explicitly requested core capability that requires a mature method, configured model, external API, local service, data source, automation engine, or runtime evidence.
11. Encode a project type, industry, object, or domain label as a special formal generation path. Domain labels may only help infer underlying capabilities; the manifest/runner route remains universal.
12. Automatically start complex or under-specified project generation merely because soft questions are non-blocking. Non-blocking means the user may explicitly start with assumptions, not that the system starts by itself.

## Stable Flow

```text
Telegram
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> pipeline_planner_agent
-> pipeline_manifest
-> Product Studio stages: product_plan / technical_plan / build / test / review / package
-> cfo module plan / support context database and risk register / specialist agent handoffs
-> dynamic_pipeline_runner
-> local_agent_actions / local_agent_skills
-> local_packager
-> delivery_manifest.json
```

The kernel is stable. The pipeline is agent-generated per project. The project itself is fully generated inside the bounded project directory. Skills are controlled capability modules. The whiteboard is the shared communication surface between intake, planning, generation, and delivery.

## Consolidated Kernel Rule

CGNK Kernel does not contain a fixed project generation pipeline. CGNK Kernel requires every formal generation run to first produce a `pipeline_manifest`.

The `pipeline_manifest` is agent-generated from `whiteboard` and `agent_session`. `dynamic_pipeline_runner` interprets that manifest through `local_agent_actions` and `local_agent_skills`.

The default manifest shape is CFO-controlled and Product Studio disciplined: `product_plan -> technical_plan -> build -> test -> review -> package_project`. A step may merge stages when appropriate, but the manifest must still cover `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`. The planning stages must produce `PRODUCT_PLAN.md`, `OUTPUT_CONTRACT.md`, `TECHNICAL_PLAN.md`, and `BUILD_PLAN.md`; QA must produce `TEST_REPORT.md`; review must produce `DELIVERY_NOTES.md`; and `package_project` remains the only delivery exit. Specialist agents may build modules, and support agents may maintain `CFO_CONTEXT_DB.json` or `CFO_RISK_REGISTER.md`, but they do not own the formal route or final delivery readiness.

Before packaging, `dynamic_pipeline_runner` must audit quality evidence. Missing `TEST_REPORT.md` or `DELIVERY_NOTES.md` may be repaired once with an honest warning artifact, but packaging cannot hide the gap. `local_packager` records `quality_evidence` in `delivery_manifest.json`, and Telegram delivery replies must summarize whether test report, review notes, and preview evidence exist.

When an agent reply is malformed or truncated, the runner may salvage fully closed actions and execute them, but it must keep the step in repair until strict JSON succeeds. This is parser resilience inside the current manifest step, not a separate generation path.

Local-model routing may reduce provider cost for low-risk tasks. Public reply tasks must not alter `whiteboard`, `pipeline_manifest`, generation actions, or delivery readiness. Generation-affecting local tasks must be opt-in and must stay inside the same `pipeline_manifest` and `dynamic_pipeline_runner` boundary. They must not bypass manifest validation, `local_agent_actions`, `local_packager`, or final delivery evidence.

Configured local models do not create a new formal generation path.

Critical setup questions, such as a missing model service, unavailable API credential, absent data source, storage choice, automation engine, runtime target, or security boundary, may be recorded in `critical_questions` and `open_questions`. They do not block the manifest/runner flow, but they must be reflected in acceptance criteria so fallback output is not misreported as satisfying the requested capability.

Telegram intake uses `should_auto_start_generation` before starting formal generation from a new project request, project update, or attachment. If `needs_direction_confirmation`, `soft_questions`, `critical_questions`, `missing_required_inputs`, a complex/high-uncertainty domain, or low confidence is present, intake records `generation_start_waiting` and waits. If the user explicitly says to start, unanswered questions and missing inputs are written into `generation_context_snapshot` as assumptions and warnings; outputs with missing real inputs must be partial/scaffold evidence, not full validation.

Capability strategy fields such as `capability_strategy` and `capability_research_targets` guide CFO planning and support agents for every project. They must describe underlying capabilities and advanced-method candidates, not project-type-specific branches. They do not authorize legacy pipelines, arbitrary execution, or bypassing manifest validation.

Fallback to a single agent loop is allowed only when pipeline planning or runner execution fails, and it must record `pipeline_fallback`.

## Legacy Code Policy

Legacy provider pipeline code must not live inside `telegram_live_bridge.py`.

Legacy CLI may exist only under `legacy/` or as a thin wrapper.

Telegram formal generation must never call legacy provider pipeline, `generate_project.py`, `run_local_pipeline`, or `simulator`.

Old `BLOCKED` and gate terminology must not be user-visible.

`backend_controls` are compatibility logs only, never execution queues.
