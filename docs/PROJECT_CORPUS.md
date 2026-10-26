# Project Corpus

The CGNK Project Corpus is local-first evaluation and artifact infrastructure.
It preserves what happened during project generation—including failure,
partial materialization, repair, and abandonment—without becoming a second
Knowledge, project-state, planning, or execution authority.

## Storage model

Set `CGNK_PROJECT_CORPUS_ROOT` to an external local directory. Real corpus
contents are not committed to Git. The root contains:

```text
objects/aa/<sha256 remainder>   immutable file bytes
snapshots/<snapshot-id>.json   project-relative file manifests
manifests/<entry-id>.json      family/attempt/run evidence
private/evaluator/             evaluator-only packets, never searched/exported
staging/                       incomplete capture recovery records
catalog.sqlite3                derived, rebuildable search index
```

Files are deduplicated by SHA-256. A snapshot is a manifest over content
objects, not another full directory copy. The catalog is convenient derived
state; manifests plus immutable objects are the corpus authority.

## Identity and lifecycle

`project_family_id` groups the whole project lineage. Each family has attempts,
and each attempt has snapshots. Supported stages are `INPUT`,
`INITIAL_GENERATION`, `POST_MATERIALIZATION`, `PRE_TEST`, `FAILED_TEST`,
`PRE_REPAIR`, `POST_REPAIR`, `FINAL`, and `ABORTED`.

An application-level hook in the minimal project loop is dormant unless the
corpus environment variable is configured. It records bounded public facts and
workspace snapshots. Capture is best-effort: storage failure produces a
`CAPTURE_FAILED` receipt and cannot change the project result.

## Quickstart

```bash
export CGNK_PROJECT_CORPUS_ROOT=/absolute/local/cgnk-project-corpus
cgkn corpus init
cgkn corpus stats
cgkn corpus list
cgkn corpus search --status FAIL --complexity MEDIUM
cgkn corpus show entry-example
cgkn corpus verify
cgkn corpus reconstruct snapshot-example ./reconstructed
cgkn corpus export family-example ./family-example.corpus.zip
```

On PowerShell, set the environment variable with
`$env:CGNK_PROJECT_CORPUS_ROOT = 'D:\local\cgnk-project-corpus'`.

The first version uses Python `sqlite3` and optional FTS5. It does not require
a database service, embedding model, vector database, or cloud account.

## Retention and recovery

Source snapshots, public test evidence, failure chains, patches, and repair
lineage are retained. Caches, virtual environments, dependency directories,
build output, and editor state are excluded. Garbage collection is report-only;
the implementation never deletes real corpus data automatically.

Capture writes immutable objects, staged manifests, finalized manifests, then
one catalog transaction. An interrupted entry remains visible as incomplete
staging or as a manifest recoverable by catalog rebuild; it is never silently
declared complete by the catalog.

## Scope limits

The current version does not fine-tune models, provide semantic near-duplicate
search, publish a public dataset, replay Provider calls, or guarantee that an
environment-dependent failure can be re-executed on another machine. It records
such cases as environment-limited instead of inventing evidence.

See [Corpus Schema](CORPUS_SCHEMA.md) and
[Benchmark Data Governance](BENCHMARK_DATA_GOVERNANCE.md).
