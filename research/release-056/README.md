# CGNK Release 056 Research Package

CGNK is the public project name. Frozen `CGKN...` legacy machine identifiers in
this package are retained for receipt compatibility.

This directory is the source-controlled research record for the release-candidate evaluation. Raw provider responses, benchmark datasets, environment images, secrets, and machine-local paths are never committed. Large or restricted artifacts stay in an external evidence root and are represented here only by sanitized manifests and hashes.

The study order is binding: preregistration commit, RC source freeze, formal execution, normalization/statistics, report, release gates, and only then a repository visibility decision.

## Published artifacts

- `preregistration.md` freezes hypotheses, comparisons, budgets, and stop rules.
- `benchmark_manifest.json` records exact public benchmark revisions and redistribution policy.
- `report/technical_report.md` is the academic-style report.
- `report/formal_results.json` and `report/statistics.json` provide machine-readable results.
- `RELEASE_CLAIM_LEDGER.json` separates supported, refuted, prohibited, and unevaluated claims.
- `research_summary.json` is the compact release research summary.

Raw execution evidence is intentionally excluded from Git because it includes
provider responses and machine-local paths. The committed indexes contain only
sanitized identifiers, aggregate measurements, and cryptographic hashes.

