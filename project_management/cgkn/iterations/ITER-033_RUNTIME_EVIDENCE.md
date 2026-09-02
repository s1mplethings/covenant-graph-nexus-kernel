# ITER-033 runtime evidence

Date: 2026-08-22

## Increment delivered

- Added `benchmarks/orbit_360_workbench`, a standalone standard-library Python benchmark with Chinese vision and usage documentation.
- Default deterministic plan contains exactly 360 work units, width 35, and 11 dependency layers.
- Materialization emits 360 descriptors, 360 boundary receipts, a plan, and a fully bound interface registry.
- Execution validates descriptors, receipts, registry entries, dependencies, hashes, and deterministic result semantics.
- Resume reuses validated checkpoint results; targeted repair invalidates only the transitive downstream closure.
- The benchmark does not execute arbitrary commands or generated source and reports only `NOT_EVALUATED` support evidence.

## Automated evidence

Command: `python -m unittest discover -s tests -v` from `benchmarks/orbit_360_workbench`.

Result: 8 passed in 10.073 seconds.

Coverage includes exact ACFV-scale planning, exact downstream closure, a real 360-unit materialize/run/resume/repair cycle, CLI subprocess behavior, status, descriptor tamper rejection, boundary-receipt tamper rejection, and semantic checkpoint-result recomputation.

Command: `python -m pytest -q -p no:cacheprovider --run-profile-marked tests/test_generation_scale_ladder.py -k "acfv_reference or downstream_closure"`.

Result: 2 passed, 4 deselected in 35.04 seconds. This confirms the existing CGKN ACFV reference and downstream-closure benchmark remained intact.

Command: `python -m pytest -q -p no:cacheprovider tests/test_repository_hygiene.py tests/test_adaptive_project_management_context.py tests/test_kernel_contract.py`.

Result: 37 passed in 7.25 seconds. Repository hygiene, self-management context, and kernel-contract checks remained green.

## Fresh 360-unit CLI evidence

Workspace: `artifacts/orbit_360_workbench_20260822_final/workspace` (ignored, reproducible runtime output).

| Operation | Result | Elapsed |
|---|---:|---:|
| plan | 360 descriptors, 360 receipts | 1.223 s |
| first run | 360 executed, 0 reused | 3.355 s |
| resume | 0 executed, 360 reused | 0.462 s |
| repair `unit_008` by `+7` | 11 invalidated | 0.393 s |
| post-repair run | 11 executed, 349 reused | 0.488 s |
| final status | 360 valid checkpoint results | verified |

Final results SHA-256: `bced86536f9f6b6946a94e4ded9812281279e479b4e88c6be40d6854d5a31107`.

All emitted reports retained `formal_evidence_status=NOT_EVALUATED`. No Provider identity, canonical generated candidate, package, delivery manifest, or formal delivery PASS was created or claimed.

## Environment note

The shell printed a pre-existing non-blocking `conda-libmamba-solver` entry-point warning. Python commands, unit tests, ACFV benchmark tests, and all CLI scenarios completed successfully.
