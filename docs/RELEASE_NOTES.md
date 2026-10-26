# CGNK 0.2.0-rc.5 Research Preview

CGNK is a composable capability kernel for evidence-grounded agentic project
work. This candidate introduces a local-first Project Corpus so the system can
retain successful, failed, partial, repaired, and aborted project attempts as
auditable material.

## Project Corpus highlights

- SHA-256 content-addressed objects deduplicate unchanged files across
  snapshots, attempts, and project families.
- Versioned attempt, snapshot, and benchmark manifests separate immutable
  evidence from the rebuildable SQLite/FTS catalog.
- The minimal project loop can capture generation, failed-test, pre/post-repair,
  final, and aborted stages when `CGNK_PROJECT_CORPUS_ROOT` is configured.
- Capture failure is isolated from project execution and never changes project
  success, repair, or scheduling.
- Public project packets and private evaluator packets are physically separated;
  private packets are not searched or included in portable family exports.
- Family-level deterministic splits and leakage checks keep attempts, repairs,
  extensions, and variants together.
- `cgkn corpus` provides initialization, inspection, search, integrity checks,
  reconstruction, import/export, catalog rebuild, and seeded sampling.

## Architecture boundary

Project Corpus is application/evaluation infrastructure. It is not a second
ProjectKnowledgePack, planner, runtime, DAG, ProjectBlueprint, FileRunStore, or
Git authority. The existing Agent -> CapabilityTree -> ExecutionDAG -> bounded
Executor -> Result/Test/Artifact -> Project State -> Agent checkpoint path is
unchanged.

## Data and security boundary

Real corpus data remains outside Git. Secret-bearing source and unknown or
unlicensed provenance are quarantined. Portable imports reject traversal,
symlinks, oversized members, unsafe compression ratios, hash mismatches,
missing objects, and manifest conflicts. No corpus dataset, PyPI package,
container image, Zenodo record, arXiv paper, leaderboard submission, or social
announcement is published by this release.

## Known limitations

This release does not implement vector search, semantic near-duplicate
detection, Provider-call replay, model training, automatic garbage collection,
or cross-machine environment reproduction. Historical backfill is limited to
evidence actually present in the repository and is labeled as full, source-only,
or metadata-only rather than inferred.

## License and citation

CGNK-owned work is Apache-2.0. Third-party assets retain their own licenses; see
`docs/THIRD_PARTY_LICENSES.md`. Report vulnerabilities through `SECURITY.md`.
Citation metadata is in `CITATION.cff`.
