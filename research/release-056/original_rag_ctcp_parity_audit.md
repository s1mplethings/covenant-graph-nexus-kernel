# Original RAG / CTCP parity audit

Status vocabulary: `IMPLEMENTED`, `PARTIAL`, `SUPERSEDED`, `MISSING`,
`NO_LONGER_NEEDED`, and `UNVERIFIABLE`.

## Provenance and method

The audit compares the current source tree with repository history, the
archived tag `cgnk-ctcp-bridge-review-package-v1`, its
`docs/CTCP_FEATURE_SELECTION.md` and `examples/ctcp/ctcp_feature_map.json`,
current product authority, and prior iteration summaries. The archived CTCP
material explicitly describes a migration source rather than current product
authority. No executable, uniquely identifiable "original RAG" implementation
survives in the reachable source history, so claims about its exact algorithms
or performance are `UNVERIFIABLE`; the feature intentions named below are
verifiable from the archived design material and current task contract.

## Parity matrix

| Original idea | Current implementation | Status | Evidence / limitation |
|---|---|---|---|
| Bottom-up retrieval | Raw evidence is indexed directly; derived summaries point to `source_refs`; Conversation can expand a matching summary into raw children. | IMPLEMENTED | `src/cgnk_knowledge/store.py`, `retrieve.py`, and `cgkn/application/conversation/service.py`. |
| Local-domain retrieval | `scope`, `branch_ref`, `subject_ref`, `by_branch_ref`, lexical postings, and bounded AgentContextPack selection localize candidates. | IMPLEMENTED | The index and local context pack share the ProjectKnowledgePack authority. |
| Leaf-first search | Detail queries drill from summaries to raw leaves and stale summaries are excluded. General lexical ranking is not a strict leaf-before-ancestor traversal. | PARTIAL | Preserving lexical relevance avoids forcing an obsolete traversal rule onto every query. |
| Branch/path convergence | Explicit and branch dependency modes converge source facts into derived nodes; branch-local invalidation follows dependent closure. There is no general-purpose path-convergence planner. | PARTIAL | Current source graph is sufficient for knowledge maintenance but not a literal reconstruction of an old graph algorithm. |
| Tree/vein-like organization | `source_refs`, relations, branch/subject indexes, derived nodes, and CapabilityTree provide tree-and-edge organization. Knowledge is stored as a normalized item graph, not a second tree authority. | SUPERSEDED | The normalized graph/index preserves the behavior without introducing a parallel knowledge runtime. |
| Abstraction nodes | `make_derived_abstraction` creates typed derived evidence with source dependencies, branch identity, freshness, and refresh count. | IMPLEMENTED | Abstractions remain derived, never raw authority. |
| Summary as navigation | Conversation treats summary/abstraction nodes as retrieval indexes and excludes their raw children until an explicit detail/fidelity gate. | IMPLEMENTED | `summary_is_source = false`; lossy summaries without children fail closed. |
| Raw evidence drill-down | Exact/detail/version/boundary queries trigger bounded child expansion with stable raw content and evidence IDs. | IMPLEMENTED | Expansion depth, nodes, and context characters are bounded. |
| Cross-domain boundary | Scope/branch metadata and retrieval tests isolate domain-specific facts; global/project/module/session scopes rank deterministically. | IMPLEMENTED | Isolation is metadata-enforced; it is not a separate domain database. |
| Local invalidation | New evidence invalidates the transitive dependent closure plus branch-derived dependents, marking only those nodes stale. | IMPLEMENTED | `internalize_evidence` records invalidated IDs and does not globally rebuild abstractions. |
| Lazy refresh | `LOCAL_LAZY` is the default; invalidation never calls a reducer implicitly; `refresh_stale_abstractions` is explicit and bounded. | IMPLEMENTED | Eager refresh remains an explicit alternative for experiments. |
| Contradiction | Typed contradiction relations, conflict review state, receipts, and Conversation fail-closed behavior preserve both competing facts. | IMPLEMENTED | Relevant conflicts yield insufficient evidence rather than a fabricated resolution. |
| Supersession | Typed superseding/correction/retraction relations archive prior facts while retaining history and provenance. | IMPLEMENTED | Retrieval excludes superseded facts unless history is requested. |
| Version/history | Evidence has source versions/revisions; segmented persistence is append-oriented, supports checkpoints, tail replay, and `as_of_sequence`. | IMPLEMENTED | Physical v1 single-file persistence is compatibility-only. |
| Query routing | Exact lexical postings, selected modules, types, scope, archive/reference flags, and Conversation detail routing determine the bounded evidence path. | IMPLEMENTED | Semantic synonym routing remains intentionally limited and measurable. |
| Candidate growth | Inverted postings prune absent and selective terms, but common-token union candidates still grow linearly and each candidate is tokenized more than once. | PARTIAL | This is the next measured optimization target; correctness gates prohibit lossy pruning. |
| Knowledge internalization | Evidence is hashed, deduplicated, relation-classified, version-checked, indexed, locally invalidated, and emitted with a mutation receipt. | IMPLEMENTED | Automatic production admission remains outside this boundary. |

## Retained and rejected CTCP scope

The current kernel retains the reviewed CTCP concepts of project generation,
artifact/evidence contracts, provider capabilities, graph edits, decision
gates, strong-intent validation, migration, and benchmarks. The old Telegram
bot, progress fallback, sanitizer, monolithic orchestrator, and outbox designs
remain rejected. Reintroducing them solely for name-level parity would violate
current product authority.

## Conclusion

Behavioral parity is strong for evidence fidelity, localization, maintenance,
and history. The remaining material gap is candidate-growth efficiency and the
absence of a universal leaf-first/path-convergence algorithm. The latter is not
automatically a defect: the current normalized graph supersedes a literal
tree/vein runtime. Optimization may target candidate scoring only after a
frozen before-profile and must preserve raw recall, contradiction recall,
supersession, selection hashes, and exact output ordering.
