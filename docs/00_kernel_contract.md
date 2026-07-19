# CGKN Kernel Contract

This contract defines the stable kernel boundary for CovenantGraph Nexus Kernel. Future changes may add capabilities around the kernel, but they must not replace the generation mainline or bypass the safety and delivery boundaries described here.

## Kernel Responsibilities

CGKN Kernel is fixed responsible for:

1. Telegram entry for user project intake and generation confirmation.
2. `agent_session.jsonl` persistence for user messages, backend dialogue events, planner events, runner actions, and tool results.
3. `whiteboard` as the shared state surface for frontdesk, backend dialogue, planner agent, and generation agents.
4. `backend_dialogue_loop` as lightweight analysis and whiteboard update only; it is not a gate.
5. Running Telegram default project generation through API/provider project generation, provider output validation, post-build finalization, canonical evidence production, required user review, `local_packager`, public delivery gate, delivery receipt, active project binding, then canonical final verdict.
6. Keeping `pipeline_manifest`, `pipeline_planner_agent`, and `dynamic_pipeline_runner` as a support/experimental planning lane, not the Telegram default final project generator.
7. Using a CFO-controlled module plan inside `pipeline_manifest` when the support lane is explicitly used: the `cfo` role owns module planning, handoff order, acceptance interpretation, evidence review, and delivery readiness.
8. Allowing CFO support agents only inside the manifest as advisory context/risk maintainers, such as a context database and risk register. Support agents do not own Telegram default project generation, final route, implementation authority, or final delivery readiness.
9. Treating planning-only outputs such as `PRODUCT_PLAN.md`, `MODULE_PIPELINE.md`, `CFO_CONTEXT_DB.json`, `README.md`, or `TEST_REPORT.md` as planning/support artifacts unless provider project generation plus post-build finalization produces a runnable project surface and evidence.
10. Using `local_agent_actions` and `local_agent_skills` as the only tool execution boundary.
11. Using `local_packager.package_project` as the only formal delivery exit.
12. Treating the frozen, self-hashed canonical `delivery_manifest.json` as package evidence only after its inspector independently recomputes the current candidate/source hash, final ZIP hash, ZIP entry hash, evidence hashes, identity binding, and manifest/package delivery-directory binding. Canonical fields are reserved and cannot be replaced by extension metadata.
13. Allowing `dynamic_pipeline_runner` to recover complete actions from malformed or truncated agent JSON only inside the same manifest step, record the parse failure, and require a repair turn before that step can pass.
14. Allowing configured local models only as a model-source optimization. By default, local models may write public frontdesk/status replies only; generation-affecting local tasks such as backend dialogue, planner, CFO planning, context support, risk support, foundation, or QA must be explicitly enabled and must remain inside the same manifest/runner/evidence boundary. When a local-model task is enabled, the router may auto-start the configured Ollama runtime (`CGNK_AUTO_START_OLLAMA`, enabled by default) before calling the model; this is runtime readiness only, not a generation route.
15. Recording critical setup questions for any explicitly required external, local, hosted, data, model, automation, security, storage, or runtime capability. These questions are shared context and acceptance constraints, not a new gate or generation route.
16. Recording a project-level capability strategy for core capabilities, advanced-method candidates, obvious route differences, and acceptance limits. This is universal planning context for the same manifest/runner flow, not a project-type-specific generator.
17. Wrapping Telegram user-facing narration in an action-based public expression layer. Public replies may describe what will be built, why input is needed, how testing works, what evidence will be shown, and how the user can continue or revise; this does not create a new formal generation path.
17. Requiring every formal `pipeline_manifest` to cover Product Studio evidence stages: `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`.
18. Auditing quality evidence before `package_project`, including `TEST_REPORT.md` and `DELIVERY_NOTES.md`, and recording missing evidence as warnings instead of hiding it.
19. Waiting for explicit user start confirmation when backend dialogue finds soft questions, critical questions, missing required inputs, or complex/high-uncertainty domains. These questions are not hard gates once the user explicitly starts; they become assumptions and delivery warnings.
20. Running public delivery gate before any final public delivery. The gate verifies canonical artifact schemas, hashes, run id, candidate hash, commit SHA, package integrity, and required attachment evidence. Missing required tests, runtime, previews, local models, datasets, or receipts produce canonical `NEEDS_REWORK` or a specific `BLOCKED_*` status.
21. Treating only `local_packager` final package output as the final delivery zip. `delivery_fact_check` records `any_zip_found` separately from `final_package_exists`; samples, fixtures, uploads, test data, and arbitrary `.zip` files must not satisfy final package delivery.
22. Sending only user-facing media/package artifacts by default in Telegram public delivery: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.mp4`, `.webm`, and `.zip`. Internal `.md`, `.json`, `.txt`, `.log`, manifest, report, and ledger artifacts stay inside the evidence bundle unless explicitly requested. Placeholder, mock, or fallback media cannot satisfy requested screenshots, backgrounds, sprites, generated images, or demo evidence.
22. Auditing build completion before a build step can pass. A worker build step must not report `pipeline_step_result.status=ok` unless it produced a real runnable project surface, including `app.py` or `main.py`, dependency metadata such as `requirements.txt` or `pyproject.toml`, source files, tests, and required visual evidence.
23. Auditing QA completion before a QA/test step can pass. If `TEST_REPORT.md` contains `NO TEST EXECUTED` or does not list real test commands, the step must be `rework_blocked`, not `ok`.
24. Treating Telegram `generation-mode=simulator` as preflight-only. It must record a recoverable blocked result and must never produce a public PASS, package, or delivery manifest.
25. Rejecting provider output locally when it is empty, unsafe, generic/template metadata, placeholder implementation, or missing `README.md`, `TEST_PLAN.md`, and a runnable entrypoint.
26. Preserving validated provider component PASS checkpoints across retryable transport failures. Failed attempts use separate diagnostics, while semantic repair invalidates stale component checkpoints once before regeneration.
26. Recording a deterministic delivery inclusion manifest in `delivery_manifest.json`, including POSIX relative paths, byte sizes, content hashes, and the final zip path. Formal `visual_required`, `media_required`, and `user_review_required` values come from workflow requirements rather than artifact presence. `CGKNUserReviewRequest` binds `visual_required` explicitly in its self-hash; the request producer and inspector never infer it from screenshots, visual evidence files, presentation results, review files, or adaptive judgment. When true, the frozen request binds canonical test/runtime/visual evidence and a successfully sent, decoder-validated screenshot with the canonical screenshot hash; when false, visual evidence and screenshot roles cannot silently expand the review scope. Candidate-bound user review then requires Telegram update/message/date/from-user identity bound to the expected reviewer. The formal rule is that session booleans and text substrings are not review truth; neither are session request dictionaries or file presence. The review inspector independently checks request/ref hashes, visual scope, reviewer identity, timestamp order, evidence identity, presentation artifacts, and the durable replay ledger. Public-gate and send runtime state stays in session/truth-ledger records and must not mutate the frozen canonical manifest; the package path, ZIP hash, entries hash, and manifest artifact hash are rechecked immediately before the package document send.
   The formal Telegram evidence checkpoint sender re-inspects the frozen request and canonical visual evidence immediately before sending, permits only the canonical screenshot path/hash, treats only normalized successful Telegram returns as sent, and freezes optional Telegram message/chat metadata into the presented artifact. Exceptions, invalid returns, partial presentation, or pre-send changes produce `presentation_failed` before approval or packaging.
27. Never duplicating one sample image into screenshot, background, and sprite evidence, and never generating fallback media merely to satisfy a requested image capability.
28. Allowing only factual failures to force `BLOCKED`: missing project output, unsafe paths, missing claimed Telegram attachments, placeholder-only generation, or explicit provider failure. A final delivery without a packager zip cannot be `PASS`, but may remain available for user review. Telegram must not mark final delivery as delivered until the allowed public artifact set has actually been sent; final verdicts require the final package zip send to succeed.

`public_delivery_gate` remains a compatibility name for the wrapper that verifies canonical evidence, package integrity, and delivery receipts; it is not a second delivery route.

## Pipeline Module Mutation Contract

Replaceable support-lane modules may be changed only through reviewed repository changes that preserve their declared `contract()` boundary. This includes directly modifying, generating, or deleting bounded modules. truth modules—canonical evidence producers, inspectors, package and delivery gates—are not replaceable support modules and cannot be bypassed by a candidate bundle or module stub. A candidate bundle remains non-final until the canonical mainline independently validates and promotes it.

When the public delivery gate returns `rework_blocked`, Telegram session state must clear `generation.package_path`. A rejected or superseded package may remain on disk for diagnostics, but its path cannot remain advertised as a deliverable session artifact.

## Kernel Prohibitions

CGKN Kernel must not:

1. Reconnect the Telegram formal generation mainline to `generate_project.py`.
2. Reconnect the Telegram formal generation mainline to the raw `run_local_pipeline.py` CLI or any route that bypasses provider output validation, post-build finalization, `local_packager`, `delivery_fact_check`, or `agent_delivery_judgment`.
3. Restore `simulator` as the formal generation mainline.
4. Turn `backend_controls` back into an execution queue.
5. Treat `blocking_questions` or `soft_questions` as a hard gate for generation.
6. Allow `pipeline_manifest` to execute arbitrary Python.
7. Allow generation agents to modify CGKN kernel files.
8. Bypass `local_packager` or forge delivery completion.
9. Treat `agent_generated_pipeline` or CFO document outputs as Telegram default final project generation.
10. Count any fallback preview, placeholder, stub, procedural substitute, simulated result, or basic implementation as satisfying an explicitly requested core capability that requires a mature method, configured model, external API, local service, data source, automation engine, or runtime evidence.
11. Encode a project type, industry, object, or domain label as a special formal generation path. Domain labels may only help infer underlying capabilities; provider project generation remains universal.
12. Automatically start complex or under-specified project generation merely because soft questions are non-blocking. Non-blocking means the user may explicitly start with assumptions, not that the system starts by itself.
13. Treat internal reports, manifests, ledgers, or README-only folders as user-facing delivery results.

## Stable Flow

```text
Telegram
-> customer request
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> API/provider project generation
-> provider output validation
-> provider project files written
-> post_build_finalize
-> canonical test/runtime/visual evidence
-> user review when required
-> local_packager
-> public_delivery_gate
-> delivery_receipt
-> bind active project
-> final_verdict.json
```

The kernel is stable. The pipeline is agent-generated per project. The project itself is fully generated inside the bounded project directory. Skills are controlled capability modules. The whiteboard is the shared communication surface between intake, planning, generation, and delivery.

## Consolidated Kernel Rule

CGKN Telegram default generation uses API/provider project generation as the formal project-file generator. The provider route must write real project files, validate provider output, run post-build finalization, produce canonical test/runtime/visual evidence, record required user review, package through `local_packager`, pass public delivery gate, record delivery receipts, and write the canonical final verdict before claiming completion.

Before canonical test/runtime/visual evidence, the formal provider route must freeze one `CGKNProductionCandidateProvenance` from `scripts.telegram_live_bridge.start_generation_from_income -> run_provider_generation_job -> provider validation -> source-changing post-build`. It binds a unique run and candidate, the repository commit, the real customer candidate path, ordered self-hashed stage receipts, provider artifacts, and the independently reproducible candidate source manifest/hash. `scripts.production_candidate_provenance.inspect` must reread disk and recompute the manifest and candidate hash. Session/context booleans, `source_inspection="PASS"`, adaptive judgment, fixture output, acceptance output, and repository commit hashes cannot authorize this provenance. A provenance failure short-circuits canonical evidence inspection and adaptive delivery judgment.

API/provider detection remains required operational support. `CGKN_OPENAI_API_KEY` may be read from the environment, `gpt-4.1-mini` smoke tests may call `https://api.gptsapi.net/v1/chat/completions`, and retryable provider transport errors such as `SSLError`, `SSLV3_ALERT_BAD_RECORD_MAC`, timeouts, connection resets, 502, 503, 504, or empty responses must be retried before declaring NEEDS_REWORK. Provider support must not write API keys to logs or project files, and must not create fake delivery assets after retry exhaustion.

The `pipeline_manifest` is retained as an agent-generated support/experimental lane from `whiteboard` and `agent_session`. `dynamic_pipeline_runner` may interpret that manifest through `local_agent_actions` and `local_agent_skills`, but Telegram default generation must not treat CFO documents alone as final project generation.

Post-build finalization is part of the provider route. If `tests/` exists it must run `python -m pytest tests` and write `TEST_REPORT.md` with `commands_run`, `exit_code`, stdout summary, and stderr summary. If requested screenshots or generated images are missing, it may attempt to collect real evidence, but must not synthesize fallback media merely to satisfy delivery. Placeholder, blank, or pure-color images must not satisfy requested background or sprite evidence. Packaging normally creates `final_project_bundle.zip`, then runs factual checking and adaptive judgment.

Collected media must retain its actual evidence type. A screenshot or generic example image cannot be copied and relabeled as both a generated background and a generated sprite. If a requested local image model is unavailable, finalization records `missing_config`; canonical evidence decides whether the honest result needs `NEEDS_REWORK`, `NOT_EVALUATED`, `PASS_WITH_LIMITS`, or a specific `BLOCKED_*` status.

The default manifest shape is CFO-controlled and Product Studio disciplined: `product_plan -> technical_plan -> build -> test -> review -> package_project`. A step may merge stages when appropriate, but the manifest must still cover `product_plan`, `technical_plan`, `build`, `test`, `review`, and `package`. The planning stages must produce `PRODUCT_PLAN.md`, `OUTPUT_CONTRACT.md`, `TECHNICAL_PLAN.md`, and `BUILD_PLAN.md`; QA must produce `TEST_REPORT.md`; review must produce `DELIVERY_NOTES.md`; and `package_project` remains the only delivery exit. Specialist agents may build modules, and support agents may maintain `CFO_CONTEXT_DB.json` or `CFO_RISK_REGISTER.md`, but they do not own the formal route or final delivery readiness.

Build and QA steps are hard evidence boundaries inside `dynamic_pipeline_runner`. README-only/docs-only output cannot pass a worker build step. `TEST_REPORT.md` with `NO TEST EXECUTED`, `commands_run: none`, or missing real commands cannot pass a QA/test step. These failures must be recorded as `pipeline_step_result.status=rework_blocked`, not hidden as successful steps.

Before packaging, `dynamic_pipeline_runner` must audit quality evidence. Missing `TEST_REPORT.md` or `DELIVERY_NOTES.md` may be repaired once with an honest warning artifact, but packaging cannot hide the gap. `local_packager` records `quality_evidence` in `delivery_manifest.json`, and Telegram delivery replies must summarize whether test report, review notes, and preview evidence exist.

Telegram delivery uses public delivery gate followed by `CGKNDeliveryReceipt`. The gate outputs canonical status, missing evidence, verified hashes, and retryable failure details without making a separate final PASS decision. `PASS_WITH_LIMITS` must disclose its limitations and cannot satisfy public final delivery. `NOT_EVALUATED` is non-final. `BLOCKED` and the specific `BLOCKED_*` statuses cannot be overridden by the agent. Public attachments remain restricted to safe, existing media/package files listed by `can_send_artifacts`. Safe delivery roots include the project directory plus explicit packager/run delivery roots recorded in the manifest; absolute paths are resolved before boundary checks.

`scripts/canonical_delivery_receipt.py` is the sole producer and inspector for the authoritative project-root `delivery_receipt.json`. Telegram final delivery may enter `delivered` only after structured API receipts bind every formally required attachment to the expected chat and the on-disk receipt inspector returns `PASS`; sent lists, truth ledgers, booleans, and session flags are not substitutes.

`scripts/final_internal_acceptance.py` is a diagnostic fixture exerciser for its fixed Task Studio project, fixed Workers, replan, recovery, startup, runtime, and browser scenarios. It is not a production entry or a formal evidence producer, and its self-hashed outputs cannot authorize a formal Gate `PASS`. `scripts/formal_mainline_acceptance.py` is the read-only total-acceptance entry: it consumes existing production artifacts, binds the repository and customer candidate identities separately, invokes the registered inspector on disk, and emits `CGKNFormalGateStatus` without copying or relabeling source evidence. A missing production artifact or inspector remains `NOT_EVALUATED` or `NEEDS_REWORK`. `scripts/final_contract_unification_acceptance.py` is only a deprecated compatibility facade for this reader.

When an agent reply is malformed or truncated, the runner may salvage fully closed actions and execute them, but it must keep the step in repair until strict JSON succeeds. This is parser resilience inside the current manifest step, not a separate generation path.

Local-model routing may reduce provider cost for low-risk tasks. Public reply tasks must not alter `whiteboard`, `pipeline_manifest`, generation actions, or delivery readiness. Generation-affecting local tasks must be opt-in and must stay inside the same `pipeline_manifest` and `dynamic_pipeline_runner` boundary. They must not bypass manifest validation, `local_agent_actions`, `local_packager`, or final delivery evidence.

If an enabled local-model task uses Ollama, the router may find `ollama.exe`, run `ollama serve`, and wait for `OLLAMA_HOST` to respond before sending the request. `CGNK_OLLAMA_EXE` or `OLLAMA_EXE` may override the executable path, and `CGNK_AUTO_START_OLLAMA=0` disables this readiness helper. Auto-starting Ollama does not enable additional tasks by itself and does not change the Telegram default provider generation route.

Configured local models do not create a new formal generation path.

Critical setup questions, such as a missing model service, unavailable API credential, absent data source, storage choice, automation engine, runtime target, or security boundary, may be recorded in `critical_questions` and `open_questions`. They do not block the manifest/runner flow, but they must be reflected in acceptance criteria so fallback output is not misreported as satisfying the requested capability.

Telegram intake uses `should_auto_start_generation` before starting formal generation from a new project request, project update, or attachment. If `needs_direction_confirmation`, `soft_questions`, `critical_questions`, `missing_required_inputs`, a complex/high-uncertainty domain, or low confidence is present, intake records `generation_start_waiting` and waits. If the user explicitly says to start, unanswered questions and missing inputs are written into `generation_context_snapshot` as assumptions and warnings; outputs with missing real inputs must be partial/scaffold evidence, not full validation.

Capability strategy fields such as `capability_strategy` and `capability_research_targets` guide CFO planning and support agents for every project. They must describe underlying capabilities and advanced-method candidates, not project-type-specific branches. They do not authorize legacy pipelines, arbitrary execution, or bypassing manifest validation.

Public narration is allowed only at Telegram reply boundaries. It may redact internal terms and present progress through concrete actions and evidence, but the underlying Telegram default execution remains `api/provider project generation -> provider validation -> post_build_finalize -> canonical evidence -> required user review -> local_packager -> public_delivery_gate -> delivery_receipt -> bind active project -> final_verdict.json`.

Fallback to a single agent loop is allowed only when pipeline planning or runner execution fails, and it must record `pipeline_fallback`.

## Legacy Code Policy

Legacy provider pipeline code must not bypass post-build finalization, `local_packager`, or public delivery gate.

Legacy CLI may exist only under `legacy/` or as a thin wrapper.

Telegram formal generation may call the reviewed API/provider project generation implementation restored from the old provider chain, but it must not bypass post-build finalization, `local_packager`, or public delivery gate. `generate_project.py` and `simulator` remain disallowed as Telegram mainline.

## Local Project Team Layer

CGKN may maintain local conversation, active project, managed project, and revision-history state through `local_conversation_manager`, `local_repo_manager`, `main_agent_manager`, and `project_revision_lane`. These modules are coordination and history layers only. They do not create a second formal generation path.

Project revisions must preserve the previous active project until the new revision passes the reviewed provider route, post-build finalization, `local_packager`, factual checking, final adaptive judgment, and `delivery_manifest.json`. `NOT_EVALUATED` does not promote a revision to `current`; only a final allowed verdict may promote it. A failed revision records failure state and never replaces the current revision.

Model defaults must be selected through `model_policy` for provider generation and connectivity checks so different entrypoints do not silently test or run different default models.

Old `BLOCKED` and gate terminology must not be user-visible.

`backend_controls` are compatibility logs only, never execution queues.
