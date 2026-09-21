# Formal machine specifications

`specs/` is the authoritative machine-readable registry for artifact types,
module contracts, flows, policies, migrations, and context packs. Loaders read
this directory first. The former `examples/<category>` lookup remains only as a
deprecated compatibility fallback when a repository has not migrated yet.

Add new formal definitions here, never under `examples/`.
