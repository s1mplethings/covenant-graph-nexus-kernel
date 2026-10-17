# ITER-DETERMINISTIC-CONTRACT-TESTS-012

The iteration completed under Stop Condition B. Contract Test Compilation is COMPLETE, while real DAG generation remains NEEDS_REWORK.

- Source Closure: `754c62052135f48a97c24b4ad7b64051caf977d9` (`9c80265dec0e460a3ac41a905430fd2ccf2eab76`).
- Baselines: `BASELINE-CONTRACT-TEST-001` and `BASELINE-CONTRACT-TEST-002`, both with `removed_guarantees=[]`.
- Verification: 86 targeted application tests passed; Phase 2 Fast Baseline passed; final Full Baseline passed with 2,129 active-repository tests, 350 historical/environment skips, zero failures, and zero errors; Kernel receipt stayed fresh.
- Compiler: 10 canonical tests were deterministically compiled from 10 Oracle specifications, with a stable plan, source, manifest, and fingerprint.
- Fake DAG: correct source passed; seeded fill defect routed to `WU-CORE`; mandatory Provider test calls remained zero.
- Real DAG: qwen3.7-flash, five observed Provider calls, 16,934 recorded tokens, 73,215 ms, two `WU-CORE` repair rounds, zero manual edits, zero whole replans, zero mandatory Provider test calls.
- Real failure: canonical pytest and Oracle agreed that the generated CLI rejected the required positional output argument because the source retained optional `-o/--output`. Classification: `SOURCE_IMPLEMENTATION_BLOCKER`.
- Repeat: not authorized. Direct was not rerun on the frozen source.
- Secondary findings: nested immutable evidence prevented final result JSON serialization, and the second successful source repair re-executed `WU-DOCS` instead of preserving strict affected-only Provider reuse.

No Provider budget, model, Oracle, hidden acceptance, or test authority was changed.
