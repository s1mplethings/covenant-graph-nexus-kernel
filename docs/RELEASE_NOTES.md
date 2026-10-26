# CGKN 0.2.0-rc.2 Research Preview

CGKN is a composable capability kernel for evidence-grounded agentic project
work. This release consolidates the single-Agent/CapabilityTree/ExecutionDAG
architecture, adds Apache-2.0 release metadata, improves indexed knowledge
retrieval and bounded context projection, and publishes a preregistered
cross-domain evaluation with negative results intact.

## Highlights

- 3,001 tests passed, 363 skipped, 0 failed/errors.
- Clean-clone installation and offline benchmark smoke passed.
- Optimized CGKN reduced median context by 98.27% versus flat context.
- Optimized and previous CGKN paths had similar success (48/72 vs 49/72).
- Direct Cheap achieved the highest holdout success (58/72); the report does
  not claim CGKN improves quality over direct execution.
- Stable dependency prompt projection removes timing, usage, and receipt-only
  metadata from downstream workers.
- Current and 7,726-blob history compliance audits found zero P0 issues.

## Known limitations

Public CRAG, LongMemEval-V2, BFCL V4, TUA-Bench, and SWE-bench Pro V2 formal
runs were environment-blocked. Strong-route cost is incomplete after a timeout
and frozen budget exhaustion. Self-Growth, Persona, Community, and Promotion
retain their experimental or approval-required boundaries. Multi-Agent Runtime
is not recommended or enabled.

## Compatibility and migration

The release does not introduce another planner, runtime, state store, or public
delivery route. Existing compatibility entrypoints remain present. Repository
users should review `docs/ARCHITECTURE.md`, `docs/REPRODUCIBILITY.md`, and the technical
report before treating an experimental application surface as qualified.

## Security, license, and citation

CGKN-owned work is Apache-2.0. Third-party assets retain their own licenses; see
`docs/THIRD_PARTY_LICENSES.md`. Report vulnerabilities through `SECURITY.md`.
Citation metadata is in `CITATION.cff`.
