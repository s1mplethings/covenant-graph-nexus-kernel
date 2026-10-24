# PB-027 strong-escalation evidence closure

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Baseline/evidence parent: `c4fabe183c2707cff8381840d957881c9914665e`
- Product source/tree: `a14b309ff5fcc9a27dabd2acff824e8919298884` / `1b7825ab106df56234c790eb1ec23803803d5bf8`
- Branch: `codex/strong-escalation-evidence-closure-20261024`
- Live replacement harness: `04596e3e924ef216af2ab3fa4339814798dec75a`
- Final accounting harness: `40edcbf67bba6faa79f7665ad893d0f3be9e11c0`
- Production `cgkn/**`, contracts, and route configuration are byte-identical to the frozen product source. No force push, PR, or merge was used.

## 2. Frozen Architecture Baseline

The Agent, CapabilityTree, ExecutionDAG, Component/Block, Executor, Project State, Knowledge, Conversation, persistence-v2, ProjectBlueprint, and Provider authorities were frozen. D3 thresholds were not tuned. The formal receipt source `c3de7eff...` is compatible with product source `a14b309f...`: the route config and policy hashes match, the 24-case manifest is complete, and the relevant source paths have no byte difference.

## 3. Previous D0-D3 Evidence

The frozen 24-case suite contains 6 deterministic, 8 cheap-sufficient, 6 strong-required, and 4 human-stop cases. Previous results were D0 22/24, D1 23/24, D2 23/24, and D3 22/24. D3 used 6 strong calls rather than D0's 14, with no false or missed escalation and 100% critical-stop correctness.

## 4. Usage Accounting Audit

The machine receipt contains all transport IDs, request identities, group memberships, billing components, request IDs, and completeness states. Compact token audit:

| case | route | model | result | accepted | input | cached | output | reasoning | total | latency ms | usage |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cheap-1 | cheap | deepseek-flash | PASS | true | 764 | 0 | 79 | 69 | 843 | 950.796 | KNOWN |
| cheap-1 | strong | qwen3.8-max | PASS | true | 590 | 0 | 117 | 106 | 707 | 4934.648 | KNOWN |
| cheap-2 | cheap | deepseek-flash | PASS | true | 464 | 0 | 47 | 38 | 511 | 983.782 | KNOWN |
| cheap-2 | strong | qwen3.8-max | PASS | true | 345 | 0 | 80 | 71 | 425 | 3401.539 | KNOWN |
| cheap-3 | cheap | deepseek-flash | PASS | true | 479 | 0 | 56 | 44 | 535 | 1023.408 | KNOWN |
| cheap-3 | strong | qwen3.8-max | PASS | true | 358 | 0 | 134 | 123 | 492 | 4580.605 | KNOWN |
| cheap-4 | cheap | deepseek-flash | PASS | true | 470 | 0 | 28 | 19 | 498 | 704.145 | KNOWN |
| cheap-4 | strong | qwen3.8-max | PASS | true | 357 | 0 | 124 | 114 | 481 | 5135.490 | KNOWN |
| cheap-5 | cheap | deepseek-flash | PASS | true | 673 | 0 | 86 | 76 | 759 | 899.074 | KNOWN |
| cheap-5 | strong | qwen3.8-max | PASS | true | 519 | 0 | 95 | 85 | 614 | 3670.410 | KNOWN |
| cheap-6 | cheap | deepseek-flash | PASS | true | 488 | 0 | 71 | 57 | 559 | 1000.102 | KNOWN |
| cheap-6 | strong | qwen3.8-max | PASS | true | 354 | 0 | 110 | 99 | 464 | 3533.954 | KNOWN |
| cheap-7 | cheap | deepseek-flash | PASS | true | 484 | 0 | 64 | 50 | 548 | 960.567 | KNOWN |
| cheap-7 | strong | qwen3.8-max | PASS | true | 357 | 0 | 117 | 105 | 474 | 4810.706 | KNOWN |
| cheap-8 | cheap | deepseek-flash | PASS | true | 480 | 0 | 56 | 46 | 536 | 827.888 | KNOWN |
| cheap-8 | strong | qwen3.8-max | PASS | true | 345 | 0 | 105 | 96 | 450 | 3769.363 | KNOWN |
| strong-1 | cheap | deepseek-flash | PASS | true | 512 | 0 | 93 | 81 | 605 | 1201.082 | KNOWN |
| strong-1 | strong | qwen3.8-max | PASS | true | 391 | 0 | 1795 | 1782 | 2186 | 49603.406 | KNOWN |
| strong-2 | cheap | deepseek-flash | PASS | true | 790 | 0 | 50 | 31 | 840 | 883.861 | KNOWN |
| strong-2 | strong | qwen3.8-max | PASS | true | 602 | 0 | 170 | 154 | 772 | 5778.844 | KNOWN |
| strong-3 | cheap | deepseek-flash | PASS | true | 496 | 0 | 60 | 46 | 556 | 1006.436 | KNOWN |
| strong-3 | strong | qwen3.8-max | PASS | true | 374 | 0 | 195 | 182 | 569 | 6662.113 | KNOWN |
| strong-4 | cheap | deepseek-flash | PASS | true | 503 | 0 | 53 | 39 | 556 | 3429.396 | KNOWN |
| strong-4 | strong | qwen3.8-max | PASS | true | 378 | 0 | 120 | 107 | 498 | 4127.747 | KNOWN |
| strong-5 | cheap | deepseek-flash | CALL_FAILED | false | 785 | 0 | 256 | 256 | 1041 | 2224.153 | KNOWN |
| strong-5 | strong | qwen3.8-max | VALIDATOR_REJECTED | false | 597 | 0 | 976 | 962 | 1573 | 25293.461 | KNOWN |
| strong-6 | cheap | deepseek-flash | PASS | true | 667 | 0 | 90 | 80 | 757 | 1826.973 | KNOWN |
| strong-6 | strong | qwen | CALL_FAILED | false | unknown | unknown | unknown | unknown | unknown | 90076.565 | UNKNOWN |

## 5. Missing Usage Root Cause

The `strong-6/Qwen` request timed out after 90.077 seconds before any response headers, provider request ID, or usage metadata reached CGKN. The budget ledger retained the stable request identity, 543-token reservation estimate, 256-output-token limit, and failure state; it did not convert unknown usage to zero.

## 6. Usage Recovery

Raw response/headers, API Lab receipt, local provider log, already-authorized usage endpoint, and provider billing record were checked in order. Recovery was impossible because no response or provider request ID existed and no persistent matching API Lab log was found. The one permitted frozen replacement preserved the same request identity, prompt hash, schema hash, model route, policy, and 256-token output limit, but returned HTTP 502 after 21.943 seconds with no usage. It was not substituted into the semantic view, and no second replacement was attempted.

## 7. Usage Completeness

- Original transports: 27/28 KNOWN = 96.43%.
- D0: 13/14 = 92.86%; strong 13/14 = 92.86%.
- D1: 14/14 = 100%.
- D2: 14/14 = 100%.
- D3: 13/14 = 92.86%; strong 5/6 = 83.33%.

## 8. Pricing Snapshot

The ITER-050 snapshot remains the applicable same-day snapshot: qwen3.8-max CNY 12/M input, 1.5/M cached input, 36/M output; deepseek-flash USD 0.15/M input, 0.003/M cached input, 0.6/M output; USD/CNY 6.72. Reasoning tokens are included in output billing and are not double counted. Historical costs were not rewritten.

## 9. Formal Benchmark Design

The analysis reuses the frozen full 24-case paired benchmark. Only the one transport-infrastructure failure was eligible for one replacement. The semantic benchmark retains the original failed result because replacement usage remained incomplete. Operational evidence counts both failures. Same tasks, public evidence, validators, registry, route config, policy hashes, and answer budget were preserved.

## 10. Provider Reliability

Original execution had 2 `CALL_FAILED` rows and 1 semantic validator rejection across 28 live calls. The replacement added one provider failure (HTTP 502). The original timeout contributes 90.077 seconds to D0/D3 latency; the replacement contributes 21.943 seconds only to operational reliability, not semantic projections.

## 11. D0 Strong-All

22/24 accepted; 14 strong calls; 8 false escalations; 0 missed escalations; 100% critical stop. Known lower bounds are 5,567 strong input, 4,138 strong output, 3,986 reasoning, and 9,705 strong total tokens. Cost lower bound is CNY 0.215772. Usage is incomplete.

## 12. D1 Cheap-All

23/24 accepted; 14 cheap calls; 9,144 total tokens; CNY 0.012510288 total and CNY 0.000543926 per success. It has 6 missed escalations, so low cost does not satisfy critical model-capability localization even though the fixture answers happened to pass 5 of those 6 cases.

## 13. D2 Fixed Strong→Cheap

23/24 accepted; 8 strong and 6 cheap calls; 3,395 strong input and 6,130 strong total tokens; 10,330 total tokens; CNY 0.145317552 total and CNY 0.006318154 per success. It has 4 false and 2 missed escalations, 50% strong-call precision, and 66.67% strong escalation recall.

## 14. D3 Adaptive

22/24 accepted; 6 strong and 8 cheap calls; 0 false and 0 missed escalation; 100% critical stop; 100% strong-call precision and recall. Known lower bounds are 2,342 strong input, 5,598 strong total, 10,387 total model tokens, and CNY 0.151620 total cost. The exact denominator is unavailable.

## 15. Strong Call Precision

D0 = 42.86%, D2 = 50%, D3 = 100%. D3 sends strong work only to the six expected strong-required cases; there were no validator-driven strong escalations in this frozen run.

## 16. Strong Escalation Recall

D0 = 100%, D1 = 0%, D2 = 66.67%, D3 = 100%. D3 did not obtain its lower strong share by skipping expected strong-required decisions.

## 17. Strong Decision Share

D3 uses strong on 6/24 decisions = 25% of all decisions and 6/14 = 42.86% of model calls. D0 uses strong on 14/24 = 58.33% of all decisions and every model call.

## 18. Strong Tokens / Success

Exact D0 and D3 values remain unavailable. At the impossible-to-observe zero-usage lower boundary, D3's best strong-input reduction is 57.93%, but it falls below 50% if the missing input exceeds 883 tokens. D3's best strong-total reduction is only 42.32%; meeting 50% would require the unknown call to have negative 1,491 tokens. Therefore the declared strong-total gate fails for every valid non-negative usage value.

## 19. Total Tokens / Success

The same unknown call is present in D0 and D3 and both have 22 successes. It cancels in ordering. D3 has 10,387 known tokens versus D0's 9,705, so D3 uses at least 31 more total model tokens per success. Cheap-token substitution more than offsets the saved strong-call count on this workload.

## 20. Cost / Success

Exact percentages remain unavailable, but the shared unknown call also cancels in D3-vs-D0 absolute ordering. D3's known cost is CNY 0.064152 lower in total, or CNY 0.002916 lower per success. Against D2, D3's lower-bound cost/success is CNY 0.006891818, already above D2's exact CNY 0.006318154; D3 cannot become cheaper by adding a non-negative unknown cost.

## 21. Latency

| Group | total ms | strong ms | cheap ms | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|
| D0 | 215378.851 | 215378.851 | 0 | 4872.677 | 90076.565 |
| D1 | 17921.663 | 0 | 17921.663 | 991.942 | 3429.396 |
| D2 | 91963.149 | 84224.392 | 7738.757 | 3764.643 | 49603.406 |
| D3 | 188891.898 | 181542.136 | 7349.762 | 1011.755 | 90076.565 |

## 22. False Escalation

D0 = 8, D1 = 0, D2 = 4, D3 = 0. D3 removes unnecessary strong routing on the frozen labels.

## 23. Missed Escalation

D0 = 0, D1 = 6, D2 = 2, D3 = 0. D3 restores full strong-required routing coverage relative to D1 and D2.

## 24. Critical Stop

All four strategies retain 4/4 critical stops and zero critical misses. Scope/security violations remain zero.

## 25. D3 vs D0

Reliability is equal (22/24), strong calls fall 57.14%, precision rises from 42.86% to 100%, and cost/success is directionally lower. However, strong-total reduction can never reach 50%, total model tokens/success are higher, usage is incomplete, and latency still contains the same 90-second strong failure.

## 26. D3 vs D1

D3 removes all six missed escalations but accepts one fewer case (a 4.17-point gap), costs at least CNY 0.006891818/success versus CNY 0.000543926, and is much slower. D1 is not an acceptable safety substitute despite its cost advantage.

## 27. D3 vs D2

D3 reduces strong calls 25% and improves precision/recall, but accepts 22/24 versus 23/24 and its cost lower bound per success already exceeds D2's exact result. On the frozen workload, adaptive routing does not justify its additional policy complexity over fixed routing.

## 28. Strong Key Decision Hypothesis

The localization mechanism is directionally supported: D3 uses strong only for labeled strong-required work, with 100% precision/recall and D0-level reliability. The economic form of the hypothesis is not qualified because strong-total reduction is capped below 50%, total tokens rise, and failure telemetry remains incomplete.

## 29. Strong Escalation Benefit

`DIRECTIONAL`. The route selection quality is strong and cost ordering beats D0, but the declared strong-token gate fails.

## 30. Adaptive Decision Hierarchy Benefit

`NEUTRAL`. D3 is safer than cheap-all and more targeted than strong-all, but it does not beat D2 on frozen success/cost and does not reduce total model tokens.

## 31. Router Complexity Cost

The non-default router currently adds 145 nonblank/noncomment production LOC, 11 policy-rule surfaces, 32 focused test cases, up to two model hops after validator escalation, and four maintenance surfaces: risk assessment, initial routing, validator escalation, and formal projection.

## 32. Break-even Analysis

Holding the frozen within-class phase mix constant, D3 becomes cheaper than D2 only when strong-required cases are below 26.62% of model-routed work. The frozen share is 42.86%, above break-even, so D2 is cheaper. This is directional workload evidence, not a production traffic estimate.

## 33. Should Adaptive Routing Become Default?

`NOT_YET`. Retain the capability as non-default and prefer the simpler fixed policy for the evaluated workload.

## 34. Should Strong Role Separation Be Collapsed?

`NOT_YET`. The evidence does not authorize a structural role change.

## 35. Full Regression / Freshness

Targeted formal and PB-027 suites pass 12/12. Compileall, product-direction, kernel-architecture, and test-architecture checks pass. Kernel receipt freshness passes for product source `a14b309f...`. Full production regression was not rerun because only experiment harness/tests and evidence changed; production source remained byte-identical.

## 36. Security

No credentials, raw provider text, hidden source, hidden assertions, or hidden tracebacks were stored. Scope/security violations are zero. API Lab stayed on frozen commit `7c15f254...`; selector authority remained CGKN; fallback remained deny.

## 37. Architecture Implication

Keep the DecisionRouter evaluation-only/non-default. Keep fixed strong/cheap role separation. Do not add another authority, planner, runtime, DAG, state store, or threshold special case.

## 38. Recommended Next Phase

Return focus to product capability work. Revisit adaptive defaulting only with naturally collected production workload composition and provider-side failure billing telemetry; do not spend more benchmark calls on the already-failed 50% strong-total gate.

## 39. Autonomous Decisions

- Built an evidence-only harness because the historical receipt could not express KNOWN/PARTIAL/UNKNOWN completeness, shared-unknown cancellation, or break-even.
- Used one and only one provider-failure replacement because it was explicitly permitted and could have answered input/cost questions.
- Stopped provider calls after the replacement 502 and used sensitivity analysis, preserving the original operational failure.
- Did not tune D3 because the issue was evidence/economics, not a deterministic routing bug.

## 40. Critical Decisions

None. No product direction, authority, security boundary, model, budget, acceptance, or role structure was changed.

## 41. Remaining P0/P1/P2

- P0: none.
- P1: none; the prior uncertainty is closed with a negative qualification decision.
- P2: provider failure telemetry cannot supply usage without a response/request ID; exact D0/D3 percentages remain unavailable.
- P2: the 24-case workload composition is not production traffic and should not be generalized beyond its frozen mix.

## 42. Commits

- `5a051d38` — `test: close strong escalation evidence accounting` — initial harness, CLI, and tests.
- `04596e3e` — `fix: bind PB-027 to frozen routing semantics` — cross-source compatibility and live replacement harness.
- `be87fc16` — `fix: report robust unknown-usage sensitivity` — configured ceiling and shared-unknown cost ordering.
- `40edcbf6` — `fix: compare adaptive cost against fixed routing` — D2 comparison and break-even interpretation.
- Evidence closure — this evidence-only commit; canonical publication receipt supplies the final SHA.

Machine evidence: `D:/CGKN/.service_evidence/strong-escalation-evidence-051/strong-escalation-closure-final.json`, SHA-256 `c7620a9dd4df48699eff88cedf14811926769e62e686c16c55821a7430b46008`, receipt hash `sha256:59a3d4e9bd9fa4d9f7b75ad7fdedd410f61951a1fe1845c9c84491b43de3cc4c`.
