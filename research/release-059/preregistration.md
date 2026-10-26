# ITER-059 Project Corpus Preregistration

Status: frozen before source closure and formal evaluation  
Iteration: ITER-059  
Deterministic split and sampling seed: `5901`

## Question

Can CGNK preserve its own successful, failed, partial, repaired, and aborted
project history as an auditable, local-first Project Corpus without creating a
second Knowledge, planning, runtime, or project-state authority?

## Fixed implementation boundary

Project Corpus is application/evaluation infrastructure. Capture observes the
existing project loop and writes immutable content objects, versioned manifests,
and a rebuildable SQLite catalog. It cannot change a ProjectBlueprint, schedule
a DAG, select a provider, influence runtime success, publish data, or mutate
ProjectKnowledgePack. Capture failure must remain failure-isolated from project
execution.

## Fixed corpus cases

1. Historical backfill: six explicit repository example directories, preserving
   their available source and classifying recovery honestly.
2. Dogfood success: generated original, accepted without repair.
3. Dogfood failure-repair-success: failed test evidence, pre-repair and
   post-repair snapshots, deterministic patch evidence, final acceptance.
4. Dogfood partial: incomplete project attempt retained without a success claim.
5. Privacy negative: a secret-bearing source is quarantined and its source
   bytes are not admitted to the normal object store.
6. Scale corpus: deterministic 1,000 snapshot manifests and at least 10,000
   file references over a small repeated object set.

The historical backfill is repository-example evidence, not a claim that six
live provider projects were recovered.

## Frozen gates

Formal status is `PROJECT_CORPUS_BENCHMARK_READY` only if all are true:

- at least five historical project families are represented;
- success, failure, partial, and repaired lifecycles are represented;
- family, attempt, and snapshot identities remain distinct;
- object hashes, manifest references, and catalog projections verify;
- reconstruction is byte-faithful to the captured snapshot objects;
- repair lineage contains the failed input, failure evidence, repair evidence,
  output snapshot, and acceptance result;
- the derived catalog can be deleted and rebuilt from manifests;
- family export/import preserves manifests and referenced object hashes;
- private evaluator material is not searchable or exportable;
- secret-bearing material is quarantined without storing secret source bytes;
- deterministic family-level split assignment has no cross-split family or
  task-hash leakage;
- structured filters and seeded sampling are reproducible;
- the 1,000-snapshot / 10,000-reference evaluation completes without corruption;
- all repository direction, architecture, security, kernel, and full pytest
  gates pass on the frozen source closure.

## Failure definitions

- `INTEGRITY_FAILURE`: any object hash mismatch, missing reference, invalid
  relative path, or catalog/manifests disagreement.
- `REPLAY_FAILURE`: reconstruction differs byte-for-byte from the captured
  object set or escapes the target directory.
- `LINEAGE_FAILURE`: a repair result cannot be traced to failure evidence,
  patch/diff evidence, before/after hashes, and acceptance.
- `PRIVACY_FAILURE`: secret/private evaluator material enters normal source
  objects, search results, export, model-visible packet, or Knowledge.
- `SPLIT_LEAKAGE`: one family or exact task hash appears in multiple benchmark
  splits.
- `CAPTURE_COUPLING_FAILURE`: capture storage failure changes project success,
  repair, or scheduling semantics.
- `UNSUPPORTED_REPLAY`: evidence is intact but external environment or provider
  behavior cannot be reproduced. This is reported and not converted to pass.

## Metrics

Record families, attempts, snapshots, objects, file references, physical bytes,
logical bytes, deduplication ratio, catalog rebuild time, reconstruction time,
search time, export/import status, quarantined entries, failure/repair coverage,
split leakage findings, and all regression results.

## Holdout and contamination rules

No future formal holdout family may be searched, sampled into development,
internalized into Knowledge, or exposed to a model during evaluation. All
attempts and variants of one family share one split. Unknown provenance or
license is quarantined. Restricted benchmark data is referenced by metadata
only. ITER-059 publishes no corpus dataset.

## Interpretation limits

Passing proves integrity and operational usefulness of this local substrate on
the frozen cases. It does not prove semantic near-duplicate detection, training
value, production-scale throughput, provider-call replay, broad dataset quality,
or statistical representativeness. Scale uses deterministic repeated content
to evaluate catalog/CAS behavior, not real-world diversity.
