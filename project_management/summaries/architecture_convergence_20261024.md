# ITER-CGNK-PARALLEL-ARCHITECTURE-CONVERGENCE-050

## 1. Git Identity

- Baseline: `codex/v2-resource-gate-scale-qualification-20261024` at `7fafb7471ebfda9a931fc1b8fb8fb3e40185a1e4`.
- Integration branch: `codex/architecture-convergence-integration-20261024`.
- Integrated and A2 source closure: `a14b309ff5fcc9a27dabd2acff824e8919298884`, tree `1b7825ab106df56234c790eb1ec23803803d5bf8`.
- Publication uses only `scripts/canonical_repo_publish.py`; no force push, merge, or PR.

## 2. Previous Validated Baseline

The previous closure had completed Kernel, generation/repair, Conversation, local-lazy knowledge, and production segmented-v2 persistence. Blueprint and incremental materialization were useful but not efficiency-proven; fixed strong role separation was harmful directionally; Multi-Agent Runtime was not recommended.

## 3. Parallel Workstream Plan

A owned semantics-preserving diet, B owned derived capability search and L0-L3 routing, and C owned checkpoint build/load. Independent worktrees and branches prevented simultaneous edits to the same production subsystem.

## 4. Workstream A Audit

The inventory covered 222 production modules, public symbols, dependency edges, runtime/test use, and dynamic-registration risk. Forty-five uncertain modules were retained because static non-reference alone is insufficient deletion evidence.

## 5. Safe Slimming Results

A removed 21 unused imports/bindings and consolidated two duplicate helpers. No public symbol, schema, registry, CLI, knowledge-format, or conversation-contract change occurred.

## 6. Complexity Before / After

Production LOC moved 76,461 → 76,438 (-23). Modules stayed 222, public classes/functions stayed 416/829, schema dataclasses stayed 200, and maximum import depth stayed 9. This is a safe but deliberately small reduction, not a claim of broad architectural collapse.

## 7. Workstream B Capability Audit

The registry remains the sole capability authority. Search records are deterministic projections of existing specs; indexes are derived and rebuildable.

## 8. Capability Search Design

Eligibility filtering rejects incompatible effects, scope, version, state, and qualification before ranked retrieval. Models receive bounded top-k candidates rather than the whole registry.

## 9. Capability Search Scaling

The real 10-capability registry achieved Top1/Top3 = 100% but is too small for a material-product benefit claim. Synthetic 100/500/1000 fixtures held Top1/Top3 = 100% and reduced context by 97.9442%, 99.5902%, and 99.7953%. Conclusion: `NOT_YET_NEEDED_AT_CURRENT_SCALE`; scaling direction only is proven.

## 10. Decision Hierarchy

The evaluated levels were deterministic, cheap model, strong model, and human stop. The router is a policy component above existing capabilities, not an Agent, planner, DAG, or state authority.

## 11. Decision Risk

Risk uses uncertainty, impact, reversibility, evidence sufficiency, authority scope, qualification, and validator availability. Known exact cases remain deterministic.

## 12. Escalation

Escalation stayed bounded and auditable. Twenty-eight transports produced 25 accepted decisions, one validator-contained wrong decision, one truncated strong response, and one strong timeout; no schema failure or safety-scope violation occurred.

## 13. D0 Strong-All

22/24 accepted; 14 strong calls; eight false escalations; zero missed escalations; critical-stop correctness 100%.

## 14. D1 Cheap-All

23/24 accepted; 14 cheap calls; 9,144 tokens; CNY 0.012510288; zero false escalations and six missed escalations.

## 15. D2 Fixed Strong→Cheap

23/24 accepted; eight strong and six cheap calls; 10,330 tokens; CNY 0.145317552; four false and two missed escalations.

## 16. D3 Adaptive Hierarchy

22/24 accepted, matching D0 reliability. Decision shares were 25% deterministic, 33.33% cheap, 25% strong, and 16.67% human stop. It made six strong and eight cheap calls with zero false/missed escalations and 100% critical-stop correctness.

## 17. D0/D1/D2/D3 Comparison

D3 reduced strong calls 57.14% versus D0 but did not reduce total known tokens and lacks complete strong-token/cost denominators because one strong route timed out without usage. D3 also trailed D2 by one accepted case. Exact paired evidence shows some cost reduction, but the formal relative-cost gate remains unavailable.

## 18. Strong Key Decision Hypothesis

Only 25% of all D3 decisions were strong, but 42.86% of model calls were strong and the exact strong-token share is unknown (lower bound 53.89%). The required >=50% strong-token-per-success reduction cannot be established from this call mix. Hypothesis: partially directional, not qualified.

## 19. Capability Retrieval Benefit

`NOT_YET_NEEDED_AT_CURRENT_SCALE`; `PROVEN_FOR_SYNTHETIC_SCALING_ONLY`.

## 20. Adaptive Decision Hierarchy Benefit

Deterministic routing is proven for the formal suite and cheap execution is directionally useful on router-selected low-risk cases. Strong escalation benefit is not proven, so adaptive routing is not adopted as a default.

## 21. Workstream C Checkpoint Forensics

Cold start was dominated by monolithic deserialize/materialization and avoidable copying, while authoritative replay remained correct but slower.

## 22. Checkpoint Optimization

The v2.1 derived checkpoint split and copy-eliding load/replay preserve authoritative segmented records, corruption fallback, v1 read/explicit-write compatibility, and exact semantic equivalence.

## 23. 250k Cold Start Old vs New

At 250k: checkpoint load 8.064s versus unchanged S0 37.430s (78.457% faster); full replay 20.257s; corruption fallback 20.125s; recall 100%; first retrieval 0.113ms; first conversation 1.280s; query P95 79.023ms.

## 24. Checkpoint Build Old vs New

Checkpoint build is 31.469s versus the prior v2 151.342s, a 79.207% improvement. Peak RSS is 1.480GB and storage amplification 2.365x.

## 25. V2 Adoption Gate

PASS. New packs default to v2. Existing v1 packs remain readable and are not auto-migrated; explicit v1 write remains supported.

## 26. Integration

A, B, and C were semantically integrated without adding a second capability, knowledge, runtime, DAG, state, or delivery authority. C production files remained byte-identical, so its 250k scale evidence remains source-valid.

## 27. Integration Conflicts

No production-authority conflict remained. Shared governance and project-management files were merged semantically. No user content was reset or overwritten.

## 28. Integrated Regression

All source-bound gates pass. Active repository: 2,828 passed, 357 skipped, 0 failed/errors. Collection: 3,185. Application: 645 passed, 39 skipped. Experiments: 32 passed. Coverage: 90.77% statements and 77.12% branches. `live-provider` is explicitly `BLOCKED_ENVIRONMENT` with one skipped selected case; the iteration's formal provider run is separately complete with disclosed failures.

## 29. Blueprint Simplification

A2 implemented an evaluation-only minimal representation and deterministic rehydration. Production Blueprint semantics were not changed.

## 30. Blueprint AB

CSV serialization fell 4,031 → 1,355 bytes (-66.39%); repair fell 3,274 → 856 (-73.85%). Blueprint/tree/DAG behavior, scope, security, and repair continuity were exactly equivalent offline. Calls stayed 3/3 and prompt characters stayed 31,788/31,788 for CSV and 14,276/14,276 for repair. Runtime benefit is not proven; B1 is not adopted.

## 31. Strong Role Separation Collapse Analysis

D3 did not meet the strong-token gate and did not beat D2 reliability. The fixed boundary therefore remains; `COLLAPSED_DECISION_PATH` is not implemented.

## 32. Final Complexity

The production reduction is small and evidence-safe. Evaluation logic remains outside production paths. No new production module was added for A2; routing adds a derived service without new authority.

## 33. Final Runtime Architecture

The target remains User Goal → Decision/knowledge/capability retrieval → bounded risk/sufficiency routing → existing Capability Runtime → validation → output or guarded state change. It is not a planner/coordinator/supervisor/worker Agent chain.

## 34. Reliability

Kernel, application, experiment, source-bound receipt, project generation, repair, persistence, and checkpoint gates pass. D3 reliability matched D0 but did not exceed D2.

## 35. Efficiency

Checkpoint efficiency is proven. Capability-search scaling is directionally proven only synthetically. Blueprint runtime efficiency and adaptive strong-token efficiency are not proven.

## 36. Capability

Real capability lookup and invalid-capability rejection pass. Derived search may be retained for growth without claiming current-scale savings.

## 37. Cost

Cheap low-risk calls showed materially lower observed cost than strong calls, but one strong timeout left D0/D3 total cost incomplete. No unknown usage is recorded as zero; relative adaptive cost qualification is withheld.

## 38. Security

Hidden source/assertions/tracebacks exposed: false. Secrets persisted: false. Scope violations, authority duplication, and manual candidate edits: zero. Raw evidence and provenance remain retained.

## 39. Final Readiness

Kernel foundation COMPLETE; current minimal Blueprint COMPLETE and retained; checkpoint gate closed; v2 default adoption PASS; integration PASS_WITH_LIMITS; adaptive hierarchy evaluated but not adopted; Multi-Agent Runtime not recommended.

## 40. Architecture KEEP / SIMPLIFY / COLLAPSE / REMOVE / DEFER

- KEEP: kernel authorities, structured evidence, Conversation, CapabilityRegistry, local-lazy knowledge, current Blueprint, segmented-v2, cheap executor.
- KEEP_FOR_RELIABILITY: incremental materialization, interface guards, provenance, v1 compatibility, human stop.
- SIMPLIFY: Blueprint only after runtime savings; provider usage completeness.
- COLLAPSE: none.
- REMOVE: 21 unused imports/bindings and two duplicate helpers.
- DEFER: role-pipeline collapse, Multi-Agent Runtime, large search infrastructure, retrieval P2.

## 41. Multi-Agent Decision

`NOT_RECOMMENDED_CURRENT_EVIDENCE`. Parallel engineering worktrees were useful; that is not evidence for a product Multi-Agent Runtime.

## 42. Recommended Next Phase

Run a bounded PB-027 strong-escalation evidence closure: require complete usage/pricing, tune only existing deterministic thresholds, and prove strong-token reduction before any default routing or structural collapse.

## 43. Autonomous Decisions

- Retained uncertain modules where dynamic registration/compatibility prevented proof of deadness.
- Kept capability search derived and rebuildable.
- Repaired formal usage propagation and truncation classification before accepting evidence.
- Withheld D3 qualification and Blueprint adoption when their explicit efficiency gates failed.

## 44. Critical Decisions

None. No critical boundary was crossed.

## 45. Remaining P0/P1/P2

- P0: none.
- P1: strong-escalation token/cost benefit not proven.
- P2: Blueprint runtime benefit not proven; real registry too small for material search savings; ambiguous retrieval scaling remains deferred.

## 46. Commits

- `6692ebba` — safe architecture diet.
- `a2f8f8aa` — capability search and decision routing workstream source.
- `859919f3` / `34f1b1f9` — checkpoint optimization and v2 adoption.
- `e02c0472` — integrate convergence foundations.
- `c3de7eff` — tighten formal decision evidence.
- `a14b309f` — evaluate minimal Blueprint representation.
- Final evidence closure is the subsequent canonical publication commit.

The machine-readable cross-workstream closure is `project_management/current/architecture_convergence_report.json`.
