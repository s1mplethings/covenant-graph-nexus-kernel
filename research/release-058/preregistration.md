# ITER-058 Preregistration

Frozen date: 2026-10-26

## Research question

Does current CGNK provide value unavailable to direct cheap-model execution on
multi-stage tasks requiring persistent state, exact evidence provenance,
supersession, repair continuity, restart recovery, or capability reuse? The
study does not assume that CGNK should win overall.

## Frozen workload

- Workload: `CGNKEssentialWorkloadV1`
- Development: 12 chains / 60 episodes, variants 1–2 in each family
- Formal holdout: 18 chains / 90 episodes, variants 3–5 in each family
- Families: state continuity, evidence provenance, knowledge update and
  supersession, repair continuity, capability reuse/composition, and mixed
  long-horizon project continuity
- Total workload hash: `sha256:1be5009ff4b58e4208fd0045081a6b42500ef5f12ff4dd3211a510121de1111d`
- Formal manifest hash: `sha256:09e806b4706a42d08e15c537a4c78e107527163d5174eb4d15b855fe16e600ea`

Gold terms, forbidden terms, required evidence IDs, expected action, and
expected capability IDs are never included in model-facing packets.

## Baselines

- `B0_DIRECT_CHEAP`: all accumulated raw public facts, without structured state.
- `B1_DIRECT_CHEAP_WITH_FLAT_STATE`: the same facts in one flat current/history/source document; no hierarchy, retrieval, invalidation, repair receipt logic, or capability registry.
- `B2_CGNK_CURRENT`: actual ProjectKnowledgePack internalization, segmented-v2 persistence/checkpoint recovery, and bounded Knowledge retrieval plus direct current-event/dependency evidence.

All routes use the same DeepSeek cheap Provider alias, temperature 0, 450
maximum output tokens, 90-second configured timeout, 120-second outer deadline,
the same answer schema, and no logical retry. API Lab may perform only its
frozen bounded transport attempts. Baseline configuration hash is
`sha256:ca2748a16f089220cab45184eee720c069df0e35c2fa137bef4d1efdbb1cd87b`;
answer schema hash is
`sha256:904757aaa27b860230f3fd4c51a630f5c8d406519470659932eccacccaf42503`.

## Primary outcomes

The primary unit is a complete chain. Report success by baseline and family,
and paired `BOTH_PASS`, `DIRECT_ONLY`, `CGNK_ONLY`, and `BOTH_FAIL` counts for
B0/B2 and B1/B2. A family benefit requires repeatable CGNK-only chain success
and a mechanism-consistent explanation; one isolated success is directional
only. Overall necessity is not inferred from episode-level pseudo-replication.

Secondary metrics are episode success, provenance accuracy, state consistency,
restart recovery, context characters, input/output tokens, repeated context
sources, capability reuse/composition correctness, and failure class.

## Statistics

Use paired chain-level absolute differences, 95% paired bootstrap intervals
with seed 58026 and 10,000 resamples, and exact two-sided McNemar tests where
appropriate. Episode metrics are descriptive repeated observations and are not
treated as independent. With 18 formal chains, all claims remain directional.

## Exclusions and failures

One logical Provider call is made per episode. Reasoning, schema, provenance,
action, stale-state, or capability-reuse failures are task failures and are not
retried or excluded. Only preregistered infrastructure impossibility or a
demonstrably evaluator-invalid case may be excluded, with its ID and evidence
reported. Unknown usage remains null, never zero.

## Formal freeze rule

Formal evaluation begins only after one canonical Source Closure freezes the
workload, formal manifest, state projections, schema, prompts, model config,
SCC architecture, tests, and report skeleton. Any subsequent source change
invalidates every formal result. Formal results cannot authorize implementation
of Router or Multi-Agent in this iteration.

## Verdicts

Report `CGNK_NECESSITY_OVERALL` and one verdict for each family using only:
`PROVEN`, `PROVEN_DIRECTIONALLY`, `NEUTRAL`, `HARMFUL`, or
`INSUFFICIENT_EVIDENCE`. `ROUTER_REOPEN_EVIDENCE` may become
`YES_DIRECTIONAL` only as a future research note; Router stays dormant.

