# ITER-105 — Pass 6 latency drift closure

Pass 6 remains the active release pass; no Pass 7 was created. Formal evidence remains `NOT_EVALUATED` because a fresh post-fix 24-hour run has not executed.

The immutable Before run `soak-20261011T131459Z` was independently recomputed and retained as `FAIL / NEEDS_REWORK`: first-two-hour p95 `0.291447585` s, last-two-hour p95 `0.455973315` s, drift ratio `1.564512` against the unchanged `1.15` gate.

Root-cause work identified whole-run recursive telemetry as an O(total retained files) latency contributor. The fix accounts each completed project once during execution, retains required metrics, adds host evidence, and performs exact reconciliation after the workload. No ProviderJob, Provider route, packaging, acceptance, or delivery authority changed.

Twenty-four isolated scale profiles (0/2000/4000/8000 retained projects, recursive/incremental telemetry, three repetitions) completed with 100% accounting and independent acceptance. At 8,000 states, median p95 improved from `0.324730495` s to `0.294476375` s; incremental 8,000/fresh median-p95 ratio was `1.090108`. Legacy scale medians were non-monotonic, so host contention remains a bounded contributing limitation.

Provider-free regression passed `2615/2615` on the frozen Python 3.13 baseline with no failures, errors, or skips. The earlier ambient-Anaconda run failed only the external-pytest-plugin isolation guard and was retained.

Run `midterm-20261012T164559Z` then executed continuously for `14406.547276` seconds. First/last-two-hour p95 was `0.248736120` / `0.251742400` s (ratio `1.012086`), throughput was `0.099861` / `0.100139` per second, and all continuity, accounting, integrity, resource, and source-stability gates passed.

The post-fix 24-hour source gate now compares the prior regression identity structurally instead of trusting one aggregate hash. It classifies production, contract/schema, test, soak/telemetry, and evidence-only changes; incomplete historical tracked-file granularity fails closed into a current-snapshot full Provider-free regression. The final manifest records path, size, and SHA-256 for modified/untracked source, tests, contracts, config, and launcher support, and a secret-scanned source bundle retains the complete bytes of every existing manifest entry.

`FINAL_24H_SOURCE_IDENTITY.json` binds HEAD, branch, canonical worktree identity, relevant untracked hashes, Python, the telemetry implementation, soak runner/config, launchers, source bundle, and current full regression receipt. The new `START_PASS6_POSTFIX_24H.ps1`, `CHECK_PASS6_POSTFIX_24H.ps1`, and `VALIDATE_PASS6_POSTFIX_24H.ps1` fail closed on source/config/regression drift, leftover processes, reused run ids, missing raw evidence, accounting/integrity/resource gates, or final exact filesystem reconciliation.

The fresh 24-hour run was not started in the Codex session. Its status, Formal CGKN Evidence, and real-model evaluation remain `NOT_EVALUATED / INCOMPLETE`. Publishing, merging, tagging, releasing, deployment, Provider calls, packaging, and public delivery were not performed.
