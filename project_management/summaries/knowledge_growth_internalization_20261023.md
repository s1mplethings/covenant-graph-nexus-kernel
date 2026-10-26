# ITER-044 Knowledge Growth Internalization

## Outcome

`ITER-CGNK-KNOWLEDGE-GROWTH-INTERNALIZATION-044` closed `PASS` on source
commit `b1c6eb9673fd20a2631e6a8f3a9206495dd1fef2`.

The existing `ProjectKnowledgePack` remains the single knowledge authority and
`cgnk_knowledge.retrieve_relevant_knowledge` remains the single retrieval
authority. The increment adds local-lazy internalization, update relationships,
dependency invalidation, explicit stale-derived state, and on-demand refresh
without changing Conversation request/response semantics or L0-L5 authority.

## Validated lifecycle

- Raw content is preserved byte-for-byte with a distinct exact-content hash.
- Exact duplicates merge observation provenance with zero model calls, no new
  raw item, no invalidation, and no derived rebuild.
- Supporting, novel, superseding, contradicting, correction, retraction, and
  unresolved relationships are explicit and receipt-backed.
- Superseded or retracted raw observations remain historical evidence.
- Only actual dependent derived nodes become stale; unrelated branches remain
  untouched and hot-path recomputation is zero.
- A bounded warm classifier is optional only for unresolved relationships, and
  its proposed target and relation are deterministically validated.
- Cold refresh is explicit, on-demand or batch, and derived abstractions remain
  recomputable caches rather than evidence truth.

## Conversation after update

A frozen-source probe superseded `Service port 8000` with `Service port 9000`,
invalidated `summary.service`, and queried the normal Conversation surface.
Conversation selected only the new raw evidence, excluded the stale summary and
old value, retained the existing retrieval authority, and used zero Provider
calls.

## Controlled maintenance comparison

| Entries | Policy | Write ms | Invalidated | Hot recompute | On-demand recompute | Retrieval candidates | Context chars |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | Flat Append | 0.295 | 0 | 0 | 0 | 101 | 3,290 |
| 100 | Eager Global | 2.719 | 10 | 10 | 0 | 2 | 32 |
| 100 | Local Lazy | 0.207 | 1 | 0 | 1 | 2 | 32 |
| 1,000 | Flat Append | 0.603 | 0 | 0 | 0 | 1,001 | 34,790 |
| 1,000 | Eager Global | 160.145 | 100 | 100 | 0 | 2 | 32 |
| 1,000 | Local Lazy | 0.491 | 1 | 0 | 1 | 2 | 32 |
| 5,000 | Flat Append | 1.681 | 0 | 0 | 0 | 5,001 | 182,790 |
| 5,000 | Eager Global | 4,843.445 | 500 | 500 | 0 | 2 | 32 |
| 5,000 | Local Lazy | 1.975 | 1 | 0 | 1 | 2 | 32 |

All rows preserved raw history and exposed the updated fact. All maintenance
paths used zero model calls. The result supports
`knowledge_internalization_benefit = PROVEN_DIRECTIONALLY`; no statistical
significance is claimed. Full `ProjectKnowledgePack` serialization remains
linear in pack size and is not represented as constant-time maintenance.

## Regression

- Focused application and knowledge suite: `518 passed`, `1 skipped`.
- Kernel profiles: static, unit, boundary, fault, security, local-functional,
  full-core, and active-repository all `PASS`.
- Unit freshness rerun: `479 passed`, `1 skipped`.
- Full repository: `2690 passed`, `351 skipped`, `0 failed`, `0 errors`.
- Collection: `3041` tests.
- Product direction, architecture, completeness, and receipt freshness gates:
  all `PASS`.

The first unit-profile attempt ran before the updated application receipt was
written and correctly failed its freshness assertion. No source change was
made; after binding the receipt to the frozen application boundary, the unit
profile passed in full.

## Remaining limits

- The benchmark is deterministic and directional, not a statistically
  significant production workload study.
- Monolithic pack serialization is linear and may dominate persistence at
  larger real-world sizes.
- Broader ANN/vector retrieval, sharding, and multi-agent work remain out of
  scope and require separate evidence rather than authority duplication.

Evidence root:
`D:/CGKN/.service_evidence/knowledge-growth-internalization-v1`.
