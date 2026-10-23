# ITER-045 Knowledge Persistence and Retrieval Scaling

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Base branch: `codex/knowledge-growth-internalization-20261023`
- Product scaling base source: `b1c6eb9673fd20a2631e6a8f3a9206495dd1fef2`
- Previous evidence closure: `260a7fd238fd9eb97998c9172fe7995d08a431a8`
- Work branch: `codex/knowledge-persistence-retrieval-scaling-20261023`
- Benchmark harness closure: `657574921ff0a06fb742294d12027160c07bdcf2`
- API Lab retained: `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`
- Force push: no. PR/merge: not requested.

## 2. Previous Validated Baseline

ITER-044 remains valid: knowledge growth, internalization, local-lazy
invalidation, Conversation-after-update, and the directional internalization
benefit stay PASS. No production Knowledge or Conversation code changed here.

## 3. Persistence Gap Audit

`save_project_knowledge` rebuilds all compatibility buckets and the complete
index, pretty-serializes the whole pack, and writes directly to the authority
path. `load_project_knowledge` reads the whole file, parses it, then discards
the persisted index in favor of another complete rebuild.

Classification:
`MONOLITHIC_FULL_REWRITE_WITH_PERSISTED_REBUILT_DERIVED_INDEX_AND_NO_ATOMIC_COMMIT`.

## 4. Authority vs Derived Data

| Class | Data |
|---|---|
| AUTHORITATIVE | pack identity/revision, `all_items`, raw/tombstone content, hashes, provenance, source versions, relation and lifecycle state |
| DERIVED_REBUILDABLE | `knowledge_index`, active type buckets, archived/discarded projections |
| EPHEMERAL | candidate lists, ranked query results, Conversation context/response, receipts, timing, transient lookup maps |

Derived abstraction content remains persisted because a reducer is required to
recreate it; its raw dependencies and stale state remain authoritative facts.

## 5. Current Physical Storage Model

One pretty UTF-8 JSON file holds both authority and duplicated derived
projections. At every save it is truncated and rewritten without a temp file,
atomic rename, file/directory fsync, checksum, or last-known-good recovery.

## 6. Benchmark Design

All core measurements are Provider-free, use real filesystem write/close,
process-isolated cold load, and deterministic state/query hashes. Uniform
corpora ran at 1k, 5k, 10k, 50k, 100k, and resource-approved 250k. The 10k
scale also ran hot-branch and long-tail skew. Each scale performed five real
single-update saves and 12 correctness query classes.

## 7. Corpus Shapes

The frozen corpus includes novel observations, merged duplicate provenance,
support, version supersession, contradictions, retractions/tombstones, fresh
and stale abstractions, explicit source references, and local dependency
branches. Branch counts were 20, 100, 100, 500, 1000, and 1000 respectively.

## 8. 1k Results

2.59 MiB file; update logic P50 1.40 ms; full save P50 125.22 ms; cold load
75.56 ms; query P50/P95 0.05/1.26 ms; peak RSS 0.04 GiB; accuracy 100%.

## 9. 5k Results

12.81 MiB; update 9.86 ms; save 1,098.13 ms; cold load 383.04 ms; query
0.06/2.32 ms; peak RSS 0.09 GiB; accuracy 100%.

## 10. 10k Results

25.59 MiB; update 22.48 ms; save 2,490.08 ms; cold load 844.71 ms; query
0.08/5.60 ms; peak RSS 0.15 GiB; accuracy 100%.

## 11. 50k Results

127.86 MiB; update 126.17 ms; save 14,654.21 ms; cold load 6,057.61 ms;
query 0.12/36.85 ms; peak RSS 0.65 GiB; accuracy 100%.

## 12. 100k Results

255.75 MiB; update 276.37 ms; save 29,715.30 ms; cold load 12,757.03 ms;
query 0.14/72.79 ms; peak RSS 1.28 GiB; accuracy 100%.

## 13. 250k Results

639.47 MiB; update 258.01 ms; save 80,617.51 ms; cold load 37,430.23 ms;
query 0.15/199.71 ms; peak RSS 3.16 GiB; accuracy 100%. This was the maximum
safe scale; 500k was not attempted.

## 14. Serialization Scaling

Serialization P50 rose from 92.03 ms at 1k to 48,568.41 ms at 250k. The
persisted document stayed about 3.2 times the compact authoritative projection
because items are repeated in compatibility buckets and index structures.

## 15. Persistence Write Amplification

Physical bytes per logical changed byte rose from 8,125× at 1k to 2,001,607×
at 250k. Windows newline translation was measured separately: serialized
UTF-8 bytes and physical file bytes are not silently conflated.

## 16. Cold Start Scaling

Cold load rose from 75.56 ms to 37.43 s. Time-to-first retrieval and
time-to-first evidence-only Conversation answer are dominated by that load and
rebuild, not by the indexed lookup itself.

## 17. Memory Scaling

Cold-process peak RSS rose from 0.04 GiB to 3.16 GiB; steady 250k RSS was about
1.01 GiB. It remained within the 75% guard but grew linearly and must not be
reported as constant-memory.

## 18. Retrieval Scaling

Exact/local query P50 remained near constant (0.05 to 0.15 ms). Ambiguous
query P95 increased to 199.71 ms because the maximum candidate set grew from
60 to 5,000. Index lookup is local for selective terms, not for common terms.

## 19. Retrieval Recall / Correctness

All 12 query classes retained 100% correctness and identical result hashes
after restart at every evaluated scale. Equivalent-answer sets were used for
intentionally ambiguous and synonym cases; version, stale, retraction, and
cross-domain assertions remained exact and fail-closed.

## 20. Local Update After Restart

The first post-restart update remained `NOVEL`, invalidated/recomputed zero
nodes, touched zero unrelated nodes, became visible to retrieval, and appeared
in a read-only `EVIDENCE_ONLY` Conversation response with zero Provider calls.

## 21. Read-heavy Workload

S0 at 10k completed 1,000 ops in 233.30 s and wrote 2,315.29 MiB. S2 completed
10k/50k/100k read-heavy in 0.82/5.00/11.75 s with all checks PASS.

## 22. Balanced Workload

S2 completed 10k/50k/100k balanced workloads in 5.35/26.80/56.82 s. Current
S0 combinations were not executed when measured P50 projected beyond the
600-second workload guard.

## 23. Write-heavy Workload

S2 completed 10k/50k/100k write-heavy in 10.92/48.24/100.10 s. The 100k run
performed 910 updates, wrote 1.03 MiB, and preserved 100% fixed-query recall.

## 24. End-to-End Internalization Cost

For S0 10k read-heavy, persistence P50 was 2,529.08 ms versus 6.56 ms for
internalization; serialization (1,806.31 ms) and index rebuild (578.85 ms)
dominated disk I/O (128.36 ms). For S2 100k write-heavy, internalization P50
was 103.27 ms and persistence P50 only 2.97 ms.

## 25. Persistence Locality Gap

`PERSISTENCE_LOCALITY_GAP = PROVEN`. From 1k to 250k, corpus size grew 250×,
single-save P50 grew 643.83×, and persistence consumed 99.68% of the largest
single-update wall time.

## 26. If Applicable: Storage Alternatives

| 100k strategy | Update P50 | Bytes/update | Cold load | Peak RSS | Result |
|---|---:|---:|---:|---:|---|
| S0 current | 29,715.30 ms | 255.75 MiB | 12,757.03 ms | 1.28 GiB | PASS, persistence-bound |
| S1 chunked authority | 26.75 ms | 0.242 MiB | 30,299.33 ms | 0.58 GiB | PASS, 1001 files |
| S2 append authority | 3.18 ms | 1.15 KiB | 16,542.95 ms | 0.76 GiB | PASS, leading update candidate |
| S3 compact authority + sidecar | 4,508.71 ms | 77.32 MiB | 21,507.08 ms | 1.01 GiB | PASS, still O(N) write |

## 27. Crash / Corruption Safety

Current S0 detects malformed JSON but cannot recover a partial direct write and
does not detect valid-JSON tampering. S1 detected corrupt chunks and ignored an
unreferenced partial temp; S2 recovered an incomplete tail and discarded a
corrupt checkpoint; S3 rebuilt a corrupt sidecar and preserved authority when
an interrupted temp existed.

## 28. Conversation After Large-Scale Restart

At every scale the first query produced grounded evidence/provenance and
read-only behavior after a new-process load. No Provider latency was mixed into
retrieval or context construction.

## 29. Quality Preservation

Authority hashes, query hashes, raw identity, relations, lifecycle filters,
stale fallback, provenance, abstention/no-evidence behavior, and cross-domain
isolation all passed. Performance was never accepted without correctness.

## 30. Algorithmic Update Locality

`PASS_SEMANTIC_LOCALITY_WITH_LINEAR_CONTAINER_COPY`: invalidation/recompute and
unrelated-node counts remain local, but copying the list-backed `all_items`
container makes in-memory update CPU grow with corpus size.

## 31. Persistence Update Locality

`PERSISTENCE_BOUND`: production writes the entire 3.2× amplified document for
each small update.

## 32. Retrieval Scalability

`DEGRADED_AMBIGUOUS_CANDIDATES_LINEAR_CORRECTNESS_PASS_AT_250K`: selective
terms remain fast; common/ambiguous candidate sets grow linearly. At 10k,
candidate maxima were 200 uniform, 1,101 hot-skew, and 2,312 long-tail.

## 33. Cold Start Scalability

`DEGRADED_37_43_SECONDS_AT_250K`.

## 34. Memory Scalability

`PASS_AT_250K_LINEAR_3_16_GIB_PEAK`; not evaluated beyond 250k.

## 35. End-to-End Growth Scalability

Current production is persistence-bound. Experimental S2 removes that bound
and exposes the next limit: list-backed in-memory update CPU.

## 36. Maximum Evaluated Safe Scale

250,000 items and 1,000 branches. Available RAM and disk were recorded and the
run stayed below the 75% resource guard. 500k was deliberately not attempted.

## 37. Architecture Implication

Logical `ProjectKnowledgePack` authority should remain singular. Physical
storage should become locally appendable and crash-safe, while checkpoints,
indexes, and projections stay derived and rebuildable.

## 38. Should Storage Be Redesigned Now?

**YES.** The conclusion is based on measured dominance, scaling slope, write
amplification, and crash-safety failure—not on an invented latency SLO.

## 39. Recommended Next Phase

Implement a backward-compatible segmented append authority inspired by S2,
with checksummed records, validated derived checkpoints, bounded compaction,
old-format loading, semantic round-trip gates, and no second truth authority.
Do not adopt the research adapter directly: its cold replay is 16.54 s at 100k
and still needs checkpoint verification/compaction design.

## 40. Autonomous Decisions

- Used process-isolated scale workers to avoid cross-scale memory retention.
- Separated serialized bytes from physical Windows text bytes.
- Corrected an evaluator false negative by accepting any semantically
  equivalent answer only for ambiguous/synonym cases; all frozen data was rerun.
- Applied a 600-second measured-runtime guard to S0 mixed workloads.
- Stopped at 250k and did not attempt 500k.

## 41. Critical Decisions

None. No irreversible migration, public format change, second authority,
Kernel authority change, or Knowledge/Conversation semantic change was made.

## 42. Remaining P0/P1/P2

- P0: none.
- P1: production persistence is non-atomic and O(total corpus); partial writes
  can destroy the only authority file.
- P1: production storage locality contradicts local-lazy semantic locality.
- P2: ambiguous/hot/long-tail retrieval candidate sets grow linearly.
- P2: S2 research needs validated checkpoint and compaction design before use.

## 43. Commits

- `657574921ff0a06fb742294d12027160c07bdcf2` —
  `test: benchmark knowledge persistence scaling` — benchmark harness, adapters,
  CLI, tests, and benchmark documentation.
- Evidence closure is the commit containing this report and the governance
  updates.

Raw evidence root:
`D:/CGKN/.service_evidence/knowledge-persistence-retrieval-scaling-v1`.
