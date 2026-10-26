# Knowledge Growth and Internalization

CGNK uses `ProjectKnowledgePack` as its only knowledge authority. Internalization
does not create another graph or database. It adds deterministic lifecycle,
relationship, dependency, invalidation, and derived-cache semantics to that
pack while preserving raw evidence and existing Conversation provenance.

## Gap audit

The pre-iteration classification was
`PARTIAL_LIFECYCLE_WITHOUT_DEPENDENCY_INVALIDATION`.

| Operation | Previous state |
|---|---|
| new raw evidence | partial: dialogue extraction existed, exact raw fidelity was not explicit |
| exact duplicate | partial: normalized hashes merged source refs |
| supporting evidence | missing |
| novel fact | existing |
| updated fact | partial |
| supersession/version | partial and domain-specific |
| contradiction | partial review-state support, no relationship lifecycle |
| correction | partial classification only |
| retraction/deletion | partial archive/discard helpers |
| derived refresh | missing |
| ancestor invalidation | missing |
| cross-branch isolation | missing |
| index update | global rebuild |
| provenance | partial `source_refs` and stable hashes |
| Conversation after update | partial status filtering, no stale-derived contract |

The learning/lesson subsystem is a separate application concern and is not
used as knowledge truth.

## Lifecycle and paths

Receipts expose the applicable stages from `OBSERVED`, `IDENTIFIED`, `DEDUPED`,
`LOCATED`, `RAW_COMMITTED`, `RELATION_CLASSIFIED`,
`DEPENDENTS_INVALIDATED`, `DERIVED_STALE`, `INTERNALIZED`, and `AVAILABLE`.
This is an auditable projection, not a second persistent state machine.

- Hot path: preserve exact content, calculate identity, validate provenance,
  deduplicate, locate through the pack index, commit raw evidence, record a
  deterministic relation, invalidate actual dependents, update indexes, and
  emit a receipt. It performs zero Provider calls.
- Warm path: only unresolved semantic relationships may use an optional bounded
  classifier. Its result is validated against existing target identity, scope,
  subject, and version metadata and is never authority by itself.
- Cold path: explicit on-demand or batch abstraction refresh. Global rebuild is
  not part of every write.

Relations are `EXACT_DUPLICATE`, `SUPPORTING`, `NOVEL`, `SUPERSEDING`,
`CONTRADICTING`, `CORRECTION`, `RETRACTION`, and `UNRESOLVED_RELATION`.

## Evidence fidelity

Raw content is stored byte-for-byte in the existing item content field and has
a SHA-256 content hash. CRLF/LF, ordering, identifiers, versions, negative
observations, and transport details therefore remain distinguishable. Derived
abstractions are recomputable cache/index nodes with explicit `source_refs` and
fresh/stale state. Retraction and supersession change active truth selection but
do not delete the historical raw observation.

Conversation uses the existing retrieval authority. Stale derived nodes are
excluded; updated active raw evidence remains retrievable. A cold refresh can
rebuild only the requested stale dependency closure.

## Maintenance policies and evaluation

`FLAT_APPEND` and `EAGER_GLOBAL_REBUILD` exist as controlled comparison modes.
The product default is `LOCAL_LAZY`.

The deterministic evaluation at 100, 1,000, and 5,000 entries compares write
latency, invalidation/recomputation, retrieval candidates, selected context,
pack size, model calls, raw-history preservation, and updated-fact visibility.
Run it with:

```text
python scripts/run_knowledge_growth_evaluation.py --profile final --sizes 100 1000 5000 --json
```

Internalization is worthwhile when facts have stable subjects/branches,
repeated retrieval, derived abstractions, update/retraction requirements, or
audit-sensitive provenance. Flat raw evidence remains cheaper for a tiny,
write-once corpus that is rarely queried. Eager global rebuild is justified
only by an explicit consistency requirement that cannot tolerate stale derived
caches; the default evidence does not support doing it on every write.

The monolithic JSON pack still has linear serialization cost. The local-lazy
claim applies to semantic maintenance and retrieval candidate selection, not to
claiming constant-time serialization of the entire persisted artifact.
