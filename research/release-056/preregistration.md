# ITER-056 Preregistration

Date frozen: 2026-10-25

## Research questions

1. Does indexed evidence localization preserve answer quality while reducing retrieval and context-assembly cost relative to the semantically equivalent full-scan baseline?
2. Does localized context outperform or remain non-inferior to flat context on the frozen cross-domain holdout?
3. Does capability shortlisting preserve selection quality while reducing context relative to a full registry?
4. Does self-growth converge toward reuse/composition rather than linear registry growth over 500 deterministic tasks?
5. Which public benchmarks can be reproduced through unmodified official evaluators without importing their datasets or implementations into CGNK?

The hypotheses and thresholds are machine-readable in `hypotheses.json`. Formal outcomes must be reported even when negative.

## Frozen internal task sets

- Cross-domain holdout: 72 cases, 12 domains, 6 cases per domain; public packet hash `sha256:da664c538a8dd6e3e434f3ab3484b218246b217ac60c4e3893a26089e1e730af`; hidden evaluator hash `sha256:f056ff3bc306020d8224f73b310c59074639a49a52ec49a9b095efc294460a3b`.
- Model-capability suite: the 26-case source-defined suite in `scripts/run_cgnk_evaluation.py`; each R0/R1/R2 route is one logical call.
- Conversation structure suite: the 10-case source-defined C1/C2 suite.
- Knowledge scale suite: 10, 100, 1k, 10k, 100k, and 250k items; 500k is exploratory and is not a release threshold.
- Self-growth longevity: 500 deterministic tasks; the initial frozen 100-task stream supplies true gaps and later windows repeat reuse/composition/non-capability/critical cases with unique IDs.

Execution receives only public task packets. Expected terms, forbidden terms, expected abstention, expected route, and evaluator decisions are withheld from the model-facing packet.

## Baselines

- `B0_DIRECT_CHEAP`: DeepSeek cheap route, task-local public evidence only.
- `B1_DIRECT_STRONG`: Qwen strong route, task-local public evidence only.
- `B2_FLAT_CONTEXT_CHEAP`: DeepSeek cheap route, complete active holdout evidence corpus.
- `B3_CURRENT_CGNK_BASELINE`: DeepSeek cheap route, exact legacy full-scan localization.
- `B4_OPTIMIZED_CGNK_RC`: DeepSeek cheap route, canonical indexed localization.

All baseline calls use temperature 0, maximum 300 output tokens, 90-second configured timeout, 120-second outer deadline, identical answer schema, no logical retry, and the same official-price snapshot. B1 intentionally varies model strength; all other comparisons keep the model fixed.

## Ablations

- A0 Full RC = B4.
- A1 no knowledge localization = B2.
- A2 no capability shortlisting = full-registry context in the capability-routing scale profile.
- A3 no reuse/composition = G1/G2 controls from the existing self-growth benchmark.
- A4 summary-only evidence = S0 diagnostic in applicable evidence-fidelity cases; never a production route.
- A5 strong-everywhere = B1 and strong-model reference tracks.
- A6 no repair evidence enrichment = applicable only to project-repair cases; excluded from unrelated QA tasks.
- A7 no persistence optimization = stale/unindexed full-scan path, performance-only comparison.

An ablation is reported `NOT_APPLICABLE` rather than forced onto a task whose semantics do not contain that component.

## Public benchmarks

The pinned revisions and redistribution decisions are in `benchmark_manifest.json`. Official evaluators and task semantics are not modified. CRAG and TUA-Bench content is CC BY-NC 4.0 and will not be redistributed in this Apache-2.0 repository. LongMemEval-V2, BFCL, and SWE-bench Pro V2 remain external dependencies; only task IDs, adapter configuration, sanitized result metadata, and reproduction instructions may be committed.

Public tracks are executed only when their official environment is available. Docker-dependent tracks are `ENVIRONMENT_BLOCKED`, not model failures, when the Docker daemon or required image is unavailable. No leaderboard submission is authorized.

## Subsets

- CRAG: official public split if available; otherwise a deterministic task-ID subset sampled with seed 56025, stratified by official domain/category.
- LongMemEval-V2: official small public tier first; cases remain isolated.
- BFCL V4: official non-live AST simple/multiple/parallel/relevance categories first; agentic live tracks are separate.
- TUA-Bench: deterministic task-ID subset with seed 56025 only when official containers run.
- SWE-bench Pro V2: HARD-51 is the predeclared cost-bounded subset; the locked no-network protocol is mandatory.

No subset may be chosen after examining CGNK results. Any unavoidable deviation is a protocol deviation and excludes the result from confirmatory claims.

## Retry and exclusion policy

- One logical call per internal task.
- API Lab may make at most two transport attempts under its frozen policy.
- No semantic retry and no task restart for a reasoning/schema failure.
- A single restart is permitted only for a separately classified infrastructure failure (429, timeout, provider 5xx, container startup, image pull, or evaluator crash), and both attempts remain in the ledger.
- Missing token usage remains null with `UNKNOWN_AFTER_TRANSPORT_FAILURE`; it is never recorded as zero.
- Exclude only preregistered evaluator-invalid or environment-impossible cases. Report counts and IDs. Do not exclude task failures.

## Metrics

Primary internal metrics are success, grounded answer rate, correct abstention, unsupported-claim rate, context characters, input/output/total tokens, estimated cost, P50/P95 latency, retrieval candidate count, and failure class. Scale metrics include retrieval accuracy, result hash, candidate counts, build time, CPU, RSS, and context-assembly latency. Growth metrics include success by window, registry size, new capability rate, reuse, composition, gap precision/recall, zero-use and duplicate rates, median reuse count, proposals, tokens/task, and cost/task.

Public benchmark primary metrics are the official evaluator metrics. CGNK-only diagnostics never replace the official score.

## Statistics

- Binary paired outcomes: paired absolute difference, 95% paired bootstrap confidence interval with seed 56025 and 10,000 resamples; McNemar exact test when discordant counts permit.
- Continuous paired metrics: median, P50, P95, paired median/mean difference, 95% paired bootstrap interval; paired Wilcoxon is exploratory when available.
- Multiple confirmatory tests use Holm correction.
- Quality non-inferiority margin: -5 percentage points in task success.
- Results with fewer than 30 paired completed tasks are descriptive only.
- Provider/model nondeterminism and one-trial task execution preclude claims of broad statistical generality.

## Release gates

An optimization enters RC only if correctness improves or quality is non-inferior and a core resource metric materially improves. Public release additionally requires exact Apache-2.0 license text, provenance and dependency audit, secret/privacy/history scan, benchmark redistribution audit, clean-clone reproduction, full regression, current security/contribution/citation/architecture documentation, a claim ledger, an academic report, and zero P0 blockers.

The repository remains private until every gate passes. Any unresolved relicensing, provenance, historical secret/private-data, or important-asset-source concern yields `PUBLIC_RELEASE_BLOCKED_LICENSE_OR_PROVENANCE` before visibility mutation.

