# CGNK Kernel Contract

This contract defines the stable kernel boundary for CovenantGraph Nexus Kernel. Future changes may add capabilities around the kernel, but they must not replace the generation mainline or bypass the safety and delivery boundaries described here.

## Kernel Responsibilities

CGNK Kernel is fixed responsible for:

1. Telegram entry for user project intake and generation confirmation.
2. `agent_session.jsonl` persistence for user messages, backend dialogue events, planner events, runner actions, and tool results.
3. `whiteboard` as the shared state surface for frontdesk, backend dialogue, planner agent, and generation agents.
4. `backend_dialogue_loop` as lightweight analysis and whiteboard update only; it is not a gate.
5. Running Telegram default project generation through API/provider project generation, post-build finalization, `local_packager`, then public delivery gate.
6. Keeping `pipeline_manifest`, `pipeline_planner_agent`, and `dynamic_pipeline_runner` as a support/experimental planning lane, not the Telegram default final project generator.
7. Using a CFO-controlled module plan inside `pipeline_manifest` when the support lane is explicitly used: the `cfo` role owns module planning, handoff order, acceptance interpretation, evidence review, and delivery readiness.
8. Allowing CFO support agents only inside the manifest as advisory context/risk maintainers, such as a context database and risk register. Support agents do not own Telegram default project generation, final route, implementation authority, or final delivery readiness.
9. Treating planning-only outputs such as `PRODUCT_PLAN.md`, `MODULE_PIPELINE.md`, `CFO_CONTEXT_DB.json`, `README.md`, or `TEST_REPORT.md` as planning/support artifacts unless provider project generation plus post-build finalization produces a runnable project surface and evidence.
10. Using `local_agent_actions` and `local_agent_skills` as the only tool execution boundary.
11. Using `local_packager.package_project` as the only formal delivery exit.
12. Treating `delivery_manifest.json` as the evidence that delivery packaging completed.
13. Allowing `dynamic_pipeline_runner` to recover complete actions from malformed or truncated agent JSON only inside the same manifest step, record the parse failure, and require a repair turn before that step can pass.
14. Allowing configured local models only as a model-source optimization. By default, local models may write public frontdesk/status replies only; generation-affecting local tasks such as backend dialogue, planner, CFO planning, context support, risk support, foundation, or QA must be explicitly enabled and must remain inside the same manifest/runner/evidence boundary.
15. Recording critical setup questions for any explicitly required external, local, hosted, data, model, automation, security, storage, or runtime capability. These questions are shared context and acceptance constraints, not a new gate or generation route.
16. Recording a project-level capability strategy for core capabilities, advanced-method candidates, obvious route differences, and acceptance limits. This is universal planning context for the same manifest/runner flow, not a project-type-specific generator.
17. Wrapping Telegram user-facing narration in an action-based public expression layer. Public replies may describe what will be built, why input is needed, how testing works, what evidence will be shown, and how the user can continue or revise; this does not create a new formal generation path.
17. Requiring every formal `pipeline_manifest` to cover Product Studio evidence stages: `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`.
18. Auditing quality evidence before `package_project`, including `TEST_REPORT.md` and `DELIVERY_NOTES.md`, and recording missing evidence as warnings instead of hiding it.
19. Waiting for explicit user start confirmation when backend dialogue finds soft questions, critical questions, missing required inputs, or complex/high-uncertainty domains. These questions are not hard gates once the user explicitly starts; they become assumptions and delivery warnings.
20. Running a Telegram public delivery gate before any intermediate or final public delivery. README-only/docs-only output, missing runnable entrypoints, missing real test commands, `NO TEST EXECUTED`, or missing requested screenshots/images/videos must force rework instead of public delivery. Final delivery also requires a project zip.
21. Sending only user-facing media/package artifacts by default in Telegram public delivery: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.mp4`, `.webm`, and `.zip`. Internal `.md`, `.json`, `.txt`, `.log`, manifest, report, and ledger artifacts stay inside the evidence bundle unless explicitly requested.
22. Auditing build completion before a build step can pass. A worker build step must not report `pipeline_step_result.status=ok` unless it produced a real runnable project surface, including `app.py` or `main.py`, dependency metadata such as `requirements.txt` or `pyproject.toml`, source files, tests, and required visual evidence.
23. Auditing QA completion before a QA/test step can pass. If `TEST_REPORT.md` contains `NO TEST EXECUTED` or does not list real test commands, the step must be `rework_blocked`, not `ok`.

## Kernel Prohibitions

CGNK Kernel must not:

1. Reconnect the Telegram formal generation mainline to `generate_project.py`.
2. Reconnect the Telegram formal generation mainline to the raw `run_local_pipeline.py` CLI or any route that bypasses provider output validation, post-build finalization, `local_packager`, or the public delivery gate.
3. Restore `simulator` as the formal generation mainline.
4. Turn `backend_controls` back into an execution queue.
5. Treat `blocking_questions` or `soft_questions` as a hard gate for generation.
6. Allow `pipeline_manifest` to execute arbitrary Python.
7. Allow generation agents to modify CGNK kernel files.
8. Bypass `local_packager` or forge delivery completion.
9. Treat `agent_generated_pipeline` or CFO document outputs as Telegram default final project generation.
10. Count any fallback preview, placeholder, stub, procedural substitute, simulated result, or basic implementation as satisfying an explicitly requested core capability that requires a mature method, configured model, external API, local service, data source, automation engine, or runtime evidence.
11. Encode a project type, industry, object, or domain label as a special formal generation path. Domain labels may only help infer underlying capabilities; provider project generation remains universal.
12. Automatically start complex or under-specified project generation merely because soft questions are non-blocking. Non-blocking means the user may explicitly start with assumptions, not that the system starts by itself.
13. Treat internal reports, manifests, ledgers, or README-only folders as user-facing delivery results.

## Stable Flow

```text
Telegram
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> API/provider project generation
-> provider output validation
-> provider project files written
-> post_build_finalize
-> tests, image/screenshot evidence, runtime artifacts
-> local_packager
-> delivery_manifest.json
```

The kernel is stable. The pipeline is agent-generated per project. The project itself is fully generated inside the bounded project directory. Skills are controlled capability modules. The whiteboard is the shared communication surface between intake, planning, generation, and delivery.

## Consolidated Kernel Rule

CGNK Telegram default generation uses API/provider project generation as the formal project-file generator. The provider route must write real project files, validate provider output, run post-build finalization, package through `local_packager`, and pass Telegram public delivery gate before sending anything public.

API/provider detection remains required operational support. `CGKN_OPENAI_API_KEY` may be read from the environment, `gpt-4.1-mini` smoke tests may call `https://api.gptsapi.net/v1/chat/completions`, and retryable provider transport errors such as `SSLError`, `SSLV3_ALERT_BAD_RECORD_MAC`, timeouts, connection resets, 502, 503, 504, or empty responses must be retried before declaring REWORK. Provider support must not write API keys to logs or project files, and must not create fake delivery assets after retry exhaustion.

The `pipeline_manifest` is retained as an agent-generated support/experimental lane from `whiteboard` and `agent_session`. `dynamic_pipeline_runner` may interpret that manifest through `local_agent_actions` and `local_agent_skills`, but Telegram default generation must not treat CFO documents alone as final project generation.

Post-build finalization is part of the provider route. If `tests/` exists it must run `python -m pytest tests` and write `TEST_REPORT.md` with `commands_run`, `exit_code`, stdout summary, and stderr summary. If requested screenshots or generated images are missing, it must attempt to collect or generate `screenshots/app_home.png`, `assets/generated/background_*.png`, `assets/generated/sprite_*.png`, and `generated_image_manifest.json`. Placeholder, blank, or pure-color images must not satisfy requested background or sprite evidence. Packaging must create `final_project_bundle.zip`, then rerun public delivery gate.

The default manifest shape is CFO-controlled and Product Studio disciplined: `product_plan -> technical_plan -> build -> test -> review -> package_project`. A step may merge stages when appropriate, but the manifest must still cover `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`. The planning stages must produce `PRODUCT_PLAN.md`, `OUTPUT_CONTRACT.md`, `TECHNICAL_PLAN.md`, and `BUILD_PLAN.md`; QA must produce `TEST_REPORT.md`; review must produce `DELIVERY_NOTES.md`; and `package_project` remains the only delivery exit. Specialist agents may build modules, and support agents may maintain `CFO_CONTEXT_DB.json` or `CFO_RISK_REGISTER.md`, but they do not own the formal route or final delivery readiness.

Build and QA steps are hard evidence boundaries inside `dynamic_pipeline_runner`. README-only/docs-only output cannot pass a worker build step. `TEST_REPORT.md` with `NO TEST EXECUTED`, `commands_run: none`, or missing real commands cannot pass a QA/test step. These failures must be recorded as `pipeline_step_result.status=rework_blocked`, not hidden as successful steps.

Before packaging, `dynamic_pipeline_runner` must audit quality evidence. Missing `TEST_REPORT.md` or `DELIVERY_NOTES.md` may be repaired once with an honest warning artifact, but packaging cannot hide the gap. `local_packager` records `quality_evidence` in `delivery_manifest.json`, and Telegram delivery replies must summarize whether test report, review notes, and preview evidence exist.

Telegram public delivery is stricter than packaging. Packaging may create an internal evidence bundle with warnings, but Telegram must not publicly deliver until `public_delivery_gate` says `delivery_allowed`. If the gate fails, including at `user_evidence_checkpoint`, the public reply must explain that backend generation did not pass and that internal reports will not be sent as the result; the run status must be `rework_blocked`, not `waiting_user_review`. Public attachments must use explicit artifact types such as project package, interface screenshot, generated background, generated sprite, or demo video.

When an agent reply is malformed or truncated, the runner may salvage fully closed actions and execute them, but it must keep the step in repair until strict JSON succeeds. This is parser resilience inside the current manifest step, not a separate generation path.

Local-model routing may reduce provider cost for low-risk tasks. Public reply tasks must not alter `whiteboard`, `pipeline_manifest`, generation actions, or delivery readiness. Generation-affecting local tasks must be opt-in and must stay inside the same `pipeline_manifest` and `dynamic_pipeline_runner` boundary. They must not bypass manifest validation, `local_agent_actions`, `local_packager`, or final delivery evidence.

Configured local models do not create a new formal generation path.

Critical setup questions, such as a missing model service, unavailable API credential, absent data source, storage choice, automation engine, runtime target, or security boundary, may be recorded in `critical_questions` and `open_questions`. They do not block the manifest/runner flow, but they must be reflected in acceptance criteria so fallback output is not misreported as satisfying the requested capability.

Telegram intake uses `should_auto_start_generation` before starting formal generation from a new project request, project update, or attachment. If `needs_direction_confirmation`, `soft_questions`, `critical_questions`, `missing_required_inputs`, a complex/high-uncertainty domain, or low confidence is present, intake records `generation_start_waiting` and waits. If the user explicitly says to start, unanswered questions and missing inputs are written into `generation_context_snapshot` as assumptions and warnings; outputs with missing real inputs must be partial/scaffold evidence, not full validation.

Capability strategy fields such as `capability_strategy` and `capability_research_targets` guide CFO planning and support agents for every project. They must describe underlying capabilities and advanced-method candidates, not project-type-specific branches. They do not authorize legacy pipelines, arbitrary execution, or bypassing manifest validation.

Public narration is allowed only at Telegram reply boundaries. It may redact internal terms and present progress through concrete actions and evidence, but the underlying Telegram default execution remains `api/provider project generation -> provider validation -> post_build_finalize -> local_packager -> public_delivery_gate -> delivery_manifest.json`.

Fallback to a single agent loop is allowed only when pipeline planning or runner execution fails, and it must record `pipeline_fallback`.

## Legacy Code Policy

Legacy provider pipeline code must not bypass post-build finalization, `local_packager`, or public delivery gate.

Legacy CLI may exist only under `legacy/` or as a thin wrapper.

Telegram formal generation may call the reviewed API/provider project generation implementation restored from the old provider chain, but it must not bypass post-build finalization, `local_packager`, or public delivery gate. `generate_project.py` and `simulator` remain disallowed as Telegram mainline.

Old `BLOCKED` and gate terminology must not be user-visible.

`backend_controls` are compatibility logs only, never execution queues.
