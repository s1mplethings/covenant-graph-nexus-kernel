# Knowledge persistence and retrieval scaling benchmark

This provider-free benchmark measures the existing `ProjectKnowledgePack`
implementation through real filesystem writes, process-isolated cold loads,
index rebuilds, fixed correctness queries, and read/write workloads. It does
not alter production persistence or knowledge semantics.

Run the frozen baseline matrix with:

```powershell
python scripts/run_knowledge_persistence_scaling.py --profile baseline --try-250k --output-dir <evidence-dir>
```

The report records hashes for the corpus generator, corpus shapes, query set,
workload definition, persistence policy, retrieval policy, context policy,
and model configuration. The 250k run is admitted only when the 100k result
stays below the configured RAM, disk, and elapsed-time guards.

After the baseline proves a persistence-locality gap, compare reversible
research representations without modifying production:

```powershell
python scripts/run_knowledge_persistence_scaling.py --profile alternatives --output-dir <evidence-dir>
```

The candidates are a chunked physical representation of the same logical
authority, an append-only authority with a rebuildable checkpoint, and a
compact monolithic authority with a rebuildable sidecar.

Run guarded 1,000-operation mixed workloads after the alternatives matrix:

```powershell
python scripts/run_knowledge_persistence_scaling.py --profile workloads `
  --baseline-report <baseline-report.json> `
  --alternatives-report <alternatives-report.json> `
  --output-dir <evidence-dir>
```

Current monolithic combinations projected above the runtime guard are marked
resource-bound from measured P50 costs. The append-log research candidate runs
all three workload mixes at 10k, 50k, and 100k.
