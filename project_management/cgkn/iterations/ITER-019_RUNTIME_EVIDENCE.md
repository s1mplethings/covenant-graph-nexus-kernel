# ITER-019 Runtime Evidence

No credential value is recorded in this artifact.

## Formal Provider resume

- Persisted Provider smoke test: PASS on the first request in 2.297 seconds with TLS verification and `gpt-5.4-nano`.
- Same-run goal hash checks passed; the previously verified foundation checkpoint was reused and formal output remained isolated from `generated/cs2_demo_anomaly_lab_20260814`.
- The first resume generated and checkpointed backend, frontend, and tests components. Registered `pipeline_fallback` events recorded API HTTP 504 responses; the local code model completed some bounded leaves but failed several complex repairs.
- Docs generation blocked on the README expected-symbol contract. Candidate-only post-build repair remained `NEEDS_REWORK` after two attempts.
- A second same-run resume reused foundation, backend, frontend, and tests checkpoints and targeted docs. The resulting candidate still failed independent pytest with **49 failed and 42 passed**.
- Representative formal-candidate failures covered artifact-store payload boundaries, unknown information-state preservation, stage mapping shapes, orchestrator state propagation, report-object interfaces, and integration behavior.
- Formal result: `NEEDS_REWORK`; `project_dir` remained null, `final_delivery_allowed=false`, and no canonical bundle or delivery manifest was emitted.

Evidence:

- `artifacts/cs2_demo_anomaly_lab_20260814/provider_run/provider_phase_log.jsonl`
- `artifacts/cs2_demo_anomaly_lab_formal_20260814/provider_result.json`
- `artifacts/cs2_demo_anomaly_lab_formal_20260814/provider_result_resume2.json`
- `generated/cs2_demo_anomaly_lab_formal_20260814_candidate/TEST_REPORT.md`

## Working-project genuine online retest

- An isolated virtual environment installed declared dependencies: `demoparser2 0.41.4`, `py7zr 1.1.3`, pandas, requests, and pytest.
- Initial global pytest startup was blocked by an unrelated broken auto-loaded Qt plugin; isolated execution removed that environment contamination.
- Pre-repair working-project tests: **27 passed**.
- Fresh discovery and download selected public GitLab project `25039855`, repository `markus-wa/cs-demos-2`, MIT repository license metadata, default branch `master`, immutable commit `0b0f78a1811d4d5184b06b55f250b586a213895b`, and candidate `s2.7z`.
- Fresh LFS download: **267,908,114 bytes**, SHA-256 `af8227b333cdd881dc9ad49d19d936de04789069ef49b736cd3bf3e6bb37dd43`.
- `py7zr 1.1.3` exposed a multi-target extraction incompatibility on the final otherwise safe member. Single-member reproduction passed. The project now validates all archive members first and extracts each approved Demo through a fresh archive reader.
- Post-repair working-project tests: **28 passed in 1.07 seconds**.
- One bounded retry stopped on a 30-second GitLab read timeout. The next identical bounded retry completed without raising resource limits.
- Live result: `PASS_WITH_LIMITS`, 17 network requests, six candidates discovered, synthetic fallback disabled.
- Selected member: `s2/arsham_infernocs2_1stSept23.dem`.
- Parser proof: **369,414** tick/player rows, **39,949** unique ticks, **10** players, required positions and yaw/pitch present.
- Events: **2,764** raw `weapon_fire`, **2,189** attributable shots, **125** deaths, **17** round starts, and **17** round ends.
- All **369,414** information-state rows remained unknown; hidden-information-dependent signals stayed disabled.
- Every player remained `insufficient_corroboration`; accuracy is `NOT_EVALUATED`, automatic ban is false, and human review is required.
- Independent source/hash/size/parser/safety/truth assertions: PASS.

Evidence:

- `artifacts/cs2_demo_anomaly_lab_20260814/real_retest_20260814/report/analysis_report.json` (initial py7zr compatibility failure)
- `artifacts/cs2_demo_anomaly_lab_20260814/real_retest_20260814/report_retry_2/analysis_report.json`
- `artifacts/cs2_demo_anomaly_lab_20260814/real_retest_20260814/report_retry_2/analysis_report.html`
- `generated/cs2_demo_anomaly_lab_20260814/TEST_REPORT.md`

## Evidence conclusion

The existing working project genuinely finds and analyzes a current public example and is `PASS_WITH_LIMITS`. Formal Provider regeneration and canonical delivery remain `NEEDS_REWORK`; functional evidence cannot authorize formal delivery PASS.
