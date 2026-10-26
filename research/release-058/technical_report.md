# ITER-058 — CGNK Necessity Boundary and Knowledge Boundary Decomposition

## 1. Executive Summary

On a frozen 18-chain, 90-episode-per-baseline internal holdout, Direct Cheap
(B0) and current CGNK (B2) both passed 18/18 chains. Full CGNK therefore did not
create an architecture-only success against the fairest direct baseline. It
did reduce deterministic rework from 195 to 159, concentrated in state,
supersession, and mixed long-horizon families, while adding 7.2% context and
0.9% estimated Provider cost. The full-architecture benefit is not proven.
Separately, the Knowledge conceptual SCC was safely reduced from one to zero
without changing authority, schemas, public signatures, or recovery behavior.

## 2. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Canonical branch: `main`
- Development branch: `codex/cgnk-necessity-boundary-20261026`
- Base Evidence Closure: `1f41defd7e15cc82d29dcfd6d1b72e7f689db4e3`
- ITER-058 Source Closure: `a2c7720fb176ba8aa913016dd166e98221282afd`
- Source tree: `3eedb87c5eead92a08b11e056a4e019a2ca048e4`
- Evidence Closure: the commit containing this report
- API Lab: `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`
- Force push: no; PR: none

## 3. Previous Evidence

ITER-056 observed Direct Cheap 58/72 and optimized CGNK 48/72 on mostly
shorter tasks. That result remains unchanged and motivated a workload focused
on the stateful and evidence-sensitive claims made for CGNK.

## 4. ITER-057 Router Negative Result

The paired oracle equaled Direct Cheap at 58/72 with `CGNK_ONLY=0`. Router V1
was not adopted. ITER-058 does not reopen or implement it.

## 5. Research Questions

The study asks whether CGNK adds reliable value when work requires persistent
state, provenance, supersession, repair continuity, restart/resume, or
capability reuse, and whether the Knowledge SCC can be removed safely.

## 6. Hypotheses

The preregistration expected possible B2 gains in chain success, provenance,
rework, and bounded context. The primary unit was the complete scenario chain;
episodes were not treated as independent observations.

## 7. Architecture Audit

The audit covered 247 production Python modules, 82,830 lines, 862 public
functions, 557 classes, 274 dataclasses, 554 import edges, and maximum import
depth 9 after the change.

## 8. Knowledge SCC Graph

Before: `store -> persistence -> internalization -> store` through projection,
legacy load, mutation, and bucket/index helpers. After: pure projection points
downward; store owns compatibility wrappers; persistence owns serialization and
mutation; internalization consumes both without back-importing store.

## 9. SCC Root Cause

Pure index/bucket projection logic lived inside `store.py`, persistence needed
legacy loading and projection, and internalization imported store helpers while
store also imported internalization behavior.

## 10. SCC Change Decision

The decomposition was justified because a small pure module could remove the
cycle without a schema migration, public API deletion, authority change, or
second state store.

## 11. SCC Before / After

Before: 246 modules, 82,816 LOC, 553 edges, one cyclic SCC. After: 247 modules,
82,830 LOC, 554 edges, zero cyclic SCCs. Public function/class/dataclass counts
and maximum depth were unchanged. Net cost: one file and 14 LOC.

## 12. Essential Workload Design

Six families each contain five-episode chains. Development used 12 chains;
formal used 18 disjoint chains. Each chain tests accumulated facts across state,
evidence, updates, repair, capability reuse, or mixed project continuity.

## 13. Fairness Rules

B0, B1, and B2 used the same DeepSeek cheap route, temperature 0, output cap,
tools, public facts, and call count. Gold remained evaluator-only. B0 received
all relevant raw facts; B1 received a reasonable flat state projection; B2 used
real `ProjectKnowledgePack`, internalization, segmented-v2 save/checkpoint/load,
restart, and retrieval.

## 14. Development Scenarios

Twelve development chains (60 episodes per baseline) were used only for
evaluator and implementation debugging. Formal variants 3–5 were never used to
tune prompts, schemas, projections, or code.

## 15. Development Findings

The valid development batch produced B0 12/12, B1 11/12, and B2 12/12. It
revealed that flat-state accumulation could omit provenance while CGNK's
targeted projection avoided that omission.

## 16. Adopted Optimizations

Three evaluator wording defects were corrected using development data; pure
projection functions were extracted; punctuation-normalized retrieval and
explicit historical superseded retrieval were added without changing defaults.

## 17. Rejected Optimizations

No Router, Multi-Agent runtime, new planner, new state authority, Provider
fallback, public benchmark substitution, or task-specific hidden hint was
added. Full CGNK was not simplified based on development outcomes alone.

## 18. Formal Holdout Freeze

Formal manifest hash is
`sha256:09e806b4706a42d08e15c537a4c78e107527163d5174eb4d15b855fe16e600ea`.
The run is bound to Source Closure `a2c7720…`, clean source, frozen API Lab,
model/config/state hashes, and 270 completed one-shot calls.

## 19. B0 Direct Cheap

B0 passed 18/18 chains and 90/90 episodes. It used 46,163 input and 8,049
output tokens, 60,891 context characters, 195 rework references, and estimated
Provider cost USD 0.0235077.

## 20. B1 Direct + Flat State

B1 passed 17/18 chains and 89/90 episodes. It used 78,209 input and 8,270
output tokens, 166,431 context characters, 195 rework references, and USD
0.0333867. The sole failure was missing provenance at final repair convergence.

## 21. B2 CGNK

B2 passed 18/18 chains and 90/90 episodes. It used 47,108 input and 7,990
output tokens, 65,259 context characters, 159 rework references, and USD
0.0237204.

## 22. Strong Reference

Not run. The question was architectural organization under the same qualified
cheap model, not a strong-model ceiling comparison.

## 23. State Continuity

All baselines passed 3/3. B2 reduced mean rework from 8 to 6 but used more
context than B0. State-continuity necessity is not proven.

## 24. Evidence / Provenance

All baselines passed 3/3 and B0/B2 both achieved 1.0 overall provenance
accuracy. Full architecture provenance benefit is not proven against B0.

## 25. Knowledge Supersession

All baselines passed 3/3. B2 cut mean rework from 10 to 4 and mean context from
2,725 to 2,275 characters versus B0. This is the clearest directional benefit.

## 26. Repair Continuity

B0 and B2 passed 3/3; B1 passed 2/3. B2 avoided one flat-state provenance
failure, but did not exceed B0. The benefit is directional versus B1 only.

## 27. Capability Reuse

All baselines passed 3/3 with equal mean rework. B2 used more context than B0;
capability-reuse benefit is not proven by this holdout.

## 28. Mixed Long-Horizon

All passed 3/3. B2 reduced mean rework from 16 to 12 and mean context from
5,117 to 4,857 versus B0, a directional efficiency result without success gain.

## 29. Chain Success

B0=18/18, B1=17/18, B2=18/18. B0 versus B2 is `BOTH_PASS=18`; B1 versus B2
is `BOTH_PASS=17, CGNK_ONLY=1`.

## 30. Episode Success

B0=90/90, B1=89/90, B2=90/90. The B1 miss is a provenance error, not a task
action or transport error.

## 31. Context Growth

B2 used 7.2% more context than B0 but 60.8% less than B1. A growing flat state
is clearly inefficient here; CGNK is not more context-efficient than raw direct
packets overall.

## 32. Rework

B2 reduced measured repeated-context source references by 36 versus B0
(-18.5%). The benefit is concentrated, not universal.

## 33. State Consistency

All baselines achieved 1.0 state consistency under the frozen evaluator.

## 34. Provenance Accuracy

B0=1.0, B1=0.9889, B2=1.0. The one B1 miss does not establish statistical
superiority for B2.

## 35. Repair Convergence

B0 and B2 converged on every repair chain. B1 omitted the second repair receipt
once while still producing the correct final behavior and interface statement.

## 36. Capability Growth / Reuse

No production capability was created or promoted. Reuse identifiers were
evaluated only inside the workload; all three routes satisfied the tested cases.

## 37. Direct-only Cases

None in either paired comparison.

## 38. CGNK-only Cases

None against B0. One against B1 (`FOR-W4-33`) due to provenance omission.

## 39. Both-fail Cases

None.

## 40. Statistical Analysis

B0 versus B2: difference 0pp, bootstrap CI [0,0], McNemar p=1.0. B1 versus B2:
difference +5.556pp, bootstrap CI [0,16.667], one discordant chain, McNemar
p=1.0. These are directional small-sample results, not significance claims.

## 41. Effect Sizes

Success effect versus B0 is zero. B2 versus B0: rework -18.5%, context +7.2%,
input tokens +2.0%, output tokens -0.7%, estimated cost +0.9%.

## 42. Public Benchmark Preflight

TUA-Bench was blocked by unavailable Docker engine; LongMemEval-V2 lacked its
required environment/data; BFCL V4 lacked Python 3.10. No Provider call or
dataset redistribution occurred.

## 43. Public Benchmark Results

Not evaluated due to environment prerequisites. No internal result is relabeled
as a public benchmark result.

## 44. Architecture Necessity Boundary

For the tested controlled workloads, fair Direct Cheap is sufficient for final
success. CGNK's supported boundary is narrower: deterministic organization can
reduce repeated evidence work in supersession and mixed long-horizon chains,
but full architecture necessity is not proven.

## 45. Router Reopen Evidence

No. A Router choosing B2 over B0 has no observed success opportunity on the
formal holdout. The B1-only miss is not a reason to route away from B0.

## 46. Complexity Cost

Full B2 adds persistence/retrieval machinery, 945 input tokens, 4,368 context
characters, and USD 0.0002127 versus B0 across the holdout. It earns 36 fewer
rework references but no additional chain success.

## 47. Security

Gold was not visible to executors; no secrets, private data, hidden tests,
external writes, Community replies, Promotion publishing, or Provider fallback
occurred. The normalized index excludes credentials and hidden gold.

## 48. Full Regression

All eight profiles passed. Active repository: 3,022 passed, 363 skipped, zero
failed, zero errors. Static gates and canonical version gate passed. The SCC
migration/recovery tests cover v1/v2 read, checkpoint, replay, corrupt fallback,
explicit migration, restart, local update, internalization, and Conversation.

## 49. Claim Ledger

`FULL_CGNK_ARCHITECTURE_BENEFIT=NOT_PROVEN`;
`KNOWLEDGE_SUPERSESSION_REWORK_BENEFIT=PROVEN_DIRECTIONALLY`;
`MIXED_LONG_HORIZON_REWORK_BENEFIT=PROVEN_DIRECTIONALLY`;
`KNOWLEDGE_SCC_DECOMPOSITION=PASS`; `ROUTER_REOPEN_EVIDENCE=NO`.

## 50. Release Decision

Release `v0.2.0-rc.4` as an internal-boundary and research-evidence candidate.
Do not claim a new public execution architecture or bump to v0.3.

## 51. GitHub Release

The prerelease targets the final Evidence Closure and attaches the normalized
formal index. No PyPI, Docker Hub, Zenodo, arXiv, leaderboard, or social-media
publication is authorized.

## 52. Remaining P0/P1/P2

- P0: none.
- P1: full-architecture necessity remains unproven; public benchmark execution
  remains environment-blocked.
- P2: investigate a smaller supersession/mixed-chain state projection before
  any routing research; estimate provider nondeterminism with repeated holdouts.

## 53. Commits

- `a2c7720…` — Source Closure: Knowledge SCC decomposition, frozen workload,
  rc.4 version identity, and regression evidence.
- Evidence Closure — the commit containing formal evidence and this report.

## 54. Final Verdict

Direct Cheap was stronger in ITER-056 largely because those tasks did not
require architecture-specific continuity. On the targeted ITER-058 holdout,
fair B0 still matched B2's perfect success, so flat-state fairness was not the
deciding factor and full CGNK necessity is not proven. CGNK did reduce repeated
work for supersession and mixed chains, but repair and capability-reuse success
did not exceed B0. The SCC split was worthwhile because it removed a real cycle
at minimal cost with all compatibility gates passing. Router stays dormant;
Multi-Agent remains not recommended; CGNK should continue shrinking toward the
smallest evidence-sensitive state/recovery substrate supported by data.
