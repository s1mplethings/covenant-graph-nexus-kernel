# ITER-CGNK-MATERIALIZATION-FULL-VALIDATION-AND-MODEL-CAPABILITY-037

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Original base: `codex/safe-acceptance-attribution-20261020` at `2247e9bf291ef0a523253853a6b19585c0f43db4`
- Working branch: `codex/full-materialization-model-eval-20261020`
- Source Closure: `d7d9ca4b774044d5915e8f917d578220f3d48e42`
- Source tree: `7832a018b941bac9237d05cbad2e07996a5b42c6`
- Evidence Closure: the evidence-only publication commit containing this report
- Force push: no
- PR: none

## 2. Previous Confirmed Failures

The previous cohesive Tests Unit repeatedly omitted the same owned file. Each incomplete response caused the full Unit to be regenerated, wasting already-correct file output and context. The terminal result was `UNIT_OUTPUT_INCOMPLETE`, six of eight logical calls were consumed, and `real_generation` remained `FAIL`.

## 3. Corrections to Previous Design

The implementation separates `GENERATION`, `GENERATION_CONTINUATION`, `GENERATION_RETRY`, and `REPAIR`; validates each response before merging it into isolated staging; retains prior valid slices across retryable continuation failures; treats already-staged returned paths as scope violations; detects no-progress stalls without conflating transport/schema failures; and uses controlled all-or-nothing apply with rollback rather than claiming filesystem-wide atomic rename.

## 4. Incremental Materialization Implementation

- Primary implementation: `cgkn/application/project_loop.py`
- Supporting contracts and CLI: `cgkn/application/project_blueprint.py`, `cgkn/application/software_project/scope.py`, `scripts/run_project_mvp.py`, and `scripts/run_role_model_efficiency.py`
- State machine: `EMPTY -> PARTIAL/COMPLETE -> VALIDATING -> VALIDATED -> COMMITTING -> COMMITTED`, with terminal discard/failure states.
- Each call receives exact `requested_paths`; dynamic FileBundle schemas enumerate only those paths.
- Partial valid files remain outside the public workspace until complete validation.
- Complete Units pass coverage, scope, syntax, interface, budget, cross-file, and required-interface checks before controlled commit.
- Baselines are registered only after successful commit; repair cannot start from partial staging.

## 5. Fake Validation

Cases A-O all pass: two-slice completion; three-slice completion; already-staged scope violation; extra-path rejection; syntax-invalid continuation with retained prior staging; provider failure with retained staging; budget-exhaustion discard; duplicate rejection; first-response completion; post-commit-only baseline; bounded continuation ledger; whole-Unit interface rejection; mid-commit rollback; hidden-acceptance exclusion; and exact dynamic schema enumeration.

## 6. Worker Live Probe

Both independent probes owned `tests/test_cleaner.py` and `tests/test_cli.py` and completed in one `GENERATION` call, so no continuation was needed.

| Run | Calls | Input | Output | Duration | Result |
|---|---:|---:|---:|---:|---|
| `worker-cohesive-live-1-675a7431e5` | 1 | 1028 | 1046 | 4821 ms | PASS, syntax PASS, committed |
| `worker-cohesive-live-2-c2b32db626` | 1 | 1028 | 1215 | 3650 ms | PASS, syntax PASS, committed |

Evidence: `D:/CGKN/.service_evidence/ITER-CGNK-MATERIALIZATION-FULL-VALIDATION-AND-MODEL-CAPABILITY-037/worker-cohesive-live-source-d7d9ca4`.

## 7. CSV Single

The final Source Closure did not produce a completed Blueprint. Attempt one made one Qwen Coordinator call and returned 335 input / 2889 output tokens, but no unique schema-valid design was accepted. Attempt two made one call and ended in HTTP 504 after 90.5 seconds; actual token usage is unknown, not zero. Earlier diagnostic Source Closures reached Unit execution but failed within the fixed eight-call budget. Compile, pytest, runtime, hidden acceptance, and attribution were therefore not reached. Final status: `MINIMAL_BLUEPRINT_NEEDS_REWORK`.

## 8. Seeded Repair

Not evaluated because CSV Single did not pass Phase E. No seeded defect, PatchBundle, invalidation, or hidden-acceptance result is claimed.

## 9. CSV 3/3

Not evaluated because the Phase E prerequisite failed. No old or cross-Source runs were reused.

## 10. M0 vs M1

Not evaluated because the required CSV Single, Seeded Repair, and repeatability gates did not pass. `INCREMENTAL_MATERIALIZATION_BENEFIT = NOT_EVALUATED`; implementation correctness is proven, cost/token benefit is not.

## 11. Role / Model Efficiency

V0, V0B, V1, and V2 were not run. `BLUEPRINT_BENEFIT`, `ROLE_SEPARATION_BENEFIT`, and `CHEAP_EXECUTOR_BENEFIT` remain `NOT_EVALUATED`. Official pricing was not captured, so cost conclusions are also `NOT_EVALUATED`.

## 12. Formal Server Evaluation

Not evaluated due to the Phase E gate. No server boot, registry, fallback, recovery, or conversation capability claim is made.

## 13. Model Capability Benchmark

The 24-case benchmark was not started because earlier phases did not pass. Raw, structured-output, planning, generation, continuation, repair, grounding, abstention, contradiction, and adversarial capability ratings remain `NOT_EVALUATED` except for retained Coordinator qualification and the new Worker 2/2 live result.

## 14. CGNK Structure Evaluation

R0 Raw, R1 Flat Retrieval, and R2 CGNK were not run. Localized retrieval, hierarchical reasoning, context efficiency, and overall structure benefit remain `NOT_EVALUATED`.

## 15. Security

- Hidden source/assertion leakage: none observed
- Secret persistence: false
- Unauthorized owned-path writes: rejected by dynamic schema and deterministic scope validation
- Partial staging exposure: zero by design and fake tests
- Manual candidate edits: zero
- Hidden acceptance live exercise: not reached

## 16. Kernel Regression

- Compile and product/kernel/test architecture/completeness gates: PASS
- Receipt verification and freshness: PASS
- static, unit, boundary, fault, security, local-functional, full-core, active-repository: PASS
- active-repository/full pytest: 2584 passed, 351 skipped, 0 failed, 0 errors
- application: 392 passed, 1 skipped
- live-provider profile: `BLOCKED_ENVIRONMENT`, one selected test skipped
- Kernel receipt: `sha256:9417888f1f82c49a883d632e873f1acd02d070702b1f738ad9109dc43f132727`

## 17. Final Readiness

- `kernel_foundation = COMPLETE`
- `minimal_blueprint_status = PARTIAL`
- `incremental_materialization_status = PASS`
- `real_generation = FAIL`
- `real_repair = NOT_EVALUATED`
- `csv_repeatability = NOT_EVALUATED`
- `efficiency_experiment_ready = false`
- `formal_server_evaluation = NOT_EVALUATED_DUE_PHASE_E_GATE`
- `model_capability_evaluation = NOT_EVALUATED_DUE_PHASE_E_GATE`
- `multi_agent_status = BLOCKED_BY_EFFICIENCY_EXPERIMENT`

## 18. Autonomous Decisions

- Kept Unit staging in memory and committed with rollback: smallest safe design within the existing Project Loop authority; fake rollback tests pass.
- Disabled Worker thinking for bounded generation/repair calls: reduced irrelevant output while preserving the qualified route; live Worker probes passed 2/2.
- Projected only actionable public pytest failures and preferred implementation ownership for mixed failures: avoids traceback leakage and unnecessary Tests Unit repair.
- Reused unchanged downstream committed baselines after localized invalidation: prevented needless Provider regeneration while rerunning deterministic checks.
- Stopped all later benchmarks after Phase E: required by the ordered gate and preserves evidence integrity.

## 19. Critical Decisions Escalated

none

## 20. Remaining Blockers

- P0 — Coordinator route reliability: the same frozen request produced a schema-selection failure and a timeout. Evidence is in the two final-source provider ledgers. Next action: qualify a stable Coordinator route without increasing the one-call or token budget.
- P0 — Fixed-budget project completion: diagnostic runs that reached execution still failed within eight calls. Next action: use the preserved public failure summaries and unchanged-baseline reuse to improve semantic convergence, then restart Source Closure evidence from zero.
- P1 — Live continuation/cost benefit: both final Worker probes returned complete first responses. Next action: after Phase E is green, run the controlled FULL_RETRY vs INCREMENTAL suite.
- P1 — Acceptance attribution: offline tests pass, but live hidden acceptance was not reached. Next action: exercise only through a naturally failing real acceptance run.
- P2 — Formal/model/structure evaluations: gated behind stable generation and repair. Next action: do not run until Phases E-G pass.

## 21. Commits

| SHA | Message | Phase |
|---|---|---|
| `5f909d3` | feat: validate incremental unit materialization | implementation and fake validation |
| `2900611` | fix: validate consumed interfaces for cohesive units | interface validation |
| `dd8c983` | fix: bound worker repair context and thinking | bounded context |
| `4ba4c4c` | fix: audit bounded worker retries in live qualification | live receipt audit |
| `b5a9c99` | fix: project actionable public test failures | safe failure projection |
| `bb6ebbd` | fix: route mixed pytest failures to implementation owners | failure ownership |
| `d7d9ca4` | fix: reuse unchanged downstream unit baselines | final Source Closure |

The Evidence Closure SHA is reported after canonical publication. No force push or PR is used.
