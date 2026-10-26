# Knowledge Boundary Decomposition Audit

## Before

The deterministic architecture audit found one cyclic strongly connected
component:

`cgnk_knowledge.internalization ↔ cgnk_knowledge.persistence ↔ cgnk_knowledge.store`

The cycle was real but conceptual rather than a second authority. `store`
owned public pack/index helpers and imported persistence; persistence locally
imported `store` for legacy reconstruction and migration, and locally imported
private internalization helpers for tail replay; internalization imported
`store` to reuse deterministic index and compatibility-bucket projection.

## Change

Pure, deterministic in-memory projection logic moved to
`cgnk_knowledge.projection`. It imports only the standard library and owns no
persistence, migration, recovery, provider, runtime, or application authority.
Store, persistence replay, and internalization now depend one-way on that
projection. Legacy loading moved behind a persistence helper while the existing
public `load_legacy_project_knowledge` compatibility function remains intact.

No persisted schema, public package export, default behavior, recovery policy,
Knowledge authority, or migration contract changed.

## After

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| cyclic SCCs | 1 | 0 | -1 |
| production LOC | 82,816 | 82,830 | +14 |
| public functions | 862 | 862 | 0 |
| public classes | 557 | 557 | 0 |
| dataclass/schema classes | 274 | 274 | 0 |
| maximum import depth | 9 | 9 | 0 |
| production modules | 246 | 247 | +1 internal projection module |
| dependency edges | 553 | 554 | +1 shared one-way projection edge |

The post-change SCC count is zero. The new edge/module and 14 LOC are the
explicit cost of removing three mutually dependent implementation paths while
retaining compatibility wrappers; public function/class and authority counts
do not increase. Architecture metrics hash:
`sha256:86c252e3023957553b1e286f79054efb7caa79e441602fe923fb15e851a98a5a`.

Targeted store, retrieval, internalization, segmented-v2 persistence,
migration, checkpoint, replay, and compatibility tests remain mandatory before
Source Closure.

