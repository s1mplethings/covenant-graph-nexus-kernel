# ITER-CGNK-V2-RESOURCE-GATE-CALIBRATION-AND-SCALE-QUALIFICATION-048

## 1. Git Identity

- repository: `s1mplethings/covenant-graph-nexus-kernel`
- branch: `codex/v2-resource-gate-scale-qualification-20261024`
- production source: `3439370f3e0a5ba118199dce10d429e77b77e24f`
- production tree: `7de7e2a25b54fd6924f9e623253b7d6524f374e0`
- resource harness commits: `6938fbc3fdae7d060965312001427e70a7058c4b`, `e602f54adc620e5c91c94cf5f457ef808a71a48e`

## 2. Frozen Production Source

Production persistence, manifest, checkpoint, compaction, migration, Knowledge,
Conversation, retrieval, internalization, and the new-pack default were not
modified. Provider calls were zero.

## 3. Previous Resource Blocker

ITER-047 stopped because every fixed volume was above 75 percent used. That
rule rejected F: despite roughly 342 GB free and did not model the actual
benchmark working set.

## 4. Why The Fixed 75% Gate Was Inappropriate

The real 250k active-pack peak was 479,389,001 bytes, only 8.409 percent of the
frozen 5,701,169,517-byte conservative estimate. F: had 341,981,667,328 bytes
free before the run. A fixed used-percent threshold was therefore unrelated to
the workload's actual risk and is confirmed over-conservative.

## 5. Resource Calibration

The replacement gate uses actual production-v2 structures and requires the
conservative peak plus transaction/rollback, estimator error, evidence,
OS/filesystem, benchmark-contingency, and memory reserves. Predicted post-run
use must also remain below 98 percent as a secondary guard.

## 6. 1k/5k Probe

| Scale | Peak disk | Peak RSS | Checkpoint due | Compaction due | Status |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1,000 | 3,140,456 B | 64,438,272 B | mutation 255 | mutation 63 | PASS |
| 5,000 | 10,772,539 B | 146,575,360 B | mutation 255 | mutation 63 | PASS |

Both probes used real segments, manifests, checkpoints, compaction, filesystem
writes, and semantic query checks.

## 7. Peak Disk Model

`EXPECTED_PEAK_DISK(scale)` combines measured authoritative bytes with a 1.25
growth margin, checkpoint ratio margin, tail segments, manifest, compaction
duplicate work, transaction/rollback duplicate work, fixed evidence, and the
greater of a 35 percent or 1 GiB estimator-error margin. It emits lower,
expected, and conservative bounds; formal gates use the conservative bound.

## 8. Safety Reserve

For 250k, conservative active peak is 5,701,169,517 bytes. Required free space
including disk OS headroom and a 2 GiB benchmark contingency is 27,852,463,306
bytes. Required available memory is 10,907,713,639 bytes.

## 9. Volume Selection

F: was selected on absolute headroom: 341,981,667,328 bytes free, 13,959,872,512
bytes memory available, predicted post-run free space 336,280,497,811 bytes,
and predicted post-run use 83.189 percent. No user or authoritative data was
deleted.

## 10. Resource Gate Freeze

- resource policy: `sha256:51e774f95fac372862d1a9fc270ad48983c7d99b95a7dbb178be0e384c514ba9`
- peak estimator: `sha256:6b7ea0bf565a4fea46be4bfaae437675a2b6577c0909c84048ee950dc41482e7`
- corpus generator: `sha256:affd7cca5ce88fc0732b1194ad0b2e7f3739b77678b7e8dd125a0ed8ba365c53`
- workload: `sha256:82405d03ff53533bf72ee982905e1ada8e8f1bfdeb8ec6dccb925a289ab7914e`
- harness: `sha256:4af62c41c0c8e235fd077ff026cff18853cc1109e2c074be34696c064b783cc8`

## 11. 10k

PASS. Actual peak 20,153,443 B versus 1,388,562,886 B bound; peak RSS
251,555,840 B; update P50 100.100 ms; write amplification P50 15.451x;
checkpoint 6,386.044 ms; compaction 228.921 ms.

## 12. 50k

PASS. Actual peak 96,943,994 B versus 2,107,330,662 B bound; peak RSS
1,082,650,624 B; update P50 113.859 ms; write amplification P50 15.454x;
checkpoint 35,080.258 ms; compaction 217.059 ms.

## 13. 100k

PASS. Actual peak 191,697,785 B versus 3,005,790,378 B bound; peak RSS
2,115,465,216 B; update P50 72.017 ms; write amplification P50 15.469x;
checkpoint 58,451.113 ms; compaction 121.475 ms.

## 14. 250k

PASS. Actual peak 479,389,001 B versus 5,701,169,517 B bound; peak RSS
5,276,147,712 B; update P50 105.886 ms; write amplification P50 15.472x;
checkpoint 151,341.903 ms; compaction 150.741 ms.

## 15. Prediction vs Actual Peak

Actual peak as a percentage of the conservative bound was 1.451%, 4.600%,
6.378%, and 8.409% at 10k, 50k, 100k, and 250k. Every bound held and every
successful temporary pack was cleaned before the next formal phase.

## 16. S0 vs Production S2

At 250k, S0 update P50 was 80,617.51 ms and 639.47 MiB per save. S2 update P50
was 105.886 ms and 5,183 B P50: 761.361x latency speedup, 129,371.579x byte
reduction, and 129,369.655x write-amplification reduction.

## 17. Normal Update

P50 latency stayed between 72.017 and 113.859 ms across all four scales while
P50 write amplification stayed between 15.451x and 15.472x. Normal persistence
is therefore effectively decoupled from total corpus size for this workload.

## 18. Checkpoint

The unchanged production policy (256 mutations or 64 MiB tail) fired at every
scale. Checkpoints validated and remained derived, rebuildable, and
non-authoritative. The 250k checkpoint cost was 151.342 s and 276,698,389 B.

## 19. Compaction

The unchanged 64-segment threshold / 32-segment merge policy fired at every
scale. Full-replay semantic equivalence, record sequence, authority root, and
cleanup passed; 250k compaction took 150.741 ms and wrote 9,243 B.

## 20. Amortized Persistence

Maintenance remained bounded by the fixed policies. At 250k the measured
checkpoint contribution is about 591.18 ms/update at the 256-mutation interval;
normal persistence is 105.886 ms P50 and steady compaction cost is bounded by
the 64/32 policy. This is dramatically below the 80.62 s S0 update path, though
checkpoint cost remains the principal amortized component.

## 21. Write Amplification

Normal P50 was 15.472x at 250k versus 2,001,607.3x for S0. Checkpoint and
compaction bytes are reported separately in the formal receipt rather than
being hidden inside the normal-update number.

## 22. Disk Amplification

250k peak disk amplification was 2.365x over initial authoritative bytes. Peak
disk explicitly includes segments, manifest, checkpoint, and transaction temp.

## 23. Cold Start

At 250k: full replay 73,293.641 ms, checkpoint+tail 45,472.051 ms, and corrupt
checkpoint fallback 73,402.391 ms. Checkpoint+tail improves on v2 full replay by
37.959%, but is 21.485% slower than the 37,430.23 ms S0 baseline. This fails the
adoption requirement for cold-start improvement.

## 24. Crash Recovery

100k selected C1-C6 injection passed: C1-C5 recovered the old committed state,
C6 recovered the new committed state, with zero data loss and zero silent
corruption. Recovery ranged from 17,945.719 to 20,264.118 ms.

## 25. Restart → Update → Conversation

250k restart, SUPERSEDING update, delta persistence, Query, and Conversation
passed. The old fact remained as superseded history; the new fact was current;
Query and Conversation returned only the new fact; stale derived evidence was
excluded and provenance was present.

## 26. Read-heavy

100k and 250k both passed. At 250k, 110 queries / 10 updates produced query
P50/P95/P99 0.071/0.106/0.134 ms and Conversation P50/P95/P99
481.286/978.168/999.117 ms.

## 27. Balanced

100k and 250k both passed. At 250k, 60 queries / 60 updates produced query
P50/P95/P99 0.081/0.101/0.135 ms, Conversation 472.132/956.978/970.402 ms,
and one compaction.

## 28. Write-heavy

100k and 250k both passed. At 250k, 10 queries / 110 updates produced query
P50/P95/P99 0.082/0.094/0.094 ms, Conversation 467.620/954.318/954.318 ms,
and three compactions.

## 29. Semantic Correctness

All scale, cold-start, compaction, mixed-workload, crash, and 250k restart-
update-Conversation semantic checks passed. No hidden or provider-dependent
correctness shortcut was used.

## 30. Retrieval P2

`RETRIEVAL_SCALING_P2_RETAINED`. Ambiguous candidate growth and the prior
250k P95 199.71 ms finding are unchanged; retrieval was not optimized here.

## 31. Adoption Gate

Scale, semantics, locality, checkpoint, compaction, crash recovery,
restart-update-Conversation, amortized maintenance, and disk amplification
passed. Cold-start improvement versus S0 failed, so
`SHOULD_V2_BECOME_DEFAULT_FOR_NEW_PACKS = NO`.

## 32. Default Adoption

Not executed. The uncommitted adoption draft was discarded after the cold-start
comparison was audited. V1 remains default; v2 remains explicit; existing v1
stores remain readable and are never auto-migrated.

## 33. Full Regression

Adoption regression is `NOT_RUN_NOT_APPLICABLE` because no default change was
committed. The frozen product source retains its prior full regression: 3,112
collected, 2,755 passed, 357 skipped, 0 failed, 0 errors. This iteration's
harness/persistence targeted suite passed 70/70, and compileall plus all five
architecture/completeness/receipt gates passed.

## 34. Final Readiness

`RESOURCE_GATE_STATUS = OVER_CONSERVATIVE_OLD_GATE_CONFIRMED` and
`PRODUCTION_V2_SCALE_QUALIFICATION = PASS_AT_250K`. Production default adoption
is not ready because `COLD_START = FAIL_S0_REGRESSION`.

## 35. Recommended Next Phase

Run a bounded cold-start optimization iteration focused on checkpoint
deserialization and index materialization. Do not change authority, checkpoint
correctness, crash safety, retrieval semantics, or the v1 default until the S0
baseline is beaten.

## 36. Autonomous Decisions

- Selected F: by highest absolute safety headroom.
- Added conservative structural estimation and kept percentage as a secondary guard.
- Kept evidence compact by excluding the in-memory pack from write receipts.
- Rejected default adoption after auditing the 250k S0 cold-start comparison.

## 37. Critical Decisions

None. The user-defined adoption gate determined the no-adoption result.

## 38. Remaining P0/P1/P2

- P0: none.
- P1: v2 checkpoint cold start is 21.485% slower than S0 at 250k.
- P2: ambiguous retrieval candidate growth remains retained for a later iteration.

## 39. Commits

- `6938fbc3fdae7d060965312001427e70a7058c4b` — `test: calibrate v2 resource gate and scale harness`
- `e602f54adc620e5c91c94cf5f457ef808a71a48e` — `fix: keep v2 scale evidence compact`
- evidence closure: recorded by the final canonical publication for this iteration

Formal evidence:
`D:/CGKN/.service_evidence/v2-resource-gate-scale-qualification-048/formal-final/productionization-report.json`
(`sha256:ff4eaf052d257ab9fd81337a322fb6d31f4ce5b4c315a47492c7fde5471e4252`).
