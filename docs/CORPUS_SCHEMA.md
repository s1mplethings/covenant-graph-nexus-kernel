# Project Corpus Schema v1

The versioned JSON Schemas are:

- `contracts/project_corpus_entry.schema.json`
- `contracts/project_snapshot_manifest.schema.json`
- `contracts/project_benchmark_manifest.schema.json`

## Project corpus entry

An entry identifies one attempt with `corpus_entry_id`, `project_family_id`,
`project_attempt_id`, `run_id`, timestamps, source/generator versions, task hash,
status, provenance, split, one public project packet, snapshot references, and
structured evidence. Status includes successful, failed, partial, aborted,
blocked, timed-out, and quarantined attempts.

Generator metadata records provider/model/route configuration and available
token, cost, latency, retry, capability, Knowledge-evidence reference, manual
intervention, and environment facts. Unknown usage stays unknown; it is not
converted to zero.

## Snapshot manifest

Every file record uses only a project-relative POSIX path plus content hash,
byte size, mode, type, and optional language. Absolute machine paths and parent
traversal are invalid. Source bytes live in the content-addressed object store.
Reconstruction verifies every object hash before writing.

## Complexity

Raw metrics remain canonical: file count, source/test LOC, module and dependency
counts, language count, task episodes, state dependencies, capabilities, repair
rounds, Knowledge source count, and version count. `LOW`, `MEDIUM`, `HIGH`, and
`EXTREME` are deterministic derived labels only.

## Provenance and quality

Provenance is one of `generated_original`, `third_party_seeded`,
`public_repo_derived`, `user_supplied`, `benchmark_derived`, or `unknown`.
Third-party and benchmark-derived material requires a source reference and
license before normal admission. Unknown provenance is quarantined.

Material labels may include clean, interesting failure, repairable,
multi-failure, stateful, provenance-sensitive, capability-heavy, long-horizon,
noisy, or unusable. Unusable metadata can remain useful; it is not automatically
deleted.

## Versioning

Corpus entry, snapshot manifest, and benchmark manifest are all version `1.0`.
Future incompatible changes require explicit migration. Existing manifests are
never silently rewritten.
