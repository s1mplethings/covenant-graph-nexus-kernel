# Repair boundary freeze

The ProviderJob issue-level repair boundary is frozen at `FROZEN_PASS`.

## Frozen evidence

- Named boundary regressions: 7/7 PASS.
- Focused regression: 115 passed, 7 skipped.
- `component_wide_rollback = 0`.
- `generic_scope_calls = 0`.
- `accepted_without_target_issue_improvement = 0`.
- `scripts/provider_jobs.py` remains a pure contract and ownership helper.
- The existing production split-file leaf executor in
  `scripts/run_local_pipeline_impl.py` is the only ProviderJob execution path.
- Benchmark hashes remain:
  - `cases.json`: `1DBD6AAE9DBAC9FBCB0C321DAC6A07D6DA45D8B31605EACEA127C499149C0462`
  - `evaluator.py`: `227E330E8BA037DE38A163631E005D29F6AD6626B0AD46582604860707E95A18`

## Non-regression rules

Do not restore case-score gating for a single ProviderJob, roll back an accepted
job because a peer fails, widen an evidenced issue into generic component
repair, add another Provider scheduler, weaken the final release gate, or patch
a generated candidate by hand.

## Provider gate

Do not start live CASE01/CASE03 convergence while the bounded Provider
preflight reports HTTP 403, `FREE_QUOTA_EXHAUSTED`, or
`WAITING_FOR_PROVIDER_QUOTA`. These are Provider blockers, not project-repair
failures.

After quota or key recovery, run:

```text
python scripts/rerun_case01_case03_product_convergence.py --model qwen3.8-flash
```

The wrapper verifies the frozen benchmark hashes, performs the canonical live
Provider preflight, and only then invokes the existing benchmark runner for
fresh CASE01 and CASE03 runs. It writes
`fresh_convergence_report.json` under the generated convergence run directory.
