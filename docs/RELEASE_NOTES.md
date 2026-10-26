# CGNK 0.2.0-rc.4 Research Preview

CGNK is a composable capability kernel for evidence-grounded agentic project
work. This boundary release safely removes the Knowledge store/persistence/
internalization import cycle and publishes a preregistered necessity study.

## Boundary and evaluation highlights

- Knowledge cyclic SCCs fell from one to zero with no schema, public signature,
  authority, persistence-format, or recovery change.
- Frozen formal results: B0 Direct Cheap 18/18, B1 Flat State 17/18, B2 CGNK
  18/18 chains; B0 versus B2 has zero discordant chains.
- B2 reduced measured rework 18.5% versus B0 but added 7.2% context and 0.9%
  estimated Provider cost. Full architecture benefit is not proven.
- All 270 formal calls completed with reported usage and no transport failure.
- Router remains not adopted; Multi-Agent remains not recommended.

## Known limitations

The 18-chain sample is directional and has one run per route/chain, so it is not
a statistical-significance or Provider-reliability claim. Public benchmark
formal runs remain environment-blocked.

## Compatibility and migration

The release does not introduce another planner, runtime, state store, or public
delivery route. Existing compatibility entrypoints remain present. Repository
users should review `docs/ARCHITECTURE.md`, `docs/REPRODUCIBILITY.md`, and the technical
report before treating an experimental application surface as qualified.

## Security, license, and citation

CGNK-owned work is Apache-2.0. Third-party assets retain their own licenses; see
`docs/THIRD_PARTY_LICENSES.md`. Report vulnerabilities through `SECURITY.md`.
Citation metadata is in `CITATION.cff`.
