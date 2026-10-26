# CGNK Project Complexity Frontier: When Does Agent Architecture Start to Help?

## 1. Abstract

ITER-060 compares four architecture levels across 24 generated-original project families and 96 isolated attempts. Findings are directional and bound to the frozen route and corpus.

## 2. Motivation

Earlier task studies did not locate a stable point at which full orchestration became necessary. This study moves the unit of evaluation from isolated answers to evolving projects.

## 3. Previous Evidence

ITER-056 through ITER-059 motivated a project-first ablation and a write-only formal Project Corpus.

## 4. Research Questions

The preregistered questions cover success degradation, evidence/state value, DAG value, repair, restart, provenance, reuse, and the minimum necessary architecture.

## 5. Project Corpus

The analyzed corpus slice contains 24 families and 96 baseline attempts; complete local snapshots are not redistributed.

## 6. Complexity Definition

LOW, MEDIUM, and HIGH labels are accompanied by raw file, module, dependency, episode, state, version, repair, capability, and knowledge-source metrics.

## 7. Project Families

Project-type counts: {"CLI_FILE_TOOL": 12, "CONFIGURATION_MIGRATION_TOOL": 12, "DATA_PIPELINE": 12, "DOCUMENT_KNOWLEDGE_TOOL": 12, "LIBRARY_PACKAGE": 12, "LOCAL_SERVICE_BACKEND": 12, "LOG_DIAGNOSTIC_TOOL": 12, "MULTI_COMPONENT_AUTOMATION": 12}.

## 8. Experimental Design

Family-paired baselines run in isolated workspaces. Development and formal holdout families are disjoint and all outcomes are retained.

## 9. Baselines

B0 is Direct Cheap, B1 adds fair flat state, B2 adds minimal evidence/state/recovery structure, and B3 uses the frozen Blueprint plus current Tree/DAG runtime.

## 10. Direct Cheap

Aggregate: {"attempts": 24, "average_calls": 3.291667, "average_context_growth_chars": 9436.875, "average_cost_usd": 0.011334, "average_duration_ms": 27844.75, "average_failed_calls": 0, "average_input_chars": 38874.166667, "average_max_input_chars": 14429.75, "average_repair_calls": 0.083333, "average_tokens": 17735.583333, "cost_per_success_usd": 0.01182669, "success_rate": 0.958333, "successes": 23}.

## 11. Flat-State Direct

Aggregate: {"attempts": 24, "average_calls": 3.291667, "average_context_growth_chars": 9725.5, "average_cost_usd": 0.011663, "average_duration_ms": 27948.583333, "average_failed_calls": 0, "average_input_chars": 39703.291667, "average_max_input_chars": 14735.375, "average_repair_calls": 0.083333, "average_tokens": 18206.208333, "cost_per_success_usd": 0.01217045, "success_rate": 0.958333, "successes": 23}.

## 12. Minimal CGNK

Aggregate: {"attempts": 24, "average_calls": 3.333333, "average_context_growth_chars": 10461.625, "average_cost_usd": 0.011849, "average_duration_ms": 27876.625, "average_failed_calls": 0, "average_input_chars": 43052.291667, "average_max_input_chars": 15797.5, "average_repair_calls": 0.125, "average_tokens": 19201.166667, "cost_per_success_usd": 0.01236453, "success_rate": 0.958333, "successes": 23}.

## 13. Full CGNK

Aggregate: {"attempts": 24, "average_calls": 3.333333, "average_context_growth_chars": 10588.5, "average_cost_usd": 0.011951, "average_duration_ms": 28661.708333, "average_failed_calls": 0, "average_input_chars": 43595.791667, "average_max_input_chars": 16155.375, "average_repair_calls": 0.125, "average_tokens": 19481.75, "cost_per_success_usd": 0.01247087, "success_rate": 0.958333, "successes": 23}.

## 14. Fairness

Provider, expected model, temperature, schema foundation, evaluator, tool access, budgets, OS, and acceptance are shared. Architectural context is the intended treatment.

## 15. Low Complexity

Best/Pareto route set: B0_DIRECT_CHEAP. Full metrics are recorded in complexity_frontier.json.

## 16. Medium Complexity

Best/Pareto route set: B1_DIRECT_CHEAP_FLAT_STATE. Full metrics are recorded in complexity_frontier.json.

## 17. High Complexity

Best/Pareto route set: B0_DIRECT_CHEAP. Full metrics are recorded in complexity_frontier.json.

## 18. Project Type Results

Eight type-stratified matrices are recorded; no global route is inferred when type cells disagree.

## 19. Success

Status counts: {"FAIL": 4, "PASS": 92}.

## 20. Context Growth

Per-attempt input characters and maximum-minus-minimum context growth are reported alongside tokens, rather than treated as quality proxies.

## 21. Rework

Public-repair calls are counted as rework; failed calls remain cost-bearing when usage is reported.

## 22. Repair

Repair orchestration verdict: NEUTRAL.

## 23. State Errors

State-heavy episodes use real restart boundaries. Failures are classified at the public evaluator without hidden feedback.

## 24. Provenance

Provenance-sensitive families require deterministic version/checksum evidence and remain generated-original research artifacts.

## 25. Capability Reuse

Verdict: INSUFFICIENT_EVIDENCE; within-family repeated capability refs cannot establish cross-family reuse.

## 26. Cost

Cost uses the frozen official DeepSeek price snapshot and is reported per attempt and per successful attempt.

## 27. Latency

Wall time and Provider elapsed time are retained; infrastructure failures are not relabeled as task failures.

## 28. Discordant Cases

There are 0 family-level discordances requiring architecture-aware interpretation.

## 29. Provider Nondeterminism

Temperature zero does not imply deterministic sampling. Findings use paired families and do not overclaim statistical significance.

## 30. Complexity Frontier

Verdict: PROVEN_DIRECTIONALLY; map hash sha256:849577fb378b2f585defee71b2df492cd8ae8ac451425047a8d44efc140a3250.

## 31. Architecture Boundary

Router reopen evidence is YES and full orchestration status is NOT_NEEDED_AT_TESTED_SCALE.

## 32. Corpus Expansion

Diversity verdict: PROVEN. Complete source and failure snapshots stay local-only.

## 33. Failure Mining

Failure classes: {"WRONG_OUTPUT": 4}.

## 34. Modification Direction

Each recommendation maps observed evidence to retain, simplify, keep-optional, or separately study; ITER-060 performs no post-formal architecture rewrite.

## 35. Negative Results

Neutral, harmful, and not-needed findings are retained and reported with the same prominence as positive findings.

## 36. Threats to Validity

The study uses one cheap model route, generated-original Python projects, small cells, and bounded episodes; results may not generalize beyond the tested frontier.

## 37. Security / Leakage

Formal Corpus reads are disabled, hidden cases stay in private packets, project execution network is disabled, and absolute paths are redacted before Provider repair prompts.

## 38. Limitations

No strong-model reference, public benchmark, Multi-Agent, Router, or cross-family capability-reuse treatment is included.

## 39. Future Project Problem Benchmark

Future candidates target cross-family reuse, natural multi-round repair, longer restart chains, and public dependency-contract changes.

## 40. Conclusion

The evidence-bound next step follows claim ledger sha256:49695215bb4d0631d61fd78c575b252edf19b286c2d5162aec43552d9d945d2d; no production default is changed in this release.
