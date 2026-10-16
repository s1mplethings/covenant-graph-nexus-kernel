# ITER-011 — Obligation Oracle execution

- Public name: `ITER-OBLIGATION-ORACLE-011`; backlog: `PB-017`.
- Outcome: accepted with limits under stop condition B.
- Source Closure: `eabc9e5b04bc1408630c358137dc348aadfc69f1`; Kernel L0-L5 was not modified.
- Delivery: all 16 CSV obligations compile to deterministic Oracles across seven bounded kinds. Fake disagreement scenarios correctly route test defects to `WU-TESTS` and source defects to `WU-CORE`; unaffected WorkUnits are reused.
- Quality: targeted, Fast, full-core, active-repository (`2120 passed`, `350` environment/historical skips), and seeded live-repair evidence passed. Full initially caught an invalid management identifier and the first real run caught non-JSON materialization of immutable evidence; both were corrected before the final source freeze.
- Real Direct: PASS with qwen3.8-max, 3 calls, 26,558 tokens, 109,911 ms, 2 bounded repairs, and public pytest/Oracle/hidden acceptance all PASS.
- Real DAG: FAIL with qwen3.7-flash after exactly 2 `WU-TESTS` repairs, 5 calls, 19,196 tokens, 93,869 ms. `WU-CORE` and `WU-DOCS` were reused; all source, CLI, dependency, and documentation Oracles passed.
- Blocker: `TEST_IMPLEMENTATION_BLOCKER`. The generated public test asserted that preview must also emit the entire cleaned output to stdout; the canonical obligation requires a preview while still writing the output file. The Test Worker retained that invalid assertion through both repairs.
- Repeat: not authorized. No budget increase, model substitution, Oracle weakening, candidate edit, whole-project replan, A/B/C rerun, PR, or merge occurred.
