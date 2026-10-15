# ITER-103 — Real workload and recovery stress

## Outcome

`completed_with_limits` / `PASS_WITH_LIMITS` for the declared Provider-free
engineering scope. Formal product evidence remains `NOT_EVALUATED`.

The existing ProviderJob scheduler and Agent Kit lifecycle were exercised with
real process termination, timeout termination, cancellation competition,
duplicate start callbacks, corrupt checkpoints, late results, and identity
drift. Three isolated short matrices covered 1, 5, 10, and 20 concurrent
projects with ProviderJob concurrency 1, 2, 4, and 8. The final 30-minute
fixed-arrival run completed and independently accepted all 1801 projects.

The stress harness itself exposed and retained three failed attempts: deferred
terminal collection distorted latency, retained Future objects leaked one
Windows handle per project, and synchronous disk traversal degraded resource
sampling cadence. Each received a negative regression before the final run.

The final Python 3.13.3 Provider-free regression machine-accounted 2606 tests
with zero failures, errors, or skips. This preserves the fourth-batch 2598-test
baseline and adds eight fifth-batch tests.

## Evidence

- `cgkn-function-stress-pass/pass5-real-workload-recovery/independent_acceptance.json`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/RECOVERY_AND_STEADY_STATE_REPORT.md`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/performance_curves.svg`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/steady-30m/`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/short-final/`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/full-final-py313/`
- `cgkn-function-stress-pass/pass5-real-workload-recovery/CGKN_PASS5_REDACTED_EVIDENCE.zip`

## Limits

No paid Provider or local-model generation was run. The 24-hour soak was not
run and remains `NOT_EVALUATED`. Engineering success cannot authorize formal
product acceptance, packaging, public delivery, repository publication, or
release.
