# Commercial Hardening Plan

CGNK is moving from internal beta toward a commercial release candidate by adding a Commercial Hardening Lane. This lane assesses release readiness; it does not replace the Telegram default generation route.

Release labels:

- Internal beta: local tests and candidate-first delivery controls exist, but provider quota, sandbox, multi-project regression, and product acceptance may be incomplete.
- Commercial trial: final truth bypasses are blocked, provider quota state is reported honestly, generated projects pass static sandbox checks, and users see recovery-oriented statuses.
- Commercial ready: provider is available, tests pass, sandbox and anti-fake checks pass, a formal project passes final delivery, product acceptance is commercially ready, and no critical warnings exist.

The lane is entered through `scripts/run_commercial_readiness.py` and writes `examples/test_results/commercial_readiness_report.json`.

Non-negotiable gates:

- Do not relax the final delivery gate.
- Do not fake screenshot, video, final zip, manifest, or PASS_FINAL.
- Do not use `candidate_diagnostic_bundle.zip` as final package.
- Do not let provider output create `final_project_bundle.zip` or `delivery_manifest.json`.
- Do not reconnect legacy simulator, fixed local generation, or raw `run_local_pipeline.py` as Telegram mainline.
