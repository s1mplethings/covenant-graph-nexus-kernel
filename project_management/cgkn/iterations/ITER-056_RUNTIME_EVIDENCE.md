# ITER-056 Runtime Evidence

This support record cannot authorize a customer candidate, package, delivery,
or formal public PASS.

## Preserved failure and isolation

- Preserved run `production-5f7461ae22b542b98656bf087953e41d`
  stopped at `frontend.leaf.002`, which owns `frontend/styles.css` and depends
  on `frontend.leaf.001`.
- Historical attempts lasted 92.101, 92.128, and 92.797 seconds. Historical
  telemetry retained three input hashes and prompt sizes but no request id,
  body size, response headers, body, or token usage.
- The closest reconstruction from the frozen plan, completed upstream files,
  interface receipts, and librarian context produced one 27,536-byte request
  body. Isolation A and B used the production client with retry disabled;
  isolation C used Python's standard-library HTTP client. All three used the
  same payload hash and timed out before response headers after approximately
  90 seconds.
- A small same-endpoint, same-model control request passed on its first attempt
  in 8.61 seconds. The bounded classification is request-dependent
  `PROVIDER_OR_MODEL_LATENCY`, not a CGKN transport defect.

## DAG and concurrency finding

- The production DAG contained 16 one-file jobs with actual wave widths
  `2, 6, 1, 1, 1, 4, 1`, a theoretical configured peak of 4, and an observed
  peak of 2.
- Six backend jobs were ready together. Their phase timestamps prove the DAG
  was wide enough for four workers, but a prior API timeout had been recorded
  as `pipeline_fallback` even though the API-only route made zero local-model
  calls. The scheduler interpreted that receipt as an actual local fallback
  and reduced subsequent batches to one worker.
- Fallback consideration, execution, and selection are now separate events.
  Only actual local fallback execution can select the local one-worker limit.
- Every job owned exactly one file. Four frontend symbol fragments plus a
  facade increased calls and dependency depth without increasing the realized
  peak, supporting `OVER_FRAGMENTED_PROVIDER_DAG`. Planner regrouping is
  deliberately deferred.

## Verification and limits

- Focused transport, routing, ProviderJob, and kernel contract tests pass.
- The slim rule guard passes.
- The original run was not resumed: the exact isolation payload still failed
  its bounded request, so Provider recovery for that leaf was not established.
  No resume Provider call, candidate, evidence, package, or delivery artifact
  was produced.
- No supervision, router, kernel authority, delivery gate, retry limit,
  timeout policy, ProviderJob planner, scheduler, or pipeline was changed.

## Experience usage

- Bounded enterprise-experience retrieval for Provider diagnostics returned no
  applicable approved item; no unrelated experience was injected.
