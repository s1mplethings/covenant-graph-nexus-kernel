# ITER-MINIMAL-BLUEPRINT-MVP-20261019

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Base: `codex/task-gated-level3-closure-20261019` at `6076b83b75b2b7e7a6003f85543f657a366453fd`
- Phase A branch: `codex/minimal-blueprint-mvp-20261019`
- Phase A source closure: `b93ddbcce0d6cdb335178ef6a87994c854cf0042`
- Phase B: not created because the Phase A gate did not pass
- Force push: no
- Pull request: not created

## 2. Minimal Architecture

- `ProjectBlueprint` freezes goal, constraints, acceptance, units, checks, and a revision hash.
- `BlueprintUnit` owns cohesive file sets, declares reads and dependencies, and compiles through the existing `CapabilityTree`, `compile_tree`, and `DAGRunner` authorities.
- `UnitResult` and `FailureReport` are immutable, serializable, and hashable.
- Coordinator modes are limited to `DESIGN` and `REPAIR`; Workers receive only `FileBundle` or `PatchBundle` results.
- Deterministic scope, syntax, interface, test, and hidden-acceptance checks retain final authority.
- Production Python additions: two L6 adapter modules plus one unified CLI.

## 3. Phase A Real Generation

- Goal: stdlib CSV-cleaner CLI.
- Fixed budget: 8 Provider calls, 200,000 input tokens, 60,000 output tokens, estimated cost 5.0.
- Consumed: 7 planning calls, 11,098 reserved input tokens, 28,000 reserved output tokens, estimated cost 0.067098.
- Providers: two Qwen attempts timed out; one Grok attempt timed out; four DeepSeek attempts failed structured-output adaptation/validation.
- Blueprint: not produced.
- Agent decisions: 0 completed decisions.
- Worker calls: 0.
- Generated files and interfaces: none.
- Internal and hidden acceptance: not reached.
- Manual edits to the generated project: none.
- Final status: `BLOCKED_PROVIDER`.
- The eighth call was intentionally not consumed because one remaining call could not complete both design and execution.

## 4. Phase A Repair

- Not evaluated: real greenfield generation never produced a frozen Blueprint or project workspace.
- Fake repair proves same-Blueprint continuity, real pytest failure capture, owner/downstream invalidation, patch-only repair, rerun, and hidden acceptance.

## 5. Multi-Agent Architecture

- Not implemented. Phase B remains `BLOCKED_BY_PHASE_A` as required by the Phase A gate.

## 6. Standup

- Not evaluated; no Phase B artifacts were introduced.

## 7. Parallel Real Run

- Not evaluated; no Phase B branch was created.

## 8. Repeatability

- Not evaluated because Phase A real generation did not complete once.

## 9. Scope and Conflict Safety

- Focused tests cover duplicate ownership, unsafe paths, cycles, missing acceptance coverage, atomic edit rejection, frozen/hashable contracts, interface extraction, and breaking-interface rejection.
- Workers cannot modify the Blueprint and cannot write outside their owned file set.

## 10. Kernel Regression

- `product_direction_gate`: PASS.
- `kernel_architecture_gate`: FAIL on inherited reverse imports from `cgkn/agent/composer.py` and `cgkn/executors/llm.py` into `cgkn.application`.
- `kernel_completeness_gate`: FAIL because the inherited kernel source-bound receipt is stale.
- `verify_kernel_test_receipt`: PASS for its recorded older source boundary.
- Kernel profiles: boundary 309 passed/1 skipped; fault 80 passed; security 119 passed/1 skipped; local-functional 6 passed.
- Unit and full-core each report 439 passed, 2 failed, 1 skipped; both failures are the inherited architecture and receipt gates.
- Full pytest exited 1. Its immediate last-failed cache contained 15 nodes; 14 fail identically on the untouched base, while the remaining consumer-governance test passed when rerun alone.
- No reproducible regression attributable to the Phase A adapter was found, but the mandatory all-green Phase A gate is not satisfied.

## 11. Readiness

- `kernel_foundation`: retains the documented `COMPLETE` product status; a fresh all-green evidence closure is blocked by inherited gate failures.
- `minimal_blueprint_mvp`: `PARTIAL`.
- `multi_agent_readiness`: `MULTI_AGENT_LEVEL_0`.
- `functional_readiness`: unchanged.
- Remaining L6 scope: real Blueprint creation, real greenfield completion, real same-Blueprint repair, full Kernel gate closure, then and only then Phase B.

## 12. Remaining Blockers

- P0: API Lab must select the schema-valid structured answer rather than echoed schema/reasoning text; then a fresh bounded run is required.
- P1: inherited architecture and source-bound receipt failures must be closed in a separately authorized Kernel iteration.

## 13. Tests

- `python scripts/run_project_mvp.py --profile unit --json`: PASS, 10 passed.
- `python scripts/run_project_mvp.py --profile fake-single --json`: PASS, 1 passed/9 deselected.
- `python scripts/run_project_mvp.py --profile fake-repair --json`: PASS, 1 passed/9 deselected.
- `python -m pytest -q tests/test_canonical_repo_publish.py`: PASS, 41 passed.
- `python scripts/product_direction_gate.py`: PASS.
- `python -m compileall -q ...`: PASS.
- `python -m pytest --collect-only -q`: PASS, 2,830 collected.
- Mandatory Kernel and full-suite commands: FAIL as detailed in section 10.

## 14. Commits

- `b93ddbcce0d6cdb335178ef6a87994c854cf0042` — `feat: add minimal project blueprint mvp` — Phase A source closure, 13 files.
- Evidence closure: the commit containing this summary and the source-commit binding.
