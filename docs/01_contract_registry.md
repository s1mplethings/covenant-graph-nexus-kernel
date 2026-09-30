# CGKN Contract Registry

## Canonical version governance

| Artifact / check | Producer | Consumer | Authority boundary |
| --- | --- | --- | --- |
| `CGKNCurrentArchitecture` / `governance/current_architecture.json` | reviewed repository change | `scripts/canonical_version_gate.py`, maintainers, Agents | current-truth registry only; names existing authorities and routes but grants none |
| `CGKNDeprecationRegistry` / `governance/deprecation_registry.json` | reviewed migration retaining real compatibility | `scripts/canonical_version_gate.py` | COMPAT_ONLY inventory only; cannot produce current artifacts or retain removed items |
| canonical version gate result | `scripts/canonical_version_gate.py` | repository quality control and review | deterministic veto-only result; cannot authorize evidence, acceptance, packaging, delivery, or public PASS |
| generated-project version policy | `scripts/project_version_policy.py` through the existing ProviderJob route | generated and maintained projects | adds the universal VERSION truth and validates upgrade shape; Provider remains project author and existing gates remain authoritative |

## Artifact-driven pipeline kernel v0.3

| Contract / artifact | Authoritative schema or implementation | Consumer | Authority boundary |
| --- | --- | --- | --- |
| `ArtifactRef` | `schemas/artifact_ref.v1.schema.json`; `cgkn/artifacts/models.py` | ArtifactStore, checkpoints, manifests, context packs | portable identity only; no evidence authority |
| `ArtifactInstance` | `schemas/artifact_instance.v1.schema.json`; `cgkn/artifacts/models.py` | `cgkn/artifacts/store.py` and typed modules | immutable structured knowledge; lifecycle status is not EvidenceStatus |
| standard v0.3 artifact contents | `schemas/artifact_content_types.v1.schema.json`; `specs/artifacts/*` with `metadata.v0_3=true` | artifact-driven compiler and runtime | content validation only |
| `ArtifactIndex` | `cgkn/artifacts/store.py`; `artifact_index.json` | lineage, cache, invalidation CLIs | mutable local lookup/status projection over immutable history |
| `ArtifactFlowRunManifest` | `schemas/artifact_run_manifest.v1.schema.json`; `cgkn/runtime/runner.py` | local resume and inspection | workflow support only |
| v0.3 `GenerationCheckpoint` | `schemas/generation_checkpoint.v2.schema.json`; `cgkn/runtime/checkpoint.py` | run manifest and diagnostics | execution side channel; refs only, no business payload or delivery authority |
| `FeedForwardReport` | `cgkn/runtime/runner.py`; `feed_forward_report.json` | token/cache/debug review | support metrics only |
| `EffectConstraint` | `schemas/policy_spec.schema.json`; `cgkn/runtime/effects.py` | compiler and ArtifactModuleRunner | limits declared effect counts; does not grant an effect denied elsewhere |
| `flow.artifact_driven_project_refactor@1` | `specs/flows/artifact_driven_project_refactor.flow.json` | `scripts/run_artifact_flow.py` | additive reference flow; not a second Codex conversation public-delivery route |

The registered content types are RawRequirement, ProjectSource (reference-flow
input), RequirementInterpretation, ProjectSnapshot, ProblemAnalysis,
ArchitectureDecision, RefactorPlan, ImplementationPatch, TestEvidence,
BoundaryReport, and DeliveryJudgment. Formal evidence values inside evidence
artifacts use only the canonical status registry. Artifact lifecycle values
remain separate.

This registry is the authoritative list of formal CGKN evidence and delivery contracts. Every formal artifact uses the canonical envelope:

```json
{
  "kind": "CGKNTestExecutionEvidence",
  "schema_version": "1.0",
  "run_id": "run-001",
  "candidate_id": "candidate-001",
  "candidate_hash": "sha256:...",
  "commit_sha": "abc123",
  "production_provenance_ref": "/production/run-001/production_candidate_provenance.json",
  "production_provenance_hash": "sha256:...",
  "producer": "scripts/real_test_execution.py",
  "created_at": "2026-07-13T00:00:00Z",
  "status": "PASS",
  "artifact_hash": "sha256:...",
  "argv": ["python", "-m", "pytest", "tests"],
  "cwd": "/workspace/project",
  "environment": "clean_temp_env",
  "started_at": "2026-07-13T00:00:00Z",
  "finished_at": "2026-07-13T00:00:05Z",
  "exit_code": 0,
  "timeout": false,
  "collected": 1,
  "passed": 1,
  "failed": 0,
  "skipped": 0,
  "skip_reasons": {},
  "stdout_artifact": "stdout.txt",
  "stdout_hash": "sha256:...",
  "stderr_artifact": "stderr.txt",
  "stderr_hash": "sha256:...",
  "result_artifact_hash": "sha256:...",
  "test_profile": "repo_default"
}
```

Canonical EvidenceStatus values:

```text
PASS
PASS_WITH_LIMITS
NOT_EVALUATED
BLOCKED
BLOCKED_PROVIDER
BLOCKED_LOCAL_MODEL
BLOCKED_ENVIRONMENT
NEEDS_REWORK
FAIL
```

WorkflowState values are separate and must not be consumed as EvidenceStatus:

```text
queued
running
validating
waiting_user_review
packaging
delivery_sending
delivery_send_failed
rework_blocked
final_delivered
```

## Formal Artifacts

| Artifact kind | Schema | Producer | Formal consumers | Mainline | Status enum | Required fields | Legacy replacement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CGKNProductionCandidateProvenance` | `schemas/production_candidate_provenance_v1.schema.json` | `scripts/codex_conversation.py` | canonical test/runtime/visual producers, public delivery gate, formal mainline acceptance | yes, frozen after provider validation and source-changing post-build work | canonical EvidenceStatus | envelope, production entrypoint and generation function, run/candidate/commit identity, canonical candidate path, independently reproducible source manifest/hash, ordered self-hashed production stage receipts, provider result ref/hash | replaces session booleans, wrapper declarations, provider diagnostics, repository commit hashes, and acceptance-created provenance claims |
| `CGKNProvisionalCandidate` / `CGKNCandidateStoreIndex` | deterministic immutable candidate record and index under `artifacts/candidate_store/` | `scripts/candidate_materializer.py` | existing post-build evaluator and affected-only repair loop | immutable per version; index is append-only support state; a source hash equal to its parent records `NO_TREE_DELTA` and creates no version | `workflow_state=BUILD_COMPLETE`, `evidence_status=NOT_EVALUATED`; never PASS authority | candidate id/version/hash/path, parent id, repair issue ids, commit SHA, ProjectSpec hash, known issues, Provider provenance | cannot replace canonical provenance, runtime, hidden acceptance, packaging, delivery, or final verdict |
| `CGKNPostBuildIssueLedger` / repair bundle | deterministic support JSON under the production run artifacts | `scripts/post_build_repair.py` after a complete post-build evaluation | existing ProviderJob-scoped split-file repair executor and diagnostic reporting | regenerated after each repair round; evaluator evidence outranks internal validators | `PASS` or `NEEDS_REWORK` as ledger status only; `release_authority=false` | issue id, failed requirement, user action, expected/observed behavior, evaluator evidence, severity, affected path and ProviderJob, root-cause key, route; bundle id, issue ids, owned targets, acceptance conditions, two-call maximum | cannot authorize formal evidence, packaging, delivery, or PASS; cannot create a scheduler or cause evidence-only issues to call Provider |
| `CGKNProviderCausalTrace` | `schemas/provider_causal_trace_v1.schema.json` | `scripts/codex_conversation.py` | canonical test/runtime/visual gate ordering, public delivery gate, formal mainline acceptance | yes, provider response staging through final production candidate | canonical EvidenceStatus | request and response content identity/hash, deterministic decisions and decision hash, per-file patch hunks and hashes, byte-exact application receipt, before/patch-after/final source hashes, post-build delta, run/candidate/commit/root identity, production provenance | replaces request/response IDs, provider-consumed booleans, direct final-candidate provider writes, wrapper PASS, and post-hoc patch claims |
| `CGKNTestExecutionEvidence` | `schemas/test_execution_v1.schema.json` | `scripts/real_test_execution.py` | post-build finalization, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, argv, cwd, environment, run/candidate/commit IDs, timing, exit code, counts, categorized skips, stdout/stderr refs and hashes, result hash, profile | replaces ad hoc `ok`, `commands_run`, `exit_code`, and handwritten `TEST_REPORT.md` truth |
| `CGKNCustomerRuntimeEvidence` | `schemas/customer_runtime_v1.schema.json` | `scripts/customer_runtime_runner.py` | runnable project contract, visual evidence, public delivery gate, final verdict | yes | canonical EvidenceStatus | envelope, startup argv, cwd, clean environment root, dependency setup, PID, URL, health probe, customer action, expected/observed result, observed hash, shutdown result | replaces hand-written `customer_runtime.json` PASS fixtures |
| `CGKNVisualEvidence` | `schemas/visual_evidence_v1.schema.json` | `scripts/browser_visual_evidence.py` | runtime visual evidence collector, public delivery gate, final verdict | yes when GUI/visual output is required | canonical EvidenceStatus | envelope, customer runtime ref/hash, browser engine/version, URL, actions, DOM assertions, network observations, screenshot path/hash, viewport, `formal_evidence=true` | replaces static preview PNG/SVG and placeholder screenshot sidecars |
| `CGKNCanonicalMediaValidationResult` | inline canonical result | `scripts/canonical_media_validation.py` | provider post-build media collector, public delivery gate | yes for generated image/background/sprite/video delivery assets | `PASS`, `FAIL`, `BLOCKED_ENVIRONMENT`, `NOT_EVALUATED` | kind, schema version, media type, requested role, path/relative path, suffix, detected format, sha256, size, decoder/version, dimensions, duration/codec/stream data, decoded frame count, blank/placeholder flags, validated_at | replaces extension/name/file-exists media acceptance |
| `CGKNUserReviewRequest` | `schemas/user_review_request_v1.schema.json` | `scripts/canonical_user_review.py` | user review writer and inspector, local packager, public delivery gate | yes before a required review | canonical EvidenceStatus | frozen candidate/evidence identity, explicit workflow-derived `visual_required`, expected Codex conversation reviewer, required presentation roles, actual sent artifact refs/hashes, requested/presented timestamps and self-hash | session request dictionaries and artifact presence cannot replace or promote this requirement |
| `CGKNUserReviewEvidence` | `schemas/user_review_v1.schema.json` | `scripts/canonical_user_review.py` | local packager, public delivery gate, final verdict | yes when review is required | canonical EvidenceStatus | envelope, request ref/hash, explicit `visual_required`, event id, Codex conversation update/message/date/reviewer identity, reviewed candidate, structured evidence refs/hashes, approval text hash, decision, reviewed_at | replaces session approval booleans and substring-based approval; inspector independently checks request, visual scope, time order and durable replay binding |
| `CGKNCanonicalVerificationReport` | inline v1 contract | `scripts/canonical_finalization.py` | canonical governance and acceptance | yes on production finalization | canonical EvidenceStatus | exact run/candidate/source identity, recomputed source hash, inspected test/runtime/visual evidence, README/entrypoint/dependency/platform/startup/error checks, blockers and evidence hashes | Provider or surrogate claims cannot replace this local inspection |
| `CGKNCanonicalGovernanceReport` | inline v1 contract | `scripts/canonical_finalization.py` consuming `scripts/product_design_depth_governance.py` | acceptance and public claim policy | yes on production finalization | canonical EvidenceStatus | candidate hash, local evaluator identity/version, frozen contract hashes, maturity ceiling, proxy and real-world result, allowed/forbidden claims | same-named Provider files and surrogate recommendations have no authority |
| `CGKNCanonicalAcceptanceDecision` | inline v1 contract | `scripts/canonical_finalization.py` | final promotion | yes before promotion | canonical EvidenceStatus | run/candidate/source identity, verification and governance hashes, maturity, blocker count, independent local acceptance authority and reason | candidate PASS or Provider release recommendation cannot accept itself |
| `CGKNCanonicalPromotionManifest` | inline v1 contract | `scripts/canonical_finalization.py` | local packager | yes before production packaging | canonical EvidenceStatus | accepted candidate, source hash, parent lineage, acceptance/verification/governance hashes, local promotion authority, immutable-content flag | candidate-only and rejected candidates cannot be packaged; repeated promotion is idempotent |
| `CGKNCanonicalFinalizationState` | inline v1 contract | `scripts/canonical_finalization.py` | Codex conversation supervision and delivery reporting | workflow support only | not EvidenceStatus | ordered states from candidate materialization through verification, governance, acceptance, review, promotion, packaging, delivery gate, and delivered | state names never substitute for evidence PASS |
| `CGKNDeliveryManifest` | `schemas/delivery_manifest_v1.schema.json` | `scripts/local_packager.py` | public delivery gate, Codex conversation delivery sender, final verdict | yes | `PASS`, `PASS_WITH_LIMITS`, `NEEDS_REWORK` | envelope, source tree hash, package hash, package entries hash, candidate hash, test/runtime/visual evidence plus user review request/review refs and hashes when required | replaces unversioned delivery bundle success records |
| `CGKNDeliveryReceipt` | `schemas/delivery_receipt_v1.schema.json` | `scripts/canonical_delivery_receipt.py` | Codex conversation final sender, active project binder, final verdict | yes | `PASS`, `FAIL`, `NEEDS_REWORK` | envelope, delivery attempt/candidate/manifest/package binding, frozen requirements, exact attachment kinds, Codex conversation chat/message/file identities, local hashes, started/sent/finished timestamps | replaces boolean `sent` checks and pre-send delivered markers |
| `CGKNFormalGateStatus` | `schemas/formal_gate_status_v1.schema.json` | `scripts/formal_mainline_acceptance.py` | `scripts/acceptance_verifier.py` | read-only formal acceptance | canonical EvidenceStatus | envelope, candidate or repository scope, authoritative source ref/hash/producer, registered inspector and actual result, failures and blocker code | replaces handwritten wrapper PASS and `source_inspection="PASS"`; cannot replace its canonical source artifact |
| `CGKNFinalVerdict` | `schemas/final_verdict_v1.schema.json` | `scripts/acceptance_verifier.py` | CLIs, reports, final user-visible completion | yes | canonical EvidenceStatus | envelope, required gates, upstream gate statuses, independently inspected veto-only support prerequisites, overall status | replaces runner-local final PASS decisions; support prerequisites cannot replace formal gates or authorize PASS |

`scripts/final_internal_acceptance.py` and its `CGKNInternal*Evidence` files are diagnostic fixtures, not formal artifacts. The producer provenance denylist prevents them, `tests/*`, fixtures, examples, demos, and benchmark-only producers from authorizing a formal Gate PASS.

## Consumer-project governance support artifacts

| Artifact kind | Definition | Producer | Authority boundary |
| --- | --- | --- | --- |
| `CGKNConsumerGovernanceResult` | `cgkn/governance/consumer.py` | `scripts/consumer_governance.py verify` | executable architecture-memory support result; never formal delivery evidence |
| `CGKNLongitudinalGovernanceTimeline` | consumer `.cgnk/governance/history.json` plus immutable invariant registry | `scripts/consumer_governance.py history` | historical PASS/FAIL/NOT_APPLICABLE/UNKNOWN assessment; UNKNOWN never promotes to PASS |
| consumer governance lock | consumer `.cgnk/governance/governance.lock.json` | explicit `record` after clean strict PASS | content and tool pin; does not authorize Provider, packaging, delivery, or owner acceptance |

Consumer-governance command decisions use `PASS`, `BLOCK`, `NEEDS_USER_REVIEW`,
and `UNKNOWN` as command-result states. They are not canonical formal
`EvidenceStatus` values and cannot be substituted into formal delivery gates.

## Project Management Support Artifacts

These artifacts support CGKN self-hosting and generated-project planning. They
are not formal delivery evidence and cannot authorize a formal gate.

| Artifact kind | Schema | Producer | Consumers | State rules |
| --- | --- | --- | --- | --- |
| `CGKNAdaptiveProjectManagementPack` | `schemas/adaptive_project_management_pack.schema.json` | `scripts/pmp_agile_quality_manager.py` or an approved project-management agent | project lead, context librarian, provider planning context | `workflow_state` is not EvidenceStatus; `evidence_status` uses only canonical values |
| `CGKNAdaptiveIteration` | `schemas/adaptive_iteration.schema.json` | approved `manage-pmp-agile-quality` workflow | implementation, QA, review, retrospective | iteration workflow state is separate from canonical evidence evaluation |
| `CGKNEnterpriseExperiencePack` | `schemas/enterprise_experience_pack.schema.json` | approved project review and retrospective workflow | project lead and bounded librarian retrieval | `experience_state` is `candidate`, `validated`, `approved`, or `retired`, never EvidenceStatus |
| `CGKNAdaptiveProjectManagementContext` | bounded inline projection of the three schemas above | `scripts/adaptive_project_management_context.py` | existing provider component and leaf context | support context only; selects no more than four validated/approved experience items and cannot authorize a formal gate |
| `CGKNProjectDecompositionTree` | `schemas/project_decomposition_tree.schema.json` plus required `artifacts/project_decomposition_tree.json` | `scripts/decomposition_tree.py`, invoked by the production mainline before Provider generation | generation plan, existing ProviderJob DAG, issue ledger, issue-level repair acceptance, canonical evidence reporting | one stable node-id namespace is shared by Plan Tree, Issue Tree, and Evidence Tree; every repairable issue and production repair action must bind an exact node; unmapped failures cannot create generic repair; support index only with `release_authority=false` |
| `WorkNode` | minimal inline dataclass | `scripts/work_nodes.py` and canonical planning projections | bounded agent/deterministic execution context; Provider nodes adapt through `scripts/provider_jobs.py` | sole agent-facing execution contract; no scheduling, Provider, evidence, packaging, or release authority; ProviderJob remains the production concurrency unit |
| `CGKNCapabilityPlan` / reuse decision / skill candidate | minimal inline JSON from `scripts/capability_execution.py` | capability planning, bounded executor selection, iteration review | existing WorkNode DAG and context librarian | support planning only; capability interfaces precede implementation; external reuse uses adapters; candidates have `experience_state=candidate`, cannot alter `skills/`, and grant no acceptance or release authority |
| `CGKNCompactProviderLeafRequest` | deterministic hard-bounded inline request | `scripts/run_local_pipeline_impl.py` at the qualified Alibaba Qwen3.8 Responses ownership-unit boundary | existing API Provider component-file generation and local Provider-output validators | contains one single- or multi-path ownership-unit contract, direct interfaces, bounded invariants/context, newest repair delta, output-size budget, and exact response shape; trims lower-priority duplicated detail to a configured hard character ceiling while retaining omitted detail and its identity locally; cannot authorize evidence, package, delivery, or create another generation route |
| `GoalSpec` | deterministic inline object plus `requirement_decision/goal_spec.json` | `scripts/requirement_decision_lane.py` | requirement blueprint, Provider component/leaf context, controlled Agent Tree | canonical project-goal planning truth; `PASS` or `NEEDS_REWORK`; never formal delivery evidence |
| `GoalDrivenProjectPlan` | deterministic inline object plus `requirement_decision/project_plan.json` | `scripts/requirement_decision_lane.py` | Provider component/leaf context, controlled Agent Tree, later goal-acceptance input | business workstreams, leaves, dependencies, outputs, structure, and test intents; cannot authorize formal delivery PASS |
| `CGKNFeatureContract` | deterministic inline object inside `GoalSpec`, `GoalDrivenProjectPlan`, component manifests, and compact Provider leaves | `scripts/requirement_decision_lane.py` from each explicit typed operation | existing Provider component-file generation, focused generated tests, local validators, and isolated repair selection | freezes one public entrypoint, typed inputs/output, declared errors, explicit side effects, dependencies, owned paths, acceptance checks, and interface hash; support planning truth only and cannot authorize evidence, packaging, or delivery |
| `CGKNFeatureInterfaceFreeze` | deterministic hashed inline object inside `GoalSpec`, `GoalDrivenProjectPlan`, and the executable interface graph | `scripts/requirement_decision_lane.py` after feature ownership conflict checks | dependency-ready Provider leaf batching, compact Provider requests, checkpoint identity, and repair closure | binds the complete feature set and unique owned-path index before generation; rejects ownership conflicts and prevents an isolated repair from expanding unrelated feature scope; cannot write source or authorize formal delivery PASS |
| `CGKNFeatureUnitSemanticReviewRequest` | deterministic bounded inline Provider request | `scripts/run_local_pipeline_impl.py` after all feature-unit leaves pass local output boundaries | existing Provider semantic-review stage | contains only the raw goal, frozen feature contracts/interface hash, negative scope, declared entrypoints, exact file manifest, complete bounded source/configuration text, short narrative-document excerpts, and review rules; Qwen Responses requests use no reasoning and an 1,800-token ceiling; replaces the generic multi-review expansion for this architecture only and cannot bypass deterministic tests, evidence, packaging, or delivery gates |
| `CGKNExecutableInterfaceGraph` | deterministic hashed inline projection inside the reviewed component pipeline | `scripts/run_local_pipeline_impl.py` | Provider implementation/test leaves, component quality validation, checkpoint identity | binds uniform stage callable/result/test-observation semantics plus runtime artifacts and report formats; support interface truth only and cannot authorize formal delivery PASS |
| `CGKNGoalAcceptance` | deterministic inline support receipt plus `artifacts/goal_acceptance.json` | `scripts/goal_acceptance.py` through existing post-build finalization | candidate review readiness and `scripts/acceptance_verifier.py` veto-only prerequisite inspection | canonical EvidenceStatus for the receipt; binds goal/plan identity, exact substantive test symbols and source hashes, and an execution summary cross-checked against canonical `test_execution.json`; when applicable, missing/change/non-PASS forces final `NEEDS_REWORK`, but PASS cannot replace the registered test inspector, any formal gate, or authorize formal delivery PASS |
| `CGKNGeneratedComponentQualityValidation` | deterministic inline support receipt | `scripts/run_local_pipeline_impl.py` | provider component checkpoint reuse, downstream component feedforward, assembled-project validation | lower-case internal `pass`/`fail`; rechecks current files and cannot authorize formal delivery PASS |
| `CGKNAssembledProjectQualityValidation` | deterministic inline support receipt | `scripts/run_local_pipeline_impl.py` | provider generation quality gate and post-build continuation | lower-case internal `pass`/`fail`; failure blocks generation success while canonical test/runtime/visual evidence remains separately required |
| `CGKNCrossValidationFeedforwardReceipt` | deterministic inline receipt plus per-run component and aggregate JSON artifacts | `scripts/cross_validation_feedforward.py`, invoked by `scripts/run_local_pipeline_impl.py` | component publication, checkpoint reuse, downstream feedforward, pre-post-build continuation | lower-case internal `pass`/`fail`; cross-binds plan, current files, quality, implemented interfaces, and upstream receipts; veto-only and explicitly cannot assert formal evidence, package, or deliver |
| `CGKNCrossValidationFeedforwardProjection` | deterministic bounded inline projection | `scripts/cross_validation_feedforward.py` from a verified passing component receipt | next component's `CGKNIntegrationFeedforwardSnapshot` | carries only identity, validated paths, and receipt/registry hashes; a failed or tampered receipt produces no projection and cannot feed downstream generation |
| `CGKNDesignResearchManifest` | deterministic JSON plus Markdown support projection | `scripts/design_research_agent.py` | existing Provider planning context and generation-context librarian | `workflow_state` is not EvidenceStatus; source references, three directions, selected contract, tokens, and anti-copying boundaries cannot authorize formal delivery PASS |
| `CGKNBoundedDesignContext` | bounded inline projection | `scripts/design_research_agent.py` | frontend, media, and docs leaf generation through the existing librarian | no more than six relevant references plus the selected direction and design contract; context hash is support identity only |
| `CGKNGeneratedDesignQualityValidation` | deterministic inline support receipt | `scripts/run_local_pipeline_impl.py` | component and assembled-project quality validation | lower-case internal `pass`/`fail`; checks design source/docs traceability and implemented source constraints but cannot replace canonical browser visual evidence or user review |
| `CGKNCodexCapabilityEscalation` | `schemas/codex_capability_escalation.schema.json` | `scripts/codex_capability_supervisor.py` from librarian-selected context and failure evidence | explicitly invoked external Codex capability supervisor | secret-redacted, bounded, and request-hashed support context only; grants no candidate-write, formal-evidence, package, or delivery authority |
| `CGKNCodexCapabilitySupervisorResponse` | `schemas/codex_capability_supervisor_response.schema.json` | external Codex through the approved `supervise-cgkn-capabilities` skill and deterministic sealing helper | `scripts/codex_capability_supervisor.py`, CFO/support workers, existing Provider planning context when explicitly selected | workflow state is `ready`, `needs_context`, or `declined`; formal evidence is fixed `NOT_EVALUATED`; response cannot contain source files, patches, final verdicts, packages, or delivery approval |
| `CGKNCodexCapabilityBrief` | `schemas/codex_capability_brief.schema.json` | `scripts/codex_capability_supervisor.py` after request/response identity and authority validation | existing `agent_session`, bounded whiteboard support state, retained support pipeline, and explicitly selected reviewed formal Provider planning context | full brief is revalidated and retained as support evidence; only a bounded advisory projection enters Provider planning/components; brief hash binds checkpoint reuse; cannot write a candidate or replace Provider output validation, canonical evidence, `local_packager`, or `public_delivery_gate` |
| `CGKNCodexCapabilityPlanContract` | deterministic inline projection bound inside `generation_plan_checkpoint.json` | `scripts/run_local_pipeline_impl.py` from one validated `CGKNCodexCapabilityBrief` projection | Requirement Decision Lane, existing Provider component/leaf context, checkpoint identity | exact brief paths, public symbols, entrypoints, safety limits, and acceptance-check hash are planning constraints only; drift blocks source generation; grants no candidate-write, formal-evidence, package, or delivery authority |
| `CGKNRuntimeSupervisionCheckpoint` | deterministic hash-linked JSONL support envelope | `scripts/cgkn_supervision_protocol.py`, invoked by the CGKN Codex conversation service | persistent Codex supervisor host | binds sequence, prior hash, repository/chat/project/run identity, checkpoint type, bounded context references, requested action, and fixed no-authority fields; contains no credential and is not formal evidence |
| `CGKNRuntimeSupervisionResult` | deterministic hash-bound support receipt constrained by `schemas/runtime_supervision_draft.schema.json` | `scripts/cgkn_runtime_supervisor.py` after one start/resume turn on the stored Codex thread | deterministic supervision router, `agent_session`, supervisor cursor | canonical action is only `resume`, `rework_project`, `recheck_evidence`, `repair_kernel`, `user_decision`, or `halt`; scope and evidence refs make routing explicit; no action grants candidate, evidence, package, or delivery authority |
| `CGKNSupervisionRouteReceipt` | deterministic hash-bound support routing receipt | `scripts/cgkn_supervision_router.py` from one validated supervision result | production consumer in `scripts/codex_conversation.py` | records one typed next action without an LLM; Provider authors project repairs, verifier rechecks evidence, and kernel repair remains separately allowlisted; never formal evidence or delivery authority |
| `CGKNSupervisionRouteConsumptionReceipt` | deterministic support completion receipt | production consumer in `scripts/codex_conversation.py` after a route is executed or explicitly stopped | supervisor diagnostics and bounded re-audit control | binds the original route, action outcome, and recovery receipt; clears the matching pending receipt; cannot authorize evidence, packaging, delivery, or PASS |
| `CGKNSupervisionProviderRepairPlan` / `CGKNSupervisionProviderRepairPreparationReceipt` | bounded support repair plan/receipt | `scripts/run_local_pipeline_impl.py` from a validated `rework_project` audit | existing same-run Provider semantic/leaf repair executor | maps exact file/leaf/component targets when available and otherwise only the affected audited scope; no second Provider scheduler or generation route |
| `CGKNSupervisionEvidenceInvalidationReceipt` | deterministic support invalidation receipt | production consumer in `scripts/codex_conversation.py` from `recheck_evidence` | the corresponding canonical validation/runtime/visual/evidence rerun | moves only in-scope stale evidence out of the active chain, records zero Provider calls, and has no formal evidence authority |
| `CGKNProviderExecutionMetrics` | durable support metrics JSON | `scripts/provider_execution_metrics.py` during the formal Provider route | operations, acceptance reports, diagnostics | records Provider API call count, actual peak request concurrency, unique Provider jobs, owned-file count, average files/job, DAG wave widths and critical-path waves, fragmentation ratio, repaired/reused job counts, and stage timing; metrics cannot authorize evidence or delivery |
| `CGKNGovernedKernelRepairRequest` / `CGKNGovernedKernelRepairReceipt` | bounded support request/receipt | `scripts/governed_kernel_repair.py` from `repair_kernel` | isolated Codex workspace-write executor and original-checkpoint re-audit | requires reproduction plus regression target, copies back only declared CGKN-owned paths, and excludes candidates, artifacts, runs, workspaces, packages, and delivery authority |
| `CGKNRuntimeSupervisorState` | project-local deterministic support JSON under `.cgkn/runtime_supervisor/` | `scripts/cgkn_runtime_supervisor.py` | supervisor reattachment, health/status, checkpoint continuity | stores supervisor/thread/process/repository/cursor/restart workflow identity without secrets; file or process presence is not readiness or formal evidence |
| `CGKNProjectGenerationBenchmarkCaseCatalog` | `schemas/project_generation_benchmark_case_v1.schema.json` | `benchmarks/project_generation_v1/cases.json` | independent project-generation benchmark runner and evaluator only | fixed evaluation input; `hidden_acceptance` is evaluator-only and must never enter Provider, Codex, planner, or production candidate context |
| `ProjectBenchmarkExternalObservation` | identity-bound inline JSON under `artifacts/project_generation_benchmark/<run_id>/cases/<case_id>/evidence/` | independent process, HTTP, browser, persistence, file/package, or controlled-fault probes | project-generation benchmark evaluator only | binds benchmark run, case, and exact candidate tree hash; CGKN verdicts, Provider claims, README claims, fixtures, and stale observations cannot replace it or authorize formal PASS |
| `CGKNProjectGenerationBenchmarkReport` | `schemas/project_generation_benchmark_report_v1.schema.json` | `benchmarks/project_generation_v1/run_benchmark.py` | engineering comparison and release-readiness review | evaluation/acceptance support only; separates `PROJECT_PASS`, `PROJECT_FAIL`, `BLOCKED_PROVIDER`, and `NOT_EVALUATED`, and can neither promote formal evidence nor authorize packaging or delivery |

The support flow is:

```text
tailored management context
-> existing provider component and leaf generation
-> canonical quality evidence
-> review and retrospective
-> evidence-backed enterprise experience
```

It does not alter the formal Codex conversation mainline or the sole delivery exit.

## Runtime Supervision Architecture Baseline

`docs/14_codex_cgkn_runtime_supervision_baseline.md` is the normative authority
for runtime ownership among Codex, CGKN, and Codex conversation:

- CGKN is the independently running system and owns Codex conversation intake, durable
  project state, the reviewed Provider route, evidence orchestration, packaging,
  and delivery handoff.
- the active Codex task is the sole CGKN-owned interaction surface; it
  are not direct Codex transports or alternate generation routes.
- Codex starts or attaches to CGKN and resumes one identity-bound persistent
  supervision thread at declared checkpoints.
- A bounded Codex repair may modify CGKN-owned code, configuration,
  documentation, or tests and must produce an auditable diff plus proportionate
  regression before resume.
- Codex cannot impersonate Provider, author a sealed generated candidate,
  promote workflow state to formal evidence, package, or authorize delivery.
- Request-scoped or ephemeral Codex calls are bounded specialist/transitional
  adapters and cannot satisfy persistent-supervision conformance by themselves.
- Public runtime selection is limited to two mutually exclusive support
  profiles: `API-only` disables every Codex path, while the branch distribution
  `CGKN Codex Edition` forces the one-shot design CLI off and uses one persistent supervisor thread.
  Their sessions, logs, uploads, project memory, Provider candidate roots, and
  supervisor state are isolated. Both profiles enter the same formal Codex conversation
  Provider mainline below.

Supervisor instance identity, Codex thread identity, process health,
checkpoint cursors, repair receipts, and restart counters are support/workflow
state. They are not formal artifacts or EvidenceStatus. Persistent supervision
remains `NOT_EVALUATED` until runtime evidence demonstrates same-thread resume,
checkpoint continuity, permitted repair plus regression, forbidden-action
rejection, and failure recovery while retaining the registered Provider and
`local_packager` route.

## Formal Codex conversation Mainline

```text
customer request
-> API/provider project generation
-> provider response staging
-> response content -> implementation decisions -> patch hunks
-> patch application to production candidate
-> provider output validation
-> source-changing post-build finalization
-> canonical production-candidate provenance
-> canonical provider causal trace
-> canonical test/runtime/visual evidence
-> canonical product-governance evaluation
-> hash-bound acceptance decision
-> idempotent final promotion
-> user review when required
-> local_packager
-> public delivery gate
-> delivery receipt
-> bind active project
-> canonical final verdict
```

`pipeline_manifest` and `dynamic_pipeline_runner` remain the support/experimental planning lane. They may produce upstream evidence, but they are not a second Codex conversation public delivery route.

## Formal Acceptance Gate Registry

`scripts/formal_mainline_acceptance.py` reads existing artifacts only. It never runs a project team, replan, recovery, provider, packager, Codex conversation sender, or provenance producer. `candidate_hash` is the canonical customer source hash; repository `commit_sha` is a separate repository-scoped identity.

The Codex conversation production entry assigns a unique production `run_id` and `candidate_id`, and the provider job freezes ordered `production_entry`, `provider_generation`, `provider_validation`, and `post_build` receipts. The provider writes response files to run-unique staging; the bridge freezes request/response content, derives decisions and hunks, and applies them to the production candidate before validation. After source-changing repair work and before canonical tests, `scripts/production_candidate_provenance.py` writes `production_candidate_provenance.json`, and the bridge finalizes `provider_causal_trace.json`, under that production run. Their inspectors independently reread every referenced artifact, validate time and identity continuity, reject path escape and reparse links, reconstruct patch application and post-build delta, and recompute the source manifest and sole canonical candidate source hash. Test, runtime, and visual Gates cannot run their evidence inspector until both provenance and causal trace pass; caller booleans or `source_inspection="PASS"` have no authority.

| Gate | Scope | Authoritative producer | Inspector | Source artifact | Current formal availability |
| --- | --- | --- | --- | --- | --- |
| test execution | candidate | `scripts/real_test_execution.py` | `scripts.real_test_execution.inspect_test_report` | `test_execution.json` plus `TEST_REPORT.md` | available |
| customer runtime | candidate | `scripts/customer_runtime_runner.py` | `scripts.customer_runtime_runner.inspect` | `customer_runtime.json` | available |
| visual evidence | candidate | `scripts/browser_visual_evidence.py` | `scripts.browser_visual_evidence.inspect` | `visual_evidence.json` and bound screenshot/runtime | available |
| media evidence | candidate | `scripts/canonical_media_validation.py` | `scripts.canonical_media_validation.validate_media` | no aggregate production artifact contract | `NOT_EVALUATED` until a production artifact binds the validated assets |
| user review | candidate | `scripts/canonical_user_review.py` | `inspect_user_review_request` then `inspect_user_review_evidence` | `user_review_request.json`, `user_review.json`, replay ledger, presented artifacts | available when a real Codex conversation review exists |
| delivery manifest | candidate | `scripts/local_packager.py` | `scripts.canonical_delivery_manifest.inspect_canonical_delivery_manifest` | `delivery_manifest.json`, final ZIP, evidence refs | available |
| delivery receipt | candidate | `scripts/canonical_delivery_receipt.py` | `scripts.canonical_delivery_receipt.inspect_canonical_delivery_receipt` | `delivery_receipt.json`, manifest, package, exact Codex conversation receipts | available with frozen send expectations |
| full_all | repository | `scripts/run_test_profile.py` | `scripts.formal_gate_registry.inspect_full_all` | `full_all_result.json`, stdout/stderr hashes | available |
| provider causal trace | candidate | `scripts/codex_conversation.py` | `scripts.provider_causal_trace.inspect` | `provider_causal_trace.json` plus bound request/response/decision/patch/application/provenance artifacts | available for a formal provider run; otherwise `NOT_EVALUATED` |
| leaf profile | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| workspace truth | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| replan | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| recovery | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| collaboration timing | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| startup profile | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| deterministic E2E | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |
| live provider E2E | candidate | none registered | none registered | none registered | `NOT_EVALUATED` |

The production Codex conversation entry is `scripts.codex_conversation.start_generation_from_income`; its default generation target is `run_provider_generation_job`, followed by provider output validation, source-changing post-build work, canonical production-candidate provenance, canonical test/runtime/visual evidence, canonical review when required, `local_packager.package_project`, public delivery gate, manifest-bound send, `CGKNDeliveryReceipt`, and canonical final verdict. `run_agent_generation_job -> dynamic_pipeline_runner.run_dynamic_pipeline -> agent_conversation_loop.run_agent_loop` remains the support/experimental lane.

## Runtime And Visual Evidence Definitions

Real runtime evidence means a clean environment is created, dependencies are prepared, the generated project starts as a real OS process, a PID is recorded, a health probe succeeds, a customer operation is executed, the observed result is verified and hashed, and the process is stopped.

Real browser visual evidence means Playwright or an equivalent browser automation tool opens the same runtime URL, performs a customer action, verifies DOM assertions and relevant network observations, captures a screenshot, and records the screenshot hash in `CGKNVisualEvidence`.

`PASS_WITH_LIMITS` is not accepted for public final delivery. It may be used for internal evidence that is honest but incomplete, and final delivery must remain `NEEDS_REWORK` until required public artifacts are complete.

## Legacy Boundary

Legacy status names and old compact Product Studio outputs are allowed only under `legacy/` or explicit compatibility notes. Formal code must not consume those names directly; use `legacy/status_adapter.py` when a historical artifact must be interpreted.

## Surrogate Provider handshake registry

`contracts/surrogate_provider_handshake_v1.schema.json` defines the canonical
`CGKNProviderJobRequest`, surrogate/replay response, and
`CGKNProviderResponseReceipt` envelopes. Their authoritative producer and
consumer are `scripts/surrogate_provider_adapter.py` beneath the production
`provider_text` boundary. The envelopes are workflow/accounting artifacts with
formal evidence `NOT_EVALUATED`; they cannot authorize candidate acceptance,
maturity, packaging, or delivery. `WAITING_SURROGATE_RESPONSE` is a resumable
workflow state, not an EvidenceStatus.

## Canonical Requirement Compiler Registry

| Artifact | Schema / producer | Consumer | Authority boundary |
| --- | --- | --- | --- |
| `CGKNRequirementsPlanningProposalArtifact` | `contracts/requirements_planning_proposal_v1.schema.json`; formal `requirements_planning` Provider stage plus local transport validation | `scripts/canonical_goal_spec_compiler.py` | proposal authority only; hash-bound to raw goal and accepted/consumed Provider request identity; no governance, acceptance, maturity, candidate, packaging, or release authority |
| `GoalSpec` v2 | `contracts/canonical_goal_spec_v2.schema.json`; `scripts/canonical_goal_spec_compiler.py` inside Requirement Decision | Project Plan and unchanged downstream design lane | sole canonical requirement projection; includes raw/normalized goal, capabilities, workflows, workstreams, constraints, non-goals, questions, assumptions, anchors, forbidden substitutions, source refs, field provenance, compiler identity, self-hash, and local authority decision |
| `CGKNRequirementReplanState` | inline v1 contract; canonical requirement loop | same-run Provider scheduler and formal request/submit/resume | workflow support only; `WAITING_REQUIREMENT_REPLAN`, `RESOLVED`, or `REPLAN_EXHAUSTED` are not EvidenceStatus; bounded to three attempts and cannot invoke candidate repair |
| `CGKNSourceIdentityReport` | inline v1 contract; `scripts/source_identity.py` | run audit and acceptance reporting | immutable start-of-run support identity with `NOT_EVALUATED`; hashes source state but grants no evidence or delivery authority |

Canonical requirement provenance labels are `USER_EXPLICIT`, `USER_CONTEXT`,
`NECESSARY_INFERENCE`, `PROVIDER_PROPOSAL`, `SYSTEM_POLICY`, and `UNGROUNDED`.
`UNGROUNDED` values remain visible for diagnostics but cannot become hard
requirements. Live, Codex surrogate, and deterministic replay modes all use the
same compiler and authority boundary.

## Product Design Depth Governance Registry

All artifacts below use `contracts/product_design_depth_governance_v1.schema.json`. Their hashes freeze design intent or make post-build maturity evaluation tamper-evident. They are governance/support records and do not themselves grant a formal `EvidenceStatus` or authorize delivery.

| Artifact | Producer | Consumer | Authority boundary |
| --- | --- | --- | --- |
| `CGKNGoalFidelityContract` / `goal_fidelity_contract.json` | `scripts/product_design_depth_governance.py` in Requirement Decision | technical design, Provider prompt, Product Challenge Review | freezes original outcome, core capabilities, allowed scope reductions, and forbidden simplifications before implementation |
| `CGKNProjectComplexityProfile` / `project_complexity_profile.json` | same | design-depth and test-depth selection | classifies `SIMPLE`, `STANDARD`, `COMPLEX`, or `HIGH_RISK`; cannot authorize PASS |
| `CGKNCoreDifficultyLock` / `core_difficulty_lock.json` | same | Provider, proxy detector, replan evaluator | prevents an MVP from deleting or proxying the core difficulty without an explicit maturity cap |
| `CGKNTestRealismContract` / `test_realism_contract.json` | same | test-resource planning and maturity evaluator | freezes real, synthetic, variation, adversarial, negative-control, and holdout requirements |
| `CGKNChallengeMatrix` / `challenge_matrix.json` | same | independent product challenge verifier | domain-derived counterexamples frozen before implementation; builder tests cannot edit acceptance after seeing failures |
| `CGKNDesignAdequacyReport` / `design_adequacy_report.json` | same | Product Challenge Review | records risk-proportionate alternatives, tradeoffs, data/state/long-task/performance/dependency/failure design |
| `CGKNProductChallengeReview` / `product_challenge_review.json` | independent challenger role in the deterministic requirement lane | implementation-entry decision | verdict is `DESIGN_READY`, `DESIGN_READY_WITH_DECLARED_PROXY`, `REPLAN_CORE_CAPABILITY`, or `BLOCKED_MISSING_EVIDENCE`; no delivery authority |
| `CGKNOverengineeringCheck` / `overengineering_check_report.json` | requirement lane | Product Challenge Review | rejects unsupported components and future features; complexity is justified by requirements and risk, not volume |
| `CGKNProxySolutionReport` / `proxy_solution_report.json` | post-build maturity evaluator | public gate and design replan | detects proxies, affected core capability, user-goal impact, and maximum allowed maturity |
| `CGKNProductMaturityReport` / `product_maturity_report.json` | post-build maturity evaluator | `local_packager` inputs and public gate | records `DEMO`, `PROTOTYPE`, `FUNCTIONAL_MVP`, `TARGET_VALIDATED`, or `PRODUCTION_READY`; separate from pipeline/artifact verdicts |
| `CGKNPublicClaimPolicyReport` / `public_claim_policy_report.json` | post-build maturity evaluator | public narration | keeps delivery eligibility separate from target satisfaction and enumerates allowed/forbidden claims |
| `CGKNDesignReplanReport` / `design_replan_report.json` | post-build maturity evaluator | existing affected-issue Provider repair planning | scopes replan to the locked capability and preserves unaffected validated components; no second repair system |

Only `CGKNIndependentProductEvidence` produced by the independent challenge verifier in the production run directory, with a valid producer identity and artifact hash, can raise a complex product to `TARGET_VALIDATED`. A similarly named file inside Provider-owned candidate source has no maturity authority.
