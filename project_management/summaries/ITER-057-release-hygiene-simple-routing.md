# ITER-057 — CGNK Release Hygiene and Simple Architecture Admission Routing

## 1. Executive Summary

CGNK release hygiene is complete on Source Closure
`7b81a3dde5823dd9ccc31839441bffc6b6acfe98`. The public name is CGNK, the
`cgkn` Python namespace remains compatible, scope-bound current/history audits
have zero P0 findings, and all required regression profiles pass. The routing
oracle equals Always Direct Cheap at 58/72 and contains zero CGNK-only
successes. Router V1 was therefore not implemented.

## 2. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Base evidence: `f9a0f4197d73e8e82654c78268988cb5b8d13a7f`
- Branch: `codex/cgnk-simple-routing-20261026`
- Source Closure: `7b81a3dde5823dd9ccc31839441bffc6b6acfe98`
- Source tree: `5c08929a2ba660aea7bd53bbfe5c286307015cb2`
- `main` migration: release tree is identical to Evidence Closure `8ef106c5…`
  and prepared as a normal fast-forward commit from `3df1110d…`; remote and
  default-branch verification are recorded by the final main evidence commit.
- Force push: no. PR: none.

## 3. Public Release Hygiene

Version metadata is `0.2.0-rc.3`; Apache-2.0, attribution, security, benchmark
redistribution, and Postiz service-boundary policies remain unchanged. The
`v0.2.0-rc.2` tag and benchmark claims were not moved or rewritten.

## 4. CGNK Naming Audit

Strict public surfaces use “Covenant Graph Nexus Kernel (CGNK)”. The
deterministic naming gate passes with zero findings. Frozen `CGKN...` values are
retained only as legacy machine identifiers or historical paths.

## 5. Legacy `cgkn` Compatibility

The import/package namespace, plugin/package IDs, repository paths, environment
variables, and serialized machine identifiers remain compatible. No destructive
`cgkn` to `cgnk` module rename occurred.

## 6. History Audit Scope

History audit at Source Closure `7b81a3dde5823dd9ccc31839441bffc6b6acfe98`
scanned 7,605 unique named text blobs of at most 8 MiB reachable from that
commit. Status: PASS; P0: 0; result hash:
`sha256:8d8d719f2d92c47cb42ad2c0892e7702031b59f43b538128ea5384934f8cb597`.

## 7. Blob Count Reconciliation

The 7,726 scan at `2ad4c650…` and 7,744 scan at `f9a0f419…` used the old
`git rev-list --objects --all` policy, whose input changes with visible local and
remote refs. Both were valid for their different scan-time ref sets. ITER-057
replaces that ambiguous scope with one explicit commit and reports the exact
policy and hash.

## 8. Default Branch Migration

The release tree is prepared on the exact remote `main` baseline and will be
published as a normal fast-forward commit. The old release branch remains
preserved. GitHub default-branch verification is recorded after canonical
publication; no force push or remote history rewrite is used.

## 9. Previous ITER-056 Results

- B0 Direct Cheap: 58/72 (80.56%).
- B4 Optimized CGNK: 48/72 (66.67%).
- Flat Context: 15/72 (20.83%).

These observed outcomes are diagnostic/development evidence for this iteration.

## 10. Router Research Question

Should every task enter an agent architecture? The tested CGNK hypothesis is
“no”: architecture should be admitted only when it provides a measurable
quality, governance, state, evidence, or repair benefit.

## 11. Oracle Feasibility

The paired oracle produced 58/72 successes, identical to Always Direct Cheap.
Oracle gain is 0.00 percentage points, below the 3pp stop threshold.

## 12. Direct-vs-CGNK Complementarity

Pair classes were BOTH_PASS=48, DIRECT_ONLY=10, CGNK_ONLY=0, BOTH_FAIL=14.
There are no complementary cases in which CGNK succeeds while Direct fails, so
no failure taxonomy can support Router admission rules.

## 13. Router Design

Not implemented. The oracle-first anti-overengineering gate stopped Router V1
before production code, route receipts, or runtime integration were created.

## 14. Router Features

Not evaluated. No task-kind, knowledge, provenance, state, capability, repair,
risk, or context-size rules were fitted to observed task IDs.

## 15. Hard Gates

Existing governance and strong/human escalation remain unchanged. No new
admission hard gate was added because no Router was admitted.

## 16. Development Results

The deterministic oracle analyzer reproduced the 72 paired outcomes and the
stop decision. Its result hash is
`sha256:4f0188e737d6457c69039a37fff2d0abd3f9cb6aedf4591856a33a5df3a816e2`.

## 17. Fresh Holdout Design

Not run. The protocol required a fresh 30-task holdout only after the oracle
showed sufficient opportunity. Running it after a zero-gain oracle would spend
resources without a viable hypothesis.

## 18. Always Direct

Observed development result: 58/72, 80.56%. This remains visible and is not
reframed as inferior to Full CGNK.

## 19. Always CGNK

Observed B4 result: 48/72, 66.67%. It did not add a success absent from Direct.

## 20. Simple Router

Status: NOT_IMPLEMENTED_BY_STOP_GATE. No formal success claim is made.

## 21. Oracle

Observed upper bound on the paired data: 58/72, exactly Always Direct.

## 22. Route Distribution

Not evaluated because no Router or fresh holdout was authorized.

## 23. Success

Router success is NOT_EVALUATED. Release hygiene and regression gates pass.

## 24. Cost / Tokens / Latency

Router cost, tokens, and latency are NOT_EVALUATED. The deterministic oracle
uses zero Provider calls; this is analysis cost, not production routing cost.

## 25. Fallback

No Router fallback chain was introduced. Existing execution validation and
strong/human escalation policies remain unchanged.

## 26. Failure Analysis

The 10 DIRECT_ONLY cases show architecture regressions; 14 BOTH_FAIL cases show
no recoverable complementarity in the compared routes. With zero CGNK_ONLY
cases, architecture admission cannot improve success on this sample.

## 27. Router Ablation

Not applicable. No rules were implemented, so there is no ablation to report.

## 28. Knowledge Cycle Audit

`store`, `persistence`, and `internalization` remain a conceptual strongly
connected component mediated partly by local imports. Safe removal requires a
broader migration/recovery revalidation, so status is `P1_FUTURE_NO_CHANGE`.

## 29. Security

Current-tree and Source-Closure history audits report zero P0 findings. Postiz
remains an independent AGPL service boundary; no implementation was imported.
No Provider call, secret exposure, external write, force push, or approval
bypass occurred.

## 30. Full Regression

All profiles PASS: static, unit (482/1 skip), boundary (325/1 skip), fault
(80), security (119/1 skip), local-functional (6), full-core (482/1 skip), and
active-repository (3,007/363 skips). Collection found 3,370 tests. The separate
Knowledge/Conversation/Capability/Routing/Self-Growth/Promotion/Community/
Persona set passed 420 with 6 skips. Failed=0; errors=0.

## 31. Claim Ledger

`ROUTER_ORACLE_OPPORTUNITY=REFUTED/LOW`; `ROUTER_FORMAL_SUCCESS`,
`ROUTER_COST`, and `ROUTER_OVERHEAD=NOT_EVALUATED`;
`ROUTER_ADOPTION_STATUS=NOT_ADOPTED`.

## 32. Release Decision

Publish hygiene-only `v0.2.0-rc.3`. Do not publish `v0.3.0-rc.1`, because no
new execution admission behavior was adopted.

## 33. GitHub Release

Prepared as an rc.3 Research Preview prerelease. The final URL and verified tag
SHA are recorded after GitHub publication.

## 34. Remaining P0/P1/P2

- P0: none.
- P1: Knowledge/persistence/internalization SCC; public benchmark environments
  remain environment-blocked; historical privacy-pattern findings remain
  documented as non-P0.
- P2: optional note on the rc.2 GitHub description and later legacy release
  branch cleanup.

## 35. Commits

- `16b7d710…` — `chore: normalize CGNK release hygiene and audit scope`.
- `7b81a3dd…` — `fix: preserve experiment receipt boundary in release analysis`.
- Evidence and main migration commits are appended after canonical publication.

## 36. Final Verdict

- `release_hygiene_status=PASS`
- `canonical_name_status=PASS_CGNK`
- `history_audit_status=PASS_SCOPE_BOUND`
- `default_branch_status=PREPARED`
- `router_oracle_opportunity=LOW`
- `router_status=INSUFFICIENT_EVIDENCE`
- `router_overhead_status=NOT_EVALUATED`
- `router_generalization_status=NOT_EVALUATED_STOP_GATE`
- `router_production_adoption=NOT_ADOPTED`
- `knowledge_cycle_status=P1_FUTURE_NO_CHANGE`
- `release_status=READY_FOR_MAIN_MIGRATION`
