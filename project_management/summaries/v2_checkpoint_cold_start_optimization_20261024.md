# V2 checkpoint cold-start optimization

Workstream C closed the remaining production-v2 adoption blocker without changing knowledge authority, retrieval semantics, mutation sequencing, compaction, or migration.

The phase profile showed CPU-bound state traversal, repeated deep copies, JSON materialization, and semantic validation dominated build and cold-load time. The selected implementation stores a small derived checkpoint descriptor plus a validated current-state component and a policy-bound derived index sidecar. Missing, corrupt, hash-mismatched, or policy-mismatched checkpoint data is discarded and rebuilt by authoritative segment replay.

Formal quiet-window requalification used the frozen checkpoint source `859919f3555a1fff985377da41bbf8bece08b18a` and the same fixed configuration at 10k, 50k, 100k, and 250k. Every scale passed semantic equivalence and 100% retrieval recall. At 250k, checkpoint build fell from 151.342 seconds to 31.469 seconds, and checkpoint cold-load fell from 45.472 seconds to 8.064 seconds. The optimized cold-load is 78.457% faster than the unchanged 37.430-second S0 baseline. First retrieval took 0.113 ms, first Conversation readiness took 1.280 seconds, and corruption fallback replay passed.

The unchanged adoption gate therefore passed. V2 is the default only for newly created packs. Existing v1 packs remain readable and retain v1 on ordinary writes; explicit v1 creation and explicit migration remain supported. No automatic migration is introduced.

Retrieval scaling P2 remains retained: this work did not alter ranking or Conversation semantics.
