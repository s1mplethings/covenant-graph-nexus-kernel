# ITER-046 Segmented Persistence Productionization

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`.
- Base: `codex/knowledge-persistence-retrieval-scaling-20261023` at `b044844feb34ec6a3783d1d570b615e34cb26a39`.
- Branch: `codex/segmented-persistence-productionization-20261023`.
- Segmented persistence source closure: `3439370f3e0a5ba118199dce10d429e77b77e24f`; tree `7de7e2a25b54fd6924f9e623253b7d6524f374e0`.
- API Lab remains frozen at `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`.
- Normal push only; force push: no; PR/merge: not requested.

## 2. Previous Scaling Evidence

ITER-045 remains the baseline: S0 save P50 was 29.72 s/255.75 MiB at
100k and 80.62 s/639.47 MiB at 250k; 250k cold load was 37.43 s and peak
write amplification was 2,001,607x. Correctness remained 100%.

## 3. Production Persistence Audit

The v1 store rebuilt derived buckets/indexes, pretty-serialized the entire
pack, directly rewrote one file, and had no checksum, safe replace, lock, or
recoverable commit protocol. The formal classification table is in
`docs/project_knowledge_persistence_v2.md`.

## 4. Authority Model

`all_items`, exact raw content, provenance, versions, lifecycle/relations,
pack identity and revision are authoritative. Indexes and compatibility
buckets are derived/rebuildable. Retrieval candidates, responses, timings and
transient maps are ephemeral. There remains one logical ProjectKnowledgePack
authority.

## 5. Format v2

Format `2.0` uses a manifest, immutable authoritative segments and derived
checkpoints. Aggregate format hash is
`sha256:b0847728e602c4c01e2fc572c2832ea91e600d69ede603120cda239e44c61334`.
Unknown versions fail closed.

## 6. Segment Protocol

Each canonical mutation has a strictly monotonic sequence, operation, target,
payload/provenance, record hash and authority-chain linkage. Segments are
self-identifying, versioned and checksummed. Gaps, duplicates, rollback,
spoofing, malformed/oversized records and cross-pack injection fail closed.

## 7. Manifest Protocol

The validated layout descriptor records pack/generation/schema identity,
sequence range, ordered segments, checkpoint coverage, authority root, policy
versions and timestamps. Temp write, flush/fsync and `os.replace` expose the
new state. The manifest describes authority layout but is not a fact source.

## 8. Checkpoint Protocol

Checkpoints are derived and rebuildable. Metadata, document checksum,
authority prefix/root and logical state hash must match. Missing, stale,
corrupt or mismatched checkpoints fall back to full authoritative replay.
Checkpoint plus tail updates cached derived views incrementally. Default due
policy: 256 committed mutations or 64 MiB tail; policy hash
`sha256:22d3b98d90c1818bd5a7017711f5b37a32e159896d19a4cd2957e2cde18542f7`.

## 9. Compaction Protocol

Compaction merges a bounded set of authoritative segments, preserving every
canonical record/hash, raw history, provenance, authority root and as-of
semantics. Replacement files are validated before manifest switch; old files
are removed only after the new layout reloads. Default threshold/batch is
64/32; policy hash
`sha256:814d0238253902e71531081099a7cfdef00d63c52936d595a795a923c391c28b`.

## 10. Legacy Compatibility

Existing v1 files auto-detect and load with unchanged semantics. Existing v1
paths remain v1 unless explicitly migrated. New paths also remain v1 by
default because the production scale adoption gate did not run.

## 11. Migration

Migration is explicit and writes v2 to a separate target, reloads it, compares
physical-independent semantic hash plus retrieval/Conversation behavior, and
retains the v1 source. Rollback deletes only the validated v2 target. There is
no dual-write mode. Migration policy hash:
`sha256:a94d027736ebae6c79a38ca2665df8ad74ccbcb5925c68a0af33b0d3048b7fe6`.

## 12. Crash Safety

C1–C6 commit points, C7 checkpoint interruption and C8 compaction
interruption are covered. Recovery exposes the old committed state or the
fully committed new state. Orphan/uncommitted files are ignored/reported and
never guessed into authority. Result: `PASS_FAILURE_INJECTION_TARGETED`.

## 13. Security

Path traversal, manifest/segment tampering, checksum spoofing, sequence
rollback, old-checkpoint replay, pack mismatch, cross-pack injection,
malformed/oversized records and concurrent writers are rejected. Writers use
an OS lock and return `PACK_WRITE_LOCKED`. Providers cannot choose physical
paths, layout or sequence IDs. No secrets or hidden evidence are involved.

## 14. Targeted Validation

All requested A–AJ behaviors are covered, including 100 sequential mutations,
duplicate/supersession/contradiction/correction/retraction, stale derived
state, checkpoint fallback/tail replay, corruption/gap/partial/orphan cases,
compaction equivalence, raw CRLF/UTF-8/NUL bytes, history/as-of, legacy load,
rollback, Conversation/retrieval equality and locking. Focused suite: 61
passed. Application + Knowledge + Conversation: 580 passed, 39
skipped, 0 failed/errors. Migration shapes: 10/10 PASS.

## 15. Full Regression

Compileall, product direction, Kernel architecture, test architecture, Kernel
completeness and receipt freshness PASS. Static, unit, boundary, fault,
security, local-functional, full-core and active-repository profiles PASS.
Collection: 3112. Full pytest: 2755 passed, 357 skipped, 0 failed, 0 errors.

## 16. Benchmark Freeze

Production benchmark harness hash:
`sha256:327d8da27bd313af42cd839acdea87a52f9318c1c67536157a2ed795862da7ec`.
All formal runs were required to bind source `3439370…`. Preflight found
memory 84.55% used and every available volume over 75% used, so no formal
scale worker was started. Development smoke/policy observations are excluded
from adoption evidence.

## 17. 10k Results

`NOT_EVALUATED_RESOURCE_SAFETY`; no formal run started.

## 18. 50k Results

`NOT_EVALUATED_RESOURCE_SAFETY`; no formal run started.

## 19. 100k Results

`NOT_EVALUATED_RESOURCE_SAFETY`; no formal run started.

## 20. 250k Results

`NOT_EVALUATED_RESOURCE_SAFETY`; no formal run started.

## 21. 500k Results

Not executed. The mandatory 250k precondition was not reached.

## 22. S0 vs S2 Update Latency

S0 frozen values remain 29.72 s at 100k and 80.62 s at 250k. Production S2
values are not available; no speedup claim is made.

## 23. Write Amplification

Production S2 write amplification is `NOT_EVALUATED_RESOURCE_SAFETY`.
Bounded-write behavior is tested functionally but not qualified at scale.

## 24. Disk Amplification

`NOT_EVALUATED_RESOURCE_SAFETY`. No steady-state scale result exists.

## 25. Checkpoint Costs

Formal 10k–250k checkpoint latency is not evaluated. A development-only 1k
study favored the 256-mutation interval over 16/64 because shorter intervals
repeatedly paid whole-checkpoint cost; it is policy-selection evidence, not an
adoption benchmark.

## 26. Compaction Costs

Formal scale cost is not evaluated. A development-only 1k study selected the
moderate 64-segment threshold and 32-segment bounded merge over aggressive 16
and relaxed 256 policies.

## 27. Amortized Maintenance

`NOT_EVALUATED_RESOURCE_SAFETY`; checkpoint and compaction cost is not hidden
inside foreground update numbers.

## 28. Cold Start

Full replay, valid checkpoint+tail and corrupt-checkpoint fallback are tested
by independent-process small smoke, but 10k–250k formal cold-start results are
not evaluated. The 37.43 s S0 250k comparison therefore remains open.

## 29. Memory

Formal S2 peak/steady RSS is not evaluated. Preflight itself observed only
4.89 GiB free of 31.64 GiB (84.55% used), above the 75% stop threshold.

## 30. Read-heavy

`NOT_EVALUATED_RESOURCE_SAFETY` at 100k/250k.

## 31. Balanced

`NOT_EVALUATED_RESOURCE_SAFETY` at 100k/250k.

## 32. Write-heavy

`NOT_EVALUATED_RESOURCE_SAFETY` at 100k/250k.

## 33. Restart → Update → Conversation

Small deterministic restart/update/Conversation semantics PASS with zero
Provider calls. The required 250k production path is not evaluated.

## 34. Migration 10/10

Empty, novel, duplicate, supersession, contradiction, correction, retraction,
derived, raw-byte and cross-domain legacy shapes all pass migration semantic,
retrieval, Conversation, restart and post-migration update checks.

## 35. Algorithmic Locality vs Persistence Locality

Algorithmic Local Lazy evidence from ITER-044/045 remains valid. Production v2
implements physical delta commits, but scale locality remains
`NOT_EVALUATED_RESOURCE_SAFETY` rather than inferred from design.

## 36. End-to-End Internalization Benefit

`NOT_EVALUATED_RESOURCE_SAFETY`. Directional algorithmic benefit remains, but
the combined production storage benefit cannot be claimed without formal runs.

## 37. Adoption Gate

Correctness, migration, crash safety and regression pass. Required 100k/250k
locality and cold-start evidence is missing. Therefore:

`SHOULD_V2_BECOME_DEFAULT_FOR_NEW_PACKS = NO`.

## 38. Legacy Policy

v1 remains readable and the default for new paths. v2 is available only via
explicit `format_version="2.0"` or explicit reversible migration. Legacy
sources are retained and never dual-written.

## 39. Retrieval P2

`RETRIEVAL_SCALING_P2_RETAINED`. Ambiguous candidate growth from ITER-045
still exists and was intentionally not redesigned here.

## 40. Architecture Implication

The production design demonstrates that physical locality can be introduced
behind one ProjectKnowledgePack authority without a database, second graph,
second planner, public Knowledge/Conversation semantic change or L0–L5 change.

## 41. Recommended Next Phase

Free enough disk and memory to put both below 75%, then run the frozen harness
at 10k/50k/100k/250k, including policy, mixed workloads, 100k crash recovery
and 250k restart→supersede→Conversation. Do not change source or defaults first.

## 42. Autonomous Decisions

- Used immutable whole-segment files plus atomic manifest switch rather than
  append-in-place framing, simplifying Windows crash recovery.
- Enforced single writer with OS locks and CAS identity.
- Selected checkpoint 256/64 MiB and compaction 64/32 from development policy
  evidence.
- Fixed the existing missing benchmark pytest marker discovered by full suite.
- Reverted premature v2 default adoption before the final source closure.
- Stopped before every formal scale run when the explicit resource gate failed.

## 43. Critical Decisions

None. No checkpoint authority, raw-history deletion, irreversible migration,
external database, Kernel authority, or public Knowledge/Conversation semantic
change was required.

## 44. Remaining P0/P1/P2

- P0: none in targeted correctness or full regression.
- P1: production v2 is not scale-qualified; 100k/250k locality, cold start,
  maintenance and crash benchmark evidence remains absent due resource safety.
- P1: v2 must not become the new-pack default until that evidence passes.
- P2: ambiguous retrieval candidate growth remains from ITER-045.

## 45. Commits

- `8cce134e1fba57f4c06cb18202f6ab79589aa32f` — initial production v2,
  schemas, maintenance CLI, benchmark harness and tests; superseded as formal
  source by the adoption-gate correction.
- `3439370f3e0a5ba118199dce10d429e77b77e24f` — retain v1 new-pack default and
  require explicit v2 until production scale qualification; formal Source
  Closure.
- `2eab17719738782bb2a8b43a851f77d1c87dd2d9` — refreshed application
  source-bound receipt after 580 targeted tests.
- Evidence Closure is the commit containing this report and final governance
  state.
