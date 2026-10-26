# ITER-CGNK-FROZEN-MVP-EFFICIENCY-MODEL-EVAL-042

## 1. Git Identity

Branch `codex/frozen-mvp-efficiency-model-eval-20261022`; normal canonical publication only, no force push and no PR.

## 2. Frozen Source

Product source `dc640cd9426616663a613f540a6d4e1e5a7898e7`, tree `66056cf6432227681a117b1f5df9c3e6999475cd`. Experiment helpers do not alter production semantics.

## 3. Fresh CSV Single

`blueprint-cli_csv_cleaner-da1958e552` passed compile, pytest, runtime, public and hidden acceptance with 6/8 calls and zero manual edits.

## 4. New Seeded Repair

`SEED-CSV-PREVIEW-POSITIVE-CONDITION-001` passed with one DeepSeek PatchBundle call, the same Frozen Blueprint, 3,382 input tokens, 197 output tokens, and zero manual edits.

## 5. CSV 3/3

Runs `da1958e552`, `b1bdfe3263`, and `d0f269ad28` all passed independently with 6/8 logical calls.

## 6. Budget Convergence

`PASS_STABLE_WITH_TWO_CALL_SPARE`; median and maximum calls were both 6.

## 7. MVP Readiness

`minimal_blueprint_status=COMPLETE`, `real_generation=PASS`, `real_repair=PASS`, `csv_repeatability=PASS_3_OF_3`, and `efficiency_experiment_ready=true`.

## 8. M0 vs M1

M0 Full Retry passed 3/3 with 11,130 generation tokens and 4,181 duplicate-waste tokens. M1 Incremental passed 3/3 with 14,203 generation tokens and zero duplicate-waste tokens.

## 9. Incremental Benefit

`NEUTRAL`: duplicate output was eliminated, but generation tokens per success increased 27.61%, so the required 20% reduction was not met.

## 10. Pricing

Captured 2026-10-22T11:29:34Z from official Qwen, DeepSeek, and CFETS sources. Qwen prices are CNY 12/1.5/36 per million input/cached/output tokens. DeepSeek off-peak prices are USD 0.15/0.003/0.6.

## 11. V0/V0B/V1/V2

V0: 3/5 overall, CSV 0/2, repair 3/3, 35,646 tokens, CNY 0.749688. V0B: 3/5, 54,367 tokens, CNY 0.769836. V1: 3/5, 66,441 tokens, CNY 0.934092. V2: 6/6, 103,093 tokens, CNY 0.178007.

## 12. Blueprint Benefit

`HARMFUL_DIRECTIONALLY`: V0B did not improve success over V0 and used more tokens/cost.

## 13. Role Separation Benefit

`HARMFUL_DIRECTIONALLY`: V1 did not improve success over V0B and used more tokens/cost.

## 14. Cheap Executor Benefit

`QUALIFIED`: V2 passed generation and repair 3/3 each and sharply reduced strong-model usage and cost per success. Small-sample statistical significance is not claimed.

## 15. Formal Server Evaluation

Boot, health/readiness, registry, spec, guard, valid/invalid invocation, unsupported/malformed requests, real timeout, Provider unavailable/recovery, provenance, evidence fallback, refusal, restart, and security checks passed. Overall status is `FAIL_MISSING_CONVERSATION` because the installed server exposes no Conversation answer path.

## 16. Model Benchmark Design

Frozen at `e04f260c3ed4381dfeb3729c6c0790f413de7be4`: 28 cases, 84 formal R0/R1/R2 calls per provider plus two summary-only diagnostics. Taskset `sha256:a249482175d0355ac336f446c7fe5f8ec2b2d76738ba04bceae0e1245040bc9a`.

## 17. Qwen Capability

Overall success 55.95%, grounded 85.71%, safe 86.90%. R2: generation 1/3, repair 1/3, reasoning 6/6, grounding 7/7, abstention 5/7.

## 18. DeepSeek Capability

Overall success 60.71%, grounded 90.48%, safe 92.86%. R2: generation 3/3, repair 1/3, reasoning 5/6, grounding 7/7, abstention 3/7.

## 19. R0

Raw-model success: Qwen 28.57%; DeepSeek 35.71%.

## 20. R1

Flat-complete-evidence success: Qwen 64.29%; DeepSeek 75.00%.

## 21. R2

CGKN-structured-evidence success: Qwen 75.00%; DeepSeek 71.43%.

## 22. Evidence Fidelity

Across 12 structured evidence runs per provider, Qwen R1/R2 were 12/12 and DeepSeek improved from 11/12 to 12/12. Summary-only was 0/2 for each provider.

## 23. Evidence Information Loss

Summary-only critical information loss was 100% on the two diagnostic cases: exact CRLF identity and event ordering were not preserved.

## 24. Bottom-up Retrieval

R2 selected the relevant leaf/ancestor path rather than the complete corpus; structured evidence irrelevant-context ratio was 0.2083 versus 0.7912 for R1.

## 25. Hierarchical Reasoning

R2 preserved reversible access to raw evidence while using higher-level summaries as indexes rather than replacements.

## 26. Cross-domain Isolation

Domain-isolation cases were executed in the frozen taskset; the structured route constrained selection to the relevant branch with no recorded unsupported claims.

## 27. Update Propagation

The frozen update-propagation case verified affected-branch change with unrelated-branch stability under the deterministic rubric.

## 28. Contradiction Localization

The frozen contradiction cases required explicit localization rather than silently selecting one incompatible fact; containment was scored separately from model correctness.

## 29. CGKN Structure Benefit

`PROVEN_DIRECTIONALLY`: structured evidence retained comparable accuracy, cut tokens per successful evidence case about 35%, and reduced irrelevant context about 73.67%. No statistical-significance claim is made.

## 30. System Containment

Schema validity and scope compliance were 100%; unsupported claim rate was zero in both model batches. Deterministic guards remained separate from model success.

## 31. Security

No hidden source, hidden assertion, hidden traceback, credential, scope violation, or manual candidate edit was recorded.

## 32. Full Regression

Compile and all architecture/completeness/freshness gates passed. Application: 447 passed, 1 skipped. Fast profiles all passed. Active repository and explicit canonical-Python pytest: 2,646 passed, 351 skipped, 0 failed, 0 errors, 26 subtests passed. Collection: 2,997.

## 33. Reliability

The frozen MVP is reliable for the evaluated CSV workload: 3/3 generation plus a distinct seeded repair within budget.

## 34. Efficiency

Cheap execution is the only clearly positive Tier-1 economic result. Incremental materialization was neutral; Blueprint-only and strong role separation were harmful directionally.

## 35. Capability

Structured evidence organization has directional value for evidence-heavy tasks, but general generation, repair, and abstention remain mixed by model.

## 36. Final Readiness

MVP and model evaluation are complete; formal server evaluation is not complete because Conversation is absent.

## 37. Multi-Agent Decision

Do not enter Multi-Agent. The mandatory formal-server PASS gate is not met despite qualified cheap execution and directional CGKN structure benefit.

## 38. Autonomous Decisions

Invalid benchmark batches were retained and excluded rather than overwritten; schema uniqueness moved to deterministic local validation when the provider rejected it; the model prompt separated task-stated facts from external evidence; canonical Python 3.13 was used after detecting Conda Python 3.12 AST variance.

## 39. Critical Decisions

None escalated. No product direction, Kernel authority, acceptance boundary, Provider budget, or model tier was changed.

## 40. Remaining Blockers

P0: formal server Conversation capability absent. P1: model generation/repair/abstention capability remains mixed. P2: benchmark sample sizes are directional only.

## 41. Commits

Product `dc640cd`; materialization harness `0981a29` through `1fa89c1`; Tier-1 harness `bb65c0d` through `8b0ca93`; formal server `52c8792`; model evaluation `8d47f4e`, `f2c97ac`, `e04f260`; final evidence closure is the canonical publication commit following this summary.
