# CGNK Kernel Contract

This contract defines the stable kernel boundary for CovenantGraph Nexus Kernel. Future changes may add capabilities around the kernel, but they must not replace the generation mainline or bypass the safety and delivery boundaries described here.

## Kernel Responsibilities

CGNK Kernel is fixed responsible for:

1. Preserving Requirement Decision First: CGNK's first responsibility is to help the customer determine the right requirement before code generation is treated as success.
2. Telegram entry for user project intake and generation confirmation.
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
14. Allowing configured local models only as a model-source optimization. By default, local models may write public frontdesk/status replies only; generation-affecting local tasks such as backend dialogue, planner, CFO planning, context support, risk support, foundation, or QA must be explicitly enabled and must remain inside the same manifest/runner/evidence boundary. When a local-model task is enabled, the router may auto-start the configured Ollama runtime (`CGNK_AUTO_START_OLLAMA`, enabled by default) before calling the model; this is runtime readiness only, not a generation route.
15. Recording critical setup questions for any explicitly required external, local, hosted, data, model, automation, security, storage, or runtime capability. These questions are shared context and acceptance constraints, not a new gate or generation route.
16. Recording a project-level capability strategy for core capabilities, advanced-method candidates, obvious route differences, and acceptance limits. This is universal planning context for the same manifest/runner flow, not a project-type-specific generator.
17. Wrapping Telegram and Local Studio user-facing narration in an action-based public expression layer. `scripts/frontdesk_team_lead_agent.py` is the Team Lead Chat Agent expression boundary: it receives the latest user message, conversation summary, whiteboard, active run, generation status, delivery evidence, known limits, and customer policy, then emits natural Chinese plus `reply_intent`, `visible_status`, and `next_user_options`. It may rewrite wording and record correction intent, but it does not start generation, package delivery, or create a new formal generation path.
17. Requiring every formal `pipeline_manifest` to cover Product Studio evidence stages: `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`.
18. Auditing quality evidence before `package_project`, including `TEST_REPORT.md` and `DELIVERY_NOTES.md`, and recording missing evidence as warnings instead of hiding it.
19. Waiting for explicit user start confirmation when backend dialogue finds soft questions, critical questions, missing required inputs, or complex/high-uncertainty domains. These questions are not hard gates once the user explicitly starts; they become assumptions and delivery warnings.
20. Running a Telegram public delivery gate before any intermediate or final public delivery. README-only/docs-only output, missing runnable entrypoints, missing real test commands, `NO TEST EXECUTED`, or missing requested screenshots/images/videos must force rework instead of public delivery. Final delivery also requires `final_project_bundle.zip`; a candidate marker or `candidate_diagnostic_bundle.zip` must force rework and cannot be treated as the final package.
21. Sending only user-facing media/package artifacts by default in Telegram public delivery: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.mp4`, `.webm`, and `.zip`. Internal `.md`, `.json`, `.txt`, `.log`, manifest, report, and ledger artifacts stay inside the evidence bundle unless explicitly requested.
22. Auditing build completion before a build step can pass. A worker build step must not report `pipeline_step_result.status=ok` unless it produced a real runnable project surface, including `app.py` or `main.py`, dependency metadata such as `requirements.txt` or `pyproject.toml`, source files, tests, and required visual evidence.
23. Auditing QA completion before a QA/test step can pass. If `TEST_REPORT.md` contains `NO TEST EXECUTED` or does not list real test commands, the step must be `rework_blocked`, not `ok`.
24. Keeping Commercial Hardening Lane as an assessment and reporting lane only. `scripts/run_commercial_readiness.py`, provider resilience, sandbox security, product acceptance, customer status rendering, and Telegram delivery split helpers may classify release readiness, but they do not create a second formal generation or delivery route.
25. Running Discovery & Selection Lane before complex project provider generation. This lane writes `run_dir/discovery/discovery_brief.md`, `candidate_directions.json`, `candidate_scorecard.json`, `selected_project_direction.json`, `rejected_options.md`, and `complexity_project_contract.json`, then passes the selected direction and contract into the existing provider route. It is an upstream selection and contract-freezing lane, not a project generator or delivery route.
26. Treating clear requirement definition, scope, priorities, constraints, acceptance criteria, rejected options, and next steps as valuable intermediate outcomes when final code delivery is not complete yet.
27. Keeping the Agent Director Loop as the agent-led coordination surface: it observes run state, selects tools from `agent_tool_registry`, validates evidence gates, executes the selected tool, and writes `artifacts/agent_decision_ledger.jsonl`. It does not replace the reviewed Telegram provider route, `local_packager`, or the public delivery gate.
28. Treating `scripts/acceptance_verifier.py` as the only canonical `final_verdict.json` writer. Runners, benchmarks, trace builders, Dynamic Tree support lanes, and QA evidence collectors may produce run facts or claims, but their claimed PASS cannot override required upstream gates.

## Kernel Prohibitions

CGNK Kernel must not:

1. Treat program generation as the first objective when the customer requirement is still unclear.
2. Reconnect the Telegram formal generation mainline to `generate_project.py`.
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
14. Treat generated code, a runnable demo, or a packaged bundle as success when it does not align with a clear customer requirement, frozen scope, and acceptance criteria.
15. Treat Commercial Hardening reports as delivery artifacts or as proof that a candidate passed final delivery. Commercial readiness can recommend release labels, but final public delivery still requires the reviewed provider route, `local_packager`, `delivery_manifest.json`, and public final gate.
16. Treat `run_formal_live_delivery_closure.py`, `final_promotion.py`, `run_commercial_readiness.py`, or `formal_delivery_evidence.py` as the only controller for every project. These scripts are callable tools or evidence gates under the Agent Director Loop; they must not turn CGKN back into a fixed pipeline where the agent only fills stage text.

## Stable Flow

```text
Telegram
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> Requirement Decision First: clarify customer goal, compare directions, freeze scope and acceptance criteria
-> Discovery & Selection Lane for complex project direction and `complexity_project_contract.json`
-> API/provider project generation
-> provider output validation
-> provider project files written
-> post_build_finalize
-> tests, image/screenshot evidence, runtime artifacts
-> local_packager
-> delivery_manifest.json
```

The kernel is stable. The pipeline is agent-generated per project. The project itself is fully generated inside the bounded project directory. Skills are controlled capability modules. The whiteboard is the shared communication surface between intake, planning, generation, and delivery.

The core operating question is: did CGNK help the customer determine the right requirement? If the answer is no, generated code is not a real success. If code is incomplete but the system has honestly clarified goals, candidate directions, selected scope, priorities, constraints, acceptance standards, rejected options, and next steps, that can be a valid intermediate outcome.

## Pipeline Module Mutation Contract

CGNK pipeline changes must be made by directly modifying, generating, or deleting bounded modules. This is a bottom-level implementation rule, not a style preference. Agents must not hide behavior in ad hoc compatibility branches, generated-project hand edits, or final artifact overrides.

The local pipeline is contract-driven and module-replaceable at the capability layer:

- `pipeline_contracts.py` defines the shared result shape and module replacement rules.
- `provider_generation.py`, `post_build_repair.py`, `visual_evidence.py`, and `candidate_review_delivery.py` are replaceable capability modules when their contracts remain satisfied.
- `candidate_materializer.py`, `candidate_sanitizer.py`, and `post_build_finalize.py` are bounded execution modules that may be changed only within their stated responsibility.
- `final_promotion.py`, `final_delivery_truth.py`, `artifact_integrity.py`, path safety, fake artifact scanning, `local_packager`, and the public final delivery gate are truth modules. They are not replaceable by generation agents and cannot be bypassed by candidate artifacts.

Module replacement must preserve candidate-first behavior, deterministic sanitizer behavior, post-build repair limits, real visual evidence checks, candidate review delivery separation, formal final promotion through `local_packager`, and strict final delivery truth. A candidate bundle, blocked screenshot/video record, generated manifest claim, or provider-created zip must never become final delivery evidence.

## Consolidated Kernel Rule

CGNK Telegram default generation uses API/provider project generation as the formal project-file generator. The provider route must write real project files, validate provider output, run post-build finalization, package through `local_packager`, and pass Telegram public delivery gate before sending anything public.

API/provider detection remains required operational support. `CGKN_OPENAI_API_KEY` may be read from the environment, `gpt-4.1-mini` smoke tests may call `https://api.gptsapi.net/v1/chat/completions`, and retryable provider transport errors such as `SSLError`, `SSLV3_ALERT_BAD_RECORD_MAC`, timeouts, connection resets, 502, 503, 504, or empty responses must be retried before declaring REWORK. Provider quota failures such as HTTP 403 `Key usage limit exceeded` must be classified as `PROVIDER_QUOTA_EXCEEDED`, treated as non-retryable for immediate repeated live generation, and reported as `provider_quota_blocked` rather than as a semantic/project failure. Provider support must not write API keys to logs or project files, and must not create fake delivery assets after retry exhaustion.

The `pipeline_manifest` is retained as an agent-generated support/experimental lane from `whiteboard` and `agent_session`. `dynamic_pipeline_runner` may interpret that manifest through `local_agent_actions` and `local_agent_skills`, but Telegram default generation must not treat CFO documents alone as final project generation.

Post-build finalization is part of the provider route. If `tests/` exists it must run `python -m pytest tests` and write `TEST_REPORT.md` with `commands_run`, `exit_code`, stdout summary, and stderr summary. If requested screenshots or generated images are missing, it must attempt to collect or generate `screenshots/app_home.png`, `assets/generated/background_*.png`, `assets/generated/sprite_*.png`, and `generated_image_manifest.json`. Placeholder, blank, or pure-color images must not satisfy requested background or sprite evidence. Packaging must create `final_project_bundle.zip`, then rerun public delivery gate.

The default manifest shape is CFO-controlled and Product Studio disciplined: `product_plan -> technical_plan -> build -> test -> review -> package_project`. A step may merge stages when appropriate, but the manifest must still cover `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`. The planning stages must produce `PRODUCT_PLAN.md`, `OUTPUT_CONTRACT.md`, `TECHNICAL_PLAN.md`, and `BUILD_PLAN.md`; QA must produce `TEST_REPORT.md`; review must produce `DELIVERY_NOTES.md`; and `package_project` remains the only delivery exit. Specialist agents may build modules, and support agents may maintain `CFO_CONTEXT_DB.json` or `CFO_RISK_REGISTER.md`, but they do not own the formal route or final delivery readiness.

Build and QA steps are hard evidence boundaries inside `dynamic_pipeline_runner`. README-only/docs-only output cannot pass a worker build step. `TEST_REPORT.md` with `NO TEST EXECUTED`, `commands_run: none`, or missing real commands cannot pass a QA/test step. These failures must be recorded as `pipeline_step_result.status=rework_blocked`, not hidden as successful steps.

Before packaging, `dynamic_pipeline_runner` must audit quality evidence. Missing `TEST_REPORT.md` or `DELIVERY_NOTES.md` may be repaired once with an honest warning artifact, but packaging cannot hide the gap. `local_packager` records `quality_evidence` in `delivery_manifest.json`, and Telegram delivery replies must summarize whether test report, review notes, and preview evidence exist.

Provider semantic review failures may write debug-only rejected previews under runtime artifacts, but those previews are not `project_dir`, must not be packaged by `local_packager`, must not create `delivery_manifest.json`, and must not be counted as public delivery artifacts.

Historical CGNK packaging allowed warning-based bundles: missing README could be filled by `local_packager`, missing screenshots were recorded as warnings, and the manifest could be `ready_with_warnings`. That leniency is still valid only for internal packaging evidence and candidate review. It must not be interpreted as public delivery success until post-build finalization, `local_packager`, and the public delivery gate all agree on real artifacts.

Provider candidates should be materialized when minimal fact checks pass. Semantic quality blockers, runtime blockers, missing screenshots, missing videos, incomplete README content, weak tests, or frontend/backend mismatches should flow into candidate post-build finalization, `known_limits.json`, `repair_plan.json`, `TEST_REPORT.md`, `DELIVERY_NOTES.md`, and `video_blocked.json` when needed. Only fatal facts such as unsafe paths, path traversal, provider returning no files, malformed file objects, corrupt or binary text output, or unresolved duplicate ownership may block candidate materialization. Repairable fact issues such as fake final zip scripts, fake delivery manifest claims, fake screenshot/video claims, inaccurate TEST_REPORT claims before tests run, or documentation claiming final delivery before packager must be deterministically sanitized before candidate materialization; sanitized candidates remain `candidate_only` and cannot pass final delivery.

Provider semantic repair resume is part of the same provider validation route, not a second delivery path. Each provider run must persist `artifacts/run_context.json` with the raw user goal, model, base URL, generation mode, and requested project directory before provider repair can be resumed. Before any semantic repair provider request, the route must write a non-empty `pending_repair_plan.json` containing the failed component, affected files, repair prompt path, checkpoint summary path, attempt counters, and the current repair plan; if that context cannot be built, it must write `pending_repair_plan_unavailable` diagnostics instead of `{}`. Retryable provider transport errors such as 503, 504, 522, and timeouts do not consume semantic repair attempts, must preserve the pending repair plan, and should record safe provider response headers such as `cf-ray`, `x-trace-id`, `x-request-id`, `request-id`, `date`, and `server` when available. Repair prompts should prefer file-level or patch-level regeneration with explicit context budgets before falling back to whole-component regeneration.

Telegram public delivery is stricter than packaging. Packaging may create an internal evidence bundle with warnings, but Telegram must not publicly deliver until `public_delivery_gate` says `delivery_allowed`. If the gate fails, including at `user_evidence_checkpoint`, the public reply must explain that backend generation did not pass and that internal reports will not be sent as the result; the run status must be `rework_blocked`, not `waiting_user_review`. Public attachments must use explicit artifact types such as project package, interface screenshot, generated background, generated sprite, or demo video.

When an agent reply is malformed or truncated, the runner may salvage fully closed actions and execute them, but it must keep the step in repair until strict JSON succeeds. This is parser resilience inside the current manifest step, not a separate generation path.

Local-model routing may reduce provider cost for low-risk tasks. Public reply tasks must not alter `whiteboard`, `pipeline_manifest`, generation actions, or delivery readiness. Generation-affecting local tasks must be opt-in and must stay inside the same `pipeline_manifest` and `dynamic_pipeline_runner` boundary. They must not bypass manifest validation, `local_agent_actions`, `local_packager`, or final delivery evidence.

If an enabled local-model task uses Ollama, the router may find `ollama.exe`, run `ollama serve`, and wait for `OLLAMA_HOST` to respond before sending the request. `CGNK_OLLAMA_EXE` or `OLLAMA_EXE` may override the executable path, and `CGNK_AUTO_START_OLLAMA=0` disables this readiness helper. Auto-starting Ollama does not enable additional tasks by itself and does not change the Telegram default provider generation route.

Configured local models do not create a new formal generation path.

Critical setup questions, such as a missing model service, unavailable API credential, absent data source, storage choice, automation engine, runtime target, or security boundary, may be recorded in `critical_questions` and `open_questions`. They do not block the manifest/runner flow, but they must be reflected in acceptance criteria so fallback output is not misreported as satisfying the requested capability.

Telegram intake uses `should_auto_start_generation` before starting formal generation from a new project request, project update, or attachment. If `needs_direction_confirmation`, `soft_questions`, `critical_questions`, `missing_required_inputs`, a complex/high-uncertainty domain, or low confidence is present, intake records `generation_start_waiting` and waits. If the user explicitly says to start, unanswered questions and missing inputs are written into `generation_context_snapshot` as assumptions and warnings; outputs with missing real inputs must be partial/scaffold evidence, not full validation.

Capability strategy fields such as `capability_strategy` and `capability_research_targets` guide CFO planning and support agents for every project. They must describe underlying capabilities and advanced-method candidates, not project-type-specific branches. They do not authorize legacy pipelines, arbitrary execution, or bypassing manifest validation.

Discovery & Selection Lane may explore and score multiple candidate project directions for a rough complex goal, but it must not generate target project code, must not select low-complexity demos or high-dependency untestable directions, and must return NEEDS_REWORK when no candidate satisfies the complexity, local-first, delivery, testability, GUI/CLI, artifact, and risk thresholds. Its `complexity_project_contract.json` is downstream input for provider generation and product acceptance; it does not weaken `post_build_finalize`, `local_packager`, final delivery truth, or the public delivery gate.

Public narration is allowed only at Telegram and Local Studio reply boundaries. It may redact internal terms and present progress through concrete actions and evidence, but the underlying Telegram default execution remains `api/provider project generation -> provider validation -> post_build_finalize -> local_packager -> public_delivery_gate -> delivery_manifest.json`.

Team Lead Chat Agent v1 is part of that public narration layer for Telegram and Local Studio and does not create a new formal generation path. It must not expose provider, pipeline, manifest, runner, JSONL, or BLOCKED in user-visible text; must not pretend human staff are manually developing the project; status questions must answer only current state and missing evidence; and user corrections must first be acknowledged, then written to whiteboard/change requests.

Fallback to a single agent loop is allowed only when pipeline planning or runner execution fails, and it must record `pipeline_fallback`.

Commercial Hardening Lane is not a generation path. `provider_resilience.py` can block live generation when quota is exhausted or select an enabled backup provider. `sandbox_security.py` can block final promotion on unsafe generated-project commands. `commercial_warning_policy.py` can downgrade PASS_FINAL to warning delivery or rejection based on classified warnings. `product_acceptance.py` can mark a project unsuitable for commercial release. `customer_status.py` and `scripts/telegram_delivery/` translate state for users and split candidate review from final delivery. None of these modules may mint `final_project_bundle.zip`, `delivery_manifest.json`, `PASS_FINAL`, or `final_delivered` outside the existing `local_packager` and final public delivery gate.

## Agent Director Tooling Layer

The Agent Director Loop keeps CGKN agent-led:

```text
observe run state
-> choose a registered tool
-> validate evidence gates
-> execute the selected tool
-> write agent_decision_ledger.jsonl
-> observe again
```

`agent_state_observer.py` reports facts only. It must not choose the next step. `agent_tool_registry.py` declares callable tools and their allowed conditions. `agent_director_loop.py` validates choices before execution. `agent_decision_ledger.py` records the selected tool, rejected tools, observed state hash, reason, expected outputs, status, and result references.

The formal live delivery closure remains available as a high-risk tool for final closure work. It is not the only controller that may call public delivery tools, and it does not weaken the rule that final public delivery requires `local_packager`, `delivery_manifest.json`, `final_project_bundle.zip`, evidence integrity, and the public delivery gate.

## Dynamic Tree Project Management and Provider Governance

The Dynamic Agent Tree support lane may maintain project-management artifacts for its own controlled runs: `project_plan.json`, append-only `task_ledger.jsonl`, `agent_performance_ledger.jsonl`, `project_manager_decisions.jsonl`, `agent_performance_snapshot.json`, `project_health.json`, and `project_health_history.jsonl`. These artifacts may influence Dynamic Tree assignment, scope, budget, reviewer, replacement, split, replan, and pruning decisions inside the support lane, but they do not connect Dynamic Tree to Telegram default generation and do not create a second public delivery route.

Dynamic Tree WBS generation must be project-specific. The support lane may infer coarse domains such as knowledge studio, studio operations, media analysis, or generic product to derive different task ledgers, critical paths, child agents, and scope contracts. If dynamic WBS generation falls back to a static template, it must write an explicit `dynamic_planner_fallback.json` reason.

Cross-run agent reputation may be stored only in private support-lane state such as `.agent_private/agent_reputation.json` or an explicit configured path. Reputation must be domain and task-type scoped, migrated by version, decayed when used for selection, and must not penalize agents for external provider quota, provider outage, network, or user requirement changes.

Provider request governance remains part of the single `provider_transport.py` truth source. Planner, conversation, leaf generation, repair, review, evidence summary, and connectivity calls must use model choices from `model_policy`, request-type output limits, API budget profiles, redacted append-only usage ledgers, request fingerprints, per-run readiness cache, request cache where safe, cache schema/TTL validation, circuit breaker state including half-open probe control, budget reservations, bounded retries, and pre-call `BLOCKED_API_BUDGET` decisions. Provider quota, provider unavailable, unsupported method/model, network, and other external blockers must not be counted as Agent performance failures.

Dynamic Tree repair should prefer incremental missing-file, test-failure, scope-violation, or malformed-response repair prompts before whole replacement. Repair evidence must record original and repair prompt sizes. No Provider governance ledger may store API keys, Authorization headers, or unreduced secrets.

Dynamic Tree support lanes must not write independent final PASS verdicts. If they emit `final_verdict.json`, it must be produced through the canonical acceptance verifier and include runner-claimed verdicts only as conflict-checkable inputs.

## Legacy Code Policy

Legacy provider pipeline code must not bypass post-build finalization, `local_packager`, or public delivery gate.

Legacy CLI may exist only under `legacy/` or as a thin wrapper.

Telegram formal generation may call the reviewed API/provider project generation implementation restored from the old provider chain, but it must not bypass post-build finalization, `local_packager`, or public delivery gate. `generate_project.py` and `simulator` remain disallowed as Telegram mainline.

## Local Project Team Layer

CGNK may maintain local conversation, active project, managed project, and revision-history state through `local_conversation_manager`, `local_repo_manager`, `main_agent_manager`, and `project_revision_lane`. These modules are coordination and history layers only. They do not create a second formal generation path.

Project revisions must preserve the previous active project until the new revision passes the reviewed provider route, post-build finalization, `local_packager`, `public_delivery_gate`, and `delivery_manifest.json`. A failed revision must record failure state and must not promote its workspace to `current`.

Model defaults must be selected through `model_policy` for provider generation and connectivity checks so different entrypoints do not silently test or run different default models.

Old `BLOCKED` and gate terminology must not be user-visible.

`backend_controls` are compatibility logs only, never execution queues.
