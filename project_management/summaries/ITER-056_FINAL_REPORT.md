# ITER-056 Final Release Report

## 1. Executive Decision

`RELEASE_RESEARCH_PREVIEW`. This is not a production-readiness or SOTA claim.

## 2. Repository Identity

Repository: `s1mplethings/covenant-graph-nexus-kernel`; release branch:
`codex/cgnk-core-optimization-release-20261025`.

## 3. Source Closure

Source closure: `c495738556ac1ee288df232a2b372a8294968051`; source tree:
`e76a64286a260fbd1ea13c0117b765c98526634d`.

## 4. Evidence Base

Pre-publication evidence base: `2ad4c6508fd0ce2b4074770cd2b857925dc2ffd2`.

## 5. API Lab Dependency

Provider ingress is pinned to API Lab commit
`999dff096afe45f058fe67016aee28a73912d5d4`.

## 6. Product Authority

`PRODUCT_GOAL.md`, `MVP_SCOPE.md`, product invariants, and current architecture
remain authoritative.

## 7. Kernel Architecture

The Agent remains the project-level decision authority over CapabilityTree,
ExecutionDAG, bounded executors, evidence, state, and checkpoints.

## 8. Runtime Authority

No second planner, runtime, DAG, scheduler, state store, or delivery route was
introduced.

## 9. License Decision

CGKN-owned source and documentation are licensed under Apache-2.0.

## 10. License File

The repository contains the unmodified Apache License 2.0 text in `LICENSE`.

## 11. Metadata Coverage

License and project metadata are present in `pyproject.toml`, README, citation,
security, contribution, changelog, and package documentation.

## 12. Copyright Attribution

No unverifiable person, employer, university, or institution was invented.

## 13. Third-Party Audit

Third-party provenance is recorded separately; CGKN's license does not relicense
third-party work.

## 14. Postiz Boundary

Postiz remains an independent AGPL service/transport boundary. No Postiz
implementation code was imported.

## 15. Benchmark Redistribution

Restricted benchmark data is not redistributed. Only revisions, task metadata,
manifests, and reproduction instructions are committed.

## 16. Current-Tree Security Scan

The final current-tree audit passed with zero P0 findings. Remaining findings
are synthetic secret fixtures and explicit path-pattern tests.

## 17. History Security Scan

The history scan covered 7,726 blobs and found zero P0 findings under the
audited policy.

## 18. Privacy Scan

No release-blocking personal path or private content was found. Test fixtures
for path detection remain explicitly documented.

## 19. Secret Handling

Provider secrets, Authorization headers, raw responses, and machine-local
evidence roots are not committed.

## 20. Clean-Clone Reproduction

A fresh clone installed in an isolated virtual environment and passed compile,
product-direction, focused tests, and a 100-node release benchmark smoke.

## 21. Full Regression

Full pytest: 3,001 passed, 363 skipped, 0 failed, 0 errors.

## 22. Kernel Static Profile

PASS.

## 23. Kernel Unit Profile

PASS: 482 passed, 1 skipped.

## 24. Kernel Boundary Profile

PASS: 325 passed, 1 skipped.

## 25. Kernel Fault Profile

PASS: 80 passed.

## 26. Kernel Security Profile

PASS: 119 passed, 1 skipped.

## 27. Kernel Local-Functional Profile

PASS: 6 passed.

## 28. Kernel Full-Core Profile

PASS: 482 passed, 1 skipped.

## 29. Active-Repository Profile

PASS: 3,001 passed, 363 skipped.

## 30. Live-Provider Profile

`BLOCKED_ENVIRONMENT`: the optional OpenAI credential was absent. This is not
a code failure and is not used to claim provider coverage.

## 31. Evaluation Freeze

Prompts, schemas, routing, cases, budgets, hypotheses, and stop rules were
preregistered before formal execution.

## 32. Holdout Composition

The internal cross-domain holdout contains 72 frozen tasks per baseline.

## 33. B0 Direct Cheap

58/72 succeeded (80.56%); 16,854 total recorded tokens; cost $0.0068328.

## 34. B1 Direct Strong

46/72 succeeded (63.89%). Usage and cost remain partially unknown after a
provider timeout and frozen aggregate-output-budget exhaustion.

## 35. B2 Flat Context Cheap

15/72 succeeded (20.83%); median context 6,861 characters.

## 36. B3 Current CGKN

49/72 succeeded (68.06%); 16,752 total recorded tokens.

## 37. B4 Optimized CGKN

48/72 succeeded (66.67%); 16,716 total recorded tokens; cost $0.0066879.

## 38. Retrieval Claim

B4 versus B2 improved success by 45.83 percentage points and reduced median
context by 98.27% on the internal holdout.

## 39. Quality Non-Inferiority Claim

B4 versus B3 differed by -1.39 percentage points with a paired bootstrap 95%
interval of [-4.17pp, 0pp]. This is directional, not definitive proof.

## 40. Direct Execution Result

Direct Cheap was the strongest baseline. An overall CGKN superiority claim is
therefore prohibited.

## 41. Strong Route Result

The strong route was harmful under the frozen budget in this run; the result is
confounded by timeout and budget exhaustion and is retained as a negative result.

## 42. Blueprint Result

Blueprint benefit remains harmful directionally for efficiency in the retained
Tier-1 evidence.

## 43. Role Separation Result

Strong role separation remains harmful directionally under tested conditions.

## 44. Cheap Executor Result

The qualified cheap-executor path remains the supported bounded-worker choice.

## 45. Incremental Materialization

Incremental materialization improved reliability and staging isolation but did
not prove a token-cost benefit; the benefit verdict remains neutral.

## 46. Stable Prompt Projection

Downstream prompts now exclude volatile duration, usage, hashes, context counts,
and action results while retaining stable semantic dependency facts.

## 47. Knowledge and Retrieval

Knowledge and retrieval are core-qualified. Indexed search is retained as a
rebuildable optimization whose production benefit is not yet needed at current scale.

## 48. Repair

Same-blueprint bounded repair, interface guards, and affected-subgraph reuse are
qualified by retained evidence.

## 49. Persistence

Segmented persistence V2 and checkpoint-based cold start retain their qualified
status at the evaluated scale.

## 50. Self-Growth

Self-growth is experimental and directionally supported only within bounded
offline admission and longevity evidence; unrestricted kernel self-modification
is not enabled.

## 51. Persona

Persona remains experimental and directionally supported; it is not a new
authority layer.

## 52. Community

Community operations remain approval-bound and limited by environment and
external-service policy.

## 53. Promotion

Promotion remains draft-only/approval-bound. No social-media announcement is
authorized by this release.

## 54. Public Benchmarks

CRAG, LongMemEval-V2, BFCL V4, TUA-Bench, and SWE-bench Pro V2 formal scores are
environment-blocked. Generalization is not yet proven.

## 55. Statistical Scope

The formal study used one execution per frozen task. Results are directional;
no claim of statistical significance beyond the reported paired tests is made.

## 56. Claim Ledger

Supported, refuted, prohibited, and unevaluated claims are recorded in
`research/release-056/RELEASE_CLAIM_LEDGER.json`.

## 57. Academic Report

The technical report, failure appendix, references, result tables, statistics,
and reproduction guide are complete.

## 58. Remaining P1 Items

Public benchmark environments, incomplete B1 usage/cost, and independent public
generalization remain P1 research gaps. There are no release-blocking P0 items.

## 59. Publication Boundary

The authorized publication scope is GitHub repository visibility, a release tag,
and a GitHub Release. PyPI, Docker Hub, Zenodo, arXiv, leaderboards, and social
announcements remain unauthorized.

## 60. Final Verdict

Publish as `v0.2.0-rc.2` Research Preview only after canonical evidence
publication, final remote-SHA verification, and one final P0 license/security
check. Multi-Agent Runtime is not recommended for the next phase.
