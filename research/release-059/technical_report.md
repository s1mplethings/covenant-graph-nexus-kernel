# CGNK Project Corpus Foundation

## 1. Executive Summary

ITER-059 adds a local-first, content-addressed Project Corpus for preserving
successful, failed, partial, repaired, and quarantined project attempts. On the
frozen source closure `a6c9414f687a9e44e4370112b709b8662907796f`, all 14
preregistered hard gates passed. The result is
`PROJECT_CORPUS_BENCHMARK_READY`: a benchmark-material substrate, not a public
dataset and not evidence that the full CGNK architecture is beneficial.

## 2. Git Identity

- Base: `main@8a7bdd7d1a719d7e9a8b182ae47c515908ba63a7`
- Work branch: `codex/project-corpus-foundation-20261026`
- Source Closure: `a6c9414f687a9e44e4370112b709b8662907796f`
- Source tree: `a0fe7cd93cb4f593864210c973d89d6f11b42024`
- Version: `0.2.0-rc.5`

## 3. Motivation

Final successful source alone hides the most useful project-generation
evidence: failed first attempts, partial materialization, test failures, repair
inputs, patches, repeated work, and the transition to acceptance. The corpus
preserves that history without changing generation decisions.

## 4. Corpus Scope

The v1 scope covers local capture, immutable objects, versioned manifests,
derived cataloging, deterministic search/sampling, reconstruction, verification,
portable family import/export, privacy quarantine, and benchmark split guards.
It excludes training, semantic deduplication, Provider-call replay, vector
search, automatic garbage collection, and public dataset distribution.

## 5. Authority Boundary

Project Corpus is application/evaluation infrastructure. ProjectKnowledgePack,
AgentComposer, CapabilityTree, ExecutionDAG, ProjectBlueprint, FileRunStore,
the bounded executor interface, and Git remain their existing authorities. A
best-effort capture failure cannot change the project outcome.

## 6. Storage Design

Each corpus root contains immutable SHA-256 objects, versioned attempt and
snapshot manifests, a derived SQLite/FTS catalog, and staging space. The root is
configured with `CGNK_PROJECT_CORPUS_ROOT`; no machine-specific root is encoded
in a manifest.

## 7. Content Addressing

Files are stored once by SHA-256 and referenced from snapshots. Object writes
verify existing bytes on collisions. Exact content reuse creates references,
not copies. The formal profile stored 23 references over 20 physical objects;
the scale workload reached a 1,000x repeated-content deduplication ratio.

## 8. Catalog

SQLite is a rebuildable projection over manifests and objects, not the source
of truth. Deleting and rebuilding the catalog restored all 10 formal entries
with stable statistics.

## 9. Project Family / Attempt / Snapshot

Family identity groups related variants; attempt identity records an individual
run; snapshot identity records a lifecycle stage. The formal corpus contains
10 families, 10 attempts, and 17 snapshots.

## 10. Source Preservation

Manifests store normalized project-relative paths, hashes, byte sizes, modes,
file types, and optional language. Generated caches, environments, dependency
trees, and ordinary build products are excluded by policy.

## 11. Failure Preservation

FAIL and PARTIAL entries remain first-class. The formal profile contains six
PASS, one FAIL, two PARTIAL, and one QUARANTINED attempt; failures are not
silently collapsed into the final successful state.

## 12. Repair Trace

The dogfood repair family retains INPUT, FAILED_TEST, PRE_REPAIR, POST_REPAIR,
and FINAL snapshots, the `add-subtracts` failure fingerprint, sanitized patch
evidence, before/after references, and failing/passing test results.

## 13. Test Evidence

Test evidence records command, status, exit code, counts, duration when
available, and affected public files. Hidden evaluator implementation remains
outside the public project packet and searchable catalog.

## 14. Model / Capability Metadata

Entries can record provider/model identity, route, token/cost fields, retry
counts, capability references, and Knowledge evidence references without
storing credentials or copying the KnowledgePack. Deterministic dogfood records
`provider=deterministic`, `model=none` honestly.

## 15. Complexity Metadata

Raw metrics include file, source/test line, module, dependency, language,
episode, state-dependency, capability, repair, Knowledge-source, and version
counts. A deterministic LOW/MEDIUM/HIGH/EXTREME label supplements rather than
replaces those values.

## 16. Lineage

Parent attempt/snapshot, derived-from, repair-of, extension-of, and migration-of
relations are explicit. Only fully evidenced relations are recorded.

## 17. Search

Structured filters cover family, status, type, language, complexity, failure,
provider, capability, date, and tags. SQLite FTS5 is used when available, with a
deterministic fallback. Private/quarantined material is excluded.

## 18. Dedup

File-level SHA-256 deduplication is authoritative. Near-duplicate handling is
limited to family/task identity and simple shared-file measures; no semantic
similarity claim is made.

## 19. Privacy / Secret Handling

Capture scans source and metadata for credential patterns and local identity
leaks. The formal secret case was quarantined without admitting secret source
bytes to the normal object store. The history audit found zero P0 findings.

## 20. License / Provenance

CGNK-owned work remains Apache-2.0. No new dependency, vendored code, font,
media, model asset, or Postiz implementation was added. Unknown or unlicensed
corpus material is quarantined. See `provenance_audit.json` and
`docs/THIRD_PARTY_LICENSES.md`.

## 21. Private Evaluator Boundary

PUBLIC_PROJECT_PACKET and PRIVATE_EVALUATOR_PACKET are distinct. Gold answers,
hidden assertions, and hidden test source cannot enter model context, Knowledge,
normal search, benchmark samples, or portable exports.

## 22. Split Governance

Split assignment is deterministic at family level using seed 5901. All sibling
attempts and variants remain together.

## 23. Leakage Prevention

The formal leakage check found no family or exact task hash crossing splits.
This proves exact/family isolation for the frozen cases, not semantic
near-duplicate detection.

## 24. Import / Export

Portable family export/import preserved one repair family and its two referenced
objects. Import validates the whole archive before commit and rejects traversal,
absolute paths, links, oversized members/totals, unsafe compression ratios,
missing objects, hash mismatches, and manifest conflicts.

## 25. Reconstruction

The final repair snapshot reconstructed from an empty directory with one file
and exact byte equality. The verified snapshot hash is
`sha256:ea93fa4f659e1a73dba1d48f31caa5c45a84dc94ad2b7728cfd796f7ffef4d23`.

## 26. Replay

V1 guarantees source reconstruction and preserves test commands/evidence. It
does not claim that remote Providers or unavailable external environments can
be replayed identically.

## 27. Crash Recovery

Staged captures are never reported COMPLETE. Recovery either finalizes a fully
validated staged entry or retains/marks incomplete evidence; catalog failure
does not alter the project result.

## 28. Catalog Rebuild

Core catalog state was rebuilt from immutable manifests. Verification reported
zero missing, corrupt, or unreferenced objects in the formal corpus.

## 29. Scale Evaluation

The deterministic scale case completed 1,000 snapshots and 10,000 file
references over 10 objects in 9.362 seconds. It tests CAS/catalog integrity and
deduplication, not realistic diversity or production throughput.

## 30. Historical Backfill

Six repository example families were classified without invention: two
FULLY_RECOVERED, three SOURCE_ONLY, and one PARTIAL_METADATA_ONLY. They are not
claimed as six recovered live Provider projects.

## 31. Real Dogfood Capture

Three deterministic application dogfoods cover success, failure-repair-success,
and partial outcomes. All were captured and verified; the repair chain contains
five lifecycle snapshots.

## 32. Corpus Profile

The formal non-scale profile contains 10 families, 10 attempts, 17 snapshots,
20 objects, 23 references, 21,498 logical bytes, and 21,417 physical bytes.
Aggregate data is public; the actual local corpus is not.

## 33. Future Benchmark Sampling

Seeded selection produced a reproducible three-family DEVELOPMENT manifest.
Future holdouts must remain outside development search, Knowledge, and model
context.

## 34. AI Project Generation Benchmark Readiness

All preregistered corpus substrate gates passed, so status is
`PROJECT_CORPUS_BENCHMARK_READY`. This means future complexity experiments can
use stable family/snapshot packets; it is not a readiness claim for training or
a specific generation architecture.

## 35. Security

The history audit scanned 6,284 unique reachable blobs and returned PASS with
zero P0 findings. Archive, path, secret, private-evaluator, split, hash, and
capture-failure cases passed. Known P1/P2 findings are deliberate detectors,
test fixtures, or historical generated paths, not live credentials.

## 36. Full Regression

Application/experiment tests passed `719 passed, 2 skipped`. The focused corpus
suite passed `22 passed, 1 skipped`; project-loop plus corpus passed `76 passed,
1 skipped`; coverage core passed `472 passed, 1 skipped`. Final profile totals
and receipt identity are recorded in `governance/kernel_test_receipt.json`.
Live-provider remains an environment-gated skip and is not converted to PASS.

## 37. Storage Cost

The metadata implementation uses only standard-library SQLite and filesystem
objects. Capture is synchronous at run boundaries. Large-binary lifecycle and
background ingestion remain future policy work.

## 38. Limitations

The evaluation is deterministic and small. It does not prove semantic
deduplication, dataset representativeness, distributed safety, cloud operation,
cross-machine environment replay, model training value, or broad real-provider
project diversity.

## 39. Future Project Problem Generator

The corpus can later supply frozen starting snapshots for controlled deletion,
bug injection, schema change, configuration replacement, or feature-extension
tasks. ITER-059 implements no problem generator.

## 40. Release Decision

Release `v0.2.0-rc.5` is approved as a Research Preview once the final evidence
commit is promoted to `main` through the canonical publisher and the remote SHA
is verified. No PyPI, container, dataset, Zenodo, arXiv, leaderboard, or social
publication is authorized.

## 41. Remaining P0/P1/P2

- P0: none.
- P1: collect broader real-provider and multi-language corpus families before
  drawing quality or representativeness conclusions.
- P2: evaluate semantic near-duplicate detection and large-object lifecycle in
  separately preregistered work.

## 42. Commits

- `25f433…` — Project Corpus implementation, schemas, tests, docs, and initial
  governance.
- `333052…` — rc.5 version alignment and receipt bootstrap.
- `a6c941…` — final rc.5 deployment-identity test alignment.
- Evidence Closure and canonical main promotion are recorded in
  `evidence_closure.json` and the GitHub release.

## 43. Final Verdict

`PROJECT_CORPUS_BENCHMARK_READY`. The implementation preserves all evaluated
outcomes, reconstructs byte-faithfully, retains a complete repair chain,
isolates private/secret material, prevents family split leakage, survives
catalog rebuild and capture failure, and passes the frozen scale case. The
verdict is deliberately limited to the local corpus substrate.
