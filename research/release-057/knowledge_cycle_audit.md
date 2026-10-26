# Knowledge / Persistence Boundary Audit

## Scope

This audit covers `src/cgnk_knowledge/store.py`, `persistence.py`, and
`internalization.py`. It does not change Knowledge authority or persistence
format.

## Observed dependency cycle

- `store` imports persistence contracts and load/save helpers.
- `internalization` imports store mutation helpers.
- `persistence` uses bounded local imports from store for index rebuild and
  legacy loading, and from internalization for index/bucket synchronization.

The local imports prevent import-time failure, but the three modules form one
conceptual strongly connected component. Eliminating it cleanly would require
moving shared index mutation and legacy migration behavior behind a dedicated
internal boundary and revalidating persistence, crash recovery, migration, and
250k-scale evidence.

## Decision

`P1_FUTURE_NO_CHANGE`. The change is larger than a low-risk dependency
inversion for this hygiene increment. No duplicate authority exists, and there
is no observed correctness failure. A broad refactor would violate the bounded
scope of ITER-057.
