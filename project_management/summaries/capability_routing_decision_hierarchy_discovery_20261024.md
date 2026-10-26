# Capability routing and decision hierarchy discovery

This is WORKSTREAM B discovery evidence for
`ITER-CGNK-PARALLEL-ARCHITECTURE-CONVERGENCE-050`. It is not the formal D0-D3
live comparison. Formal model/cost conclusions must be rerun on the integrated
source closure.

## Authority and design

- `CapabilityRegistry` remains the only capability authority.
- `CapabilitySearchIndex` is an in-memory, deterministic, rebuildable lexical
  inverted-index projection of registry descriptors and their bound
  `ComponentSpec` values.
- Eligibility is evaluated before ranking for lifecycle qualification, input
  availability, effect compatibility, permissions, scope, required state, and
  version.
- Search returns only a bounded top-k context and records both full-registry
  and top-k token estimates.
- `DecisionRouter` is a deterministic routing policy, not an Agent, planner,
  runtime, scheduler, or state authority.
- L0 applies proven deterministic rules, L1 uses a qualified cheap route only
  with a validator and reversible bounded scope, L2 handles semantic risk or
  validator-driven escalation, and L3 stops at protected human boundaries.
- Model self-reported confidence has no routing authority.

## Discovery results

The current real L6 registry projection contains 10 capabilities. Three real
queries achieved 3/3 Top1 and Top3 selection. Because the registry is small,
the current product conclusion is `NOT_YET_NEEDED_AT_CURRENT_SCALE`, not a
claim of current production savings.

Synthetic deterministic fixtures demonstrate scaling direction only:

| Registry size | Top1 | Top3 | Full context tokens | Top-k tokens | Context reduction | Median search ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 1.0 | 1.0 | 12,774 | 263 | 97.9411% | 1.2478 |
| 500 | 1.0 | 1.0 | 64,321 | 264 | 99.5896% | 5.2181 |
| 1,000 | 1.0 | 1.0 | 128,755 | 264 | 99.7950% | 10.4574 |

The 24-case routing fixture contains six deterministic, eight cheap-sufficient,
six strong-required, and four critical-stop cases. D3 routed all 24 as
expected, with zero false escalations, zero missed escalations, and 4/4 critical
stops. D0-D3 results in this branch are deterministic discovery simulations;
they are not live Provider, token, cost, or reliability evidence.

## Frozen discovery identities

- benchmark hash: `sha256:fb7a9e6e1d42f21d5e199066fa602baebb186d22815016fa23a6068a2a7ee773`
- decision policy hash: `sha256:7f6359036dec0511dbc34ff4017c176c90f9ab81bd9081207cb5319b747aae51`
- escalation policy hash: `sha256:b8a912249623073a640466025df0e53e15b5fd677f35162905d191b73fb23b45`
- model-config hash: `sha256:d0daac2d3b9b166870ae0fd4f0ca33ac157cc9059631702dabca77c980f80f7e`

## Integration notes

- Run the formal D0/D1/D2/D3 comparison on the integrated source using the
  same public evidence, validators, registry, budgets, and acceptance.
- Keep `CapabilitySearchIndex` derived and rebuildable; do not persist it as a
  second capability database.
- Integrate a bounded top-k catalog at the decision-call boundary only after
  the integrated real search smoke passes.
- No persistence, checkpoint, Knowledge persistence, Conversation semantics,
  or Blueprint production files were changed.
- `CROSS_WORKSTREAM_DEPENDENCY`: none.

