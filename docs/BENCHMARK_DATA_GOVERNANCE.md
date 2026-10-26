# Benchmark Data Governance

## Public and private packets

The `PUBLIC_PROJECT_PACKET` contains only the requirement, normalized public
contract, acceptance criteria, constraints, and public starting state. A
`PRIVATE_EVALUATOR_PACKET` may contain hidden tests, gold outputs, expected
failure classes, and evaluator labels. Private packets live under a separate
local namespace and are never indexed, exported, sent to models, internalized
into Knowledge, or returned by corpus search.

## Family-level splits

Deterministic split seed `5901` assigns the whole project family—not individual
attempts or snapshots—to development, validation, or formal holdout. Repair,
extension, migration, and continuation descendants stay with their family.
Quarantined material is never sampled.

The leakage checker rejects a family or task hash appearing across splits.
Future benchmark freezing must also evaluate source hashes, shared-file ratios,
and explicit parent/child lineage. During formal evaluation, corpus and Knowledge
retrieval must exclude the holdout family and related variants.

## Sampling

```bash
cgkn corpus benchmark-sample \
  --split DEVELOPMENT \
  --complexity MEDIUM \
  --count 10 \
  --seed 5901 \
  --output benchmark-manifest.json
```

The result contains only entry/family/attempt identifiers, selection rules, and
the seed. Freezing a future formal manifest must additionally lock evaluator
references outside model-visible storage.

## License, privacy, and redistribution

Generated-original material is distinguished from user-supplied, third-party,
public-repository, and benchmark-derived sources. Restricted benchmark data is
represented by task IDs, manifests, result metadata, and reproduction
instructions only. It is never repackaged merely because CGNK is Apache-2.0.

Secret-bearing source, unknown provenance, malicious archives, symlink escapes,
oversized files, and unresolved licenses are quarantined. Corpus dataset
publication requires a separate license, privacy, provenance, deduplication,
and contamination review; ITER-059 does not authorize it.
