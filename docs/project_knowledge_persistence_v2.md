# ProjectKnowledgePack Persistence Format v2

Status: production implementation specification for
`ITER-CGNK-SEGMENTED-PERSISTENCE-PRODUCTIONIZATION-046`.

## S2_PRODUCTION_GAP_AUDIT

The production persistence entry points are
`cgnk_knowledge.store.load_project_knowledge` and
`cgnk_knowledge.store.save_project_knowledge`. Format v1 is one pretty-printed
JSON document. A save rebuilds every compatibility bucket and the complete
term/dependency index, serializes the complete document, and overwrites the
target with `Path.write_text`. A load reads and parses the complete document
and then rebuilds the complete derived projection again.

The current path has no write lock, temporary-file commit, replace protocol,
file or record checksum, sequence, interrupted-write recovery, orphan
classification, checkpoint, or compaction. `ConversationExecutor` calls the
same loader synchronously when given `knowledge_path`. The production API does
not otherwise distinguish the physical format.

| Class | Current fields or values | Reason |
|---|---|---|
| AUTHORITATIVE | `kind`, `id`, `project`, `version`, `knowledge_revision`, `diagnostics`, every `all_items` item, raw content and hashes, provenance/source refs and versions, relations, supersession/correction/contradiction/retraction state, retention/review/status, derived-item content and stale state | These values define the logical ProjectKnowledgePack, history, evidence identity, retrieval eligibility, and as-of result. They cannot be reconstructed from an index or checkpoint alone. |
| DERIVED_REBUILDABLE | `knowledge_index`, active type buckets, `archived_items`, `discarded_items` | They are deterministic projections of authoritative `all_items` plus pack revision. |
| EPHEMERAL | retrieval candidates/ranking, Conversation context and response, operation timings, receipts, transient lookup maps | They describe an execution, not persistent knowledge truth. |

Derived-node `derived_state`, `stale_due_to`, dependencies, content, and
revision remain authoritative semantic state. A serialized lookup index or
compatibility bucket containing those nodes remains a derived cache.

The product currently behaves as a single-writer store but does not enforce
that assumption. Format v2 enforces one local writer with an operating-system
file lock and permits lock-free readers because committed manifests are
replaced as complete files.

## Authority model

There is one logical authority: the canonical ProjectKnowledgePack mutation
history. Its physical authoritative representation is an ordered, validated
chain of immutable segment records. Folding that chain yields the logical
ProjectKnowledgePack state.

Checkpoints, indexes, compatibility buckets, and cache files are derived,
rebuildable, and non-authoritative. A missing, stale, corrupt, cross-pack, or
authority-mismatched checkpoint is ignored and the authoritative segments are
replayed. No Provider chooses a sequence, segment/checkpoint path, manifest
layout, or persistence metadata.

## Directory layout

```text
pack-root/
  manifest.json
  .write.lock
  segments/
    seg-<start>-<end>-<digest>.json
  checkpoints/
    checkpoint-<sequence>-<digest>.json
  quarantine/                 # optional diagnostic destination
```

`manifest.json` is a checksummed physical-layout descriptor. It is not a fact
source. It binds the pack identity, generation, schema and policy versions,
strict sequence range, ordered authoritative segment descriptors, latest
optional checkpoint, and authority-history root hash.

## Authoritative record and segment protocol

Each canonical mutation receives one strictly increasing sequence. A record
contains its format, operation, deterministic target identity, canonical
payload, bounded provenance, and hash. The record hash excludes incidental
physical layout. The authority root is a chain over ordered record hashes and
therefore remains stable when segment boundaries change.

Each immutable segment is self-identifying and contains format/pack identity,
sequence start/end, record count, prior and resulting authority roots, records,
and a content checksum. The manifest also stores the hash of the exact segment
file bytes so checkpoint-assisted cold load can validate an unchanged prefix
without parsing every historical record.

A commit writes and fsyncs a temporary segment, replaces the final segment,
validates it, writes and fsyncs a temporary manifest, and replaces the
manifest. Directory fsync is used where the operating system supports it.
Until the manifest replacement, a complete new segment is an uncommitted
orphan and cannot become truth. After replacement, the mutation is committed
even if optional maintenance fails.

## Checkpoint protocol

A checkpoint materializes logical state as of an authoritative segment
boundary. It binds pack identity, covered sequence, authority root, logical
semantic hash, format/schema versions, and a checksummed derived index. Before
publication, replayed authoritative state and checkpoint state must have the
same semantic hash. Load may use only a fully validated checkpoint whose
authority prefix matches the manifest, then replay later segments. Otherwise
it performs full authoritative replay.

Checkpoint cadence is policy-controlled by committed tail mutation count or
tail bytes. A normal mutation never requires a checkpoint to succeed.

The initial production policy uses 256 committed tail mutations or 64 MiB for
checkpoint due status. The source-phase short/medium/long experiment showed
that 16 and 64 mutation intervals repeatedly paid full checkpoint cost while a
256 interval retained bounded tail replay. The initial compaction policy uses
64 segments with a bounded 32-segment merge; this was the measured middle
point between excessive 16-segment maintenance and 256-segment directory and
manifest growth. These are versioned policy defaults, not product semantics.

## Compaction protocol

Compaction merges a bounded contiguous prefix of immutable authoritative
segments into fewer authoritative segments without changing or deleting any
canonical record. Replacement segments are built separately, replayed, and
checked for record-sequence, authority-root, and semantic-state equivalence.
The manifest is switched only after validation. Old physical segments are
removed only after the new manifest reloads successfully; an interruption
therefore leaves either the old layout or the new layout recoverable.

Compaction is triggered by configurable segment count, tail bytes, and
small-segment ratio. It never emits an active-state-only summary and never
promotes a checkpoint into authority.

## Format v1 and migration

The loader auto-detects an existing v1 file or v2 directory. Unknown versions
fail closed. Migration is explicit: load v1, compute the physical-independent
`PROJECT_KNOWLEDGE_SEMANTIC_HASH`, build v2 at a separate temporary target,
reload v2, compare semantic hashes, and only then expose the v2 target. The v1
source is retained and receives no further writes after the caller selects v2
as active. There is no dual-write mode.

Until the production 100k/250k adoption gate is satisfied, a previously
nonexistent path continues to use the legacy v1 default. New v2 stores require
an explicit `format_version="2.0"` request or the migration command. This keeps
deployment reversible and prevents offline correctness alone from silently
changing the public persistence default.

The semantic hash includes authoritative pack metadata and all authoritative
item values sorted by stable item identity. It excludes indexes, compatibility
buckets, checkpoint metadata, manifest generation, timestamps, segment order
incidents, and segment boundaries.

## Failure behavior

Referenced missing, malformed, oversized, cross-pack, checksum-invalid,
duplicate/gapped/rolled-back sequence, or broken-chain segments fail closed.
Unreferenced complete or partial segment files are reported as orphans and
never replayed. Corrupt/missing checkpoints and indexes are rebuildable
failures, not authority failures. A contended writer receives
`PACK_WRITE_LOCKED` rather than risking silent corruption.

The crash invariant is: a reader observes the old committed manifest state or
the new fully committed manifest state, never a half-visible mutation.
