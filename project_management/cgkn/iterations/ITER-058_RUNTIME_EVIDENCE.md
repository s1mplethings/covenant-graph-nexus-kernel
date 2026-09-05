# ITER-058 Runtime Evidence

This benchmark and this support record cannot authorize a customer candidate,
formal evidence, package, delivery, or public PASS.

## Bound implementation

- Benchmark code is isolated under `benchmarks/project_generation_v1/` and
  invokes the existing `scripts/run_local_pipeline.py` facade only as a
  subprocess.
- The production invocation context contains only `user_goal`; the opaque
  production slot contains no case id, hidden acceptance, score, or fixture
  name.
- The evaluator imports no CGKN runtime, verdict, Provider, evidence, package,
  or delivery module. It accepts only external observations bound to the exact
  run id, case id, candidate tree hash, and an allowlisted black-box producer.
- Controlled repair is eligible only after the independent happy path passes.
  Its receipt must prove one recoverable fault, affected-only Provider recall,
  stale-evidence invalidation/re-emission, recovery, and re-evaluation.

## Verification

- Benchmark regression: 30 passed, covering the requested minimum 17 areas.
- Combined focused regression: 108 passed, 41 skipped, zero failed.
- Strict slim/routing rule guard: PASS, including one production ProviderJob
  scheduler and the reviewed Provider-validation/package/delivery route.
- Production contamination scan: PASS; no production script, agent, or skill
  contains fixed benchmark ids or fixture markers.

## Harness dry-run

- Bound repository: `8d7ba3ca21b4ee8cfec64655a738f4df28aa6322` on
  `codex/cgkn-codex-edition`.
- Run: `PGBV1_DRY_20260905_8D7BA3C`.
- CASE_01: external process, persisted output, malformed-row, summary/file,
  identity, and delivery-package probes PASS; benchmark result NOT_EVALUATED.
- CASE_03: external process, HTTP, fresh-process persistence, export, identity,
  and delivery-package probes PASS; benchmark result NOT_EVALUATED.
- All eight harness checks PASS. Provider calls: 0. Codex calls: 0. The dry
  fixtures produce no CGKN score or baseline.

## Provider readiness and live pilot

- The most recent bounded qwen3.8-max readiness request reached Alibaba Model
  Studio and returned HTTP 403 `PERMISSION_DENIED`: free quota exhausted.
- The fixed CASE_01/CASE_03/CASE_10 pilot run
  `PGBV1_PILOT_20260905_8D7BA3C` records three `BLOCKED_PROVIDER` results, zero
  `PROJECT_FAIL`, zero generation calls, and zero Codex calls. No full
  generation was started after the known non-retryable account blocker.
- No live baseline label was created. A first live pilot still requires restored
  Provider funds or free-tier-only mode disabled, plus real external evaluator
  and controlled-repair adapters for the generated technology.

## Experience usage

`EXP-CGKN-QUALITY-001` was applied: benchmark report truth remains separate
from production verdict, formal evidence, and delivery truth. The successful
harness isolation and registry guard are the usage outcome; Provider-dependent
project quality remains blocked rather than inferred.
