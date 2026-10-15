# ORBIT-360 Test Plan

## Test layers

1. Plan contract: deterministic IDs, layers, dependencies, and self-hash.
2. Materialization: exact unit/receipt counts and registry binding.
3. Boundary validation: all receipts, registry entries, descriptor hashes, and dependencies are checked before execution.
4. Execution: dependency-respecting deterministic outputs and result hashes, including semantic result recomputation.
5. Resume: verified results are reused; invalid results are recomputed.
6. Repair: only the target's transitive downstream closure is invalidated.
7. CLI: plan, run, repair, and status work from a clean subprocess.
8. Scale runtime: the default 360-unit scenario completes within 30 seconds locally.

## Commands

```powershell
python -m unittest discover -s tests -v
python -m orbit360 plan --workspace workspace
python -m orbit360 run --workspace workspace --workers 8
python -m orbit360 run --workspace workspace --workers 8
python -m orbit360 repair --workspace workspace --target unit_008 --delta 1
python -m orbit360 run --workspace workspace --workers 8
python -m orbit360 status --workspace workspace
```

The test results are benchmark support evidence. They cannot replace canonical CGKN test, runtime, review, packaging, or delivery artifacts.
