# CGNK 0.2.0-rc.2: A Governed Capability Kernel Research Preview

## 1. Abstract

CGNK is an agent architecture that separates project-level decisions from
bounded execution, localizes evidence before model reasoning, and records
state-changing work through typed contracts and receipts. This report evaluates
whether those mechanisms improve reliability or efficiency across a frozen
72-task, twelve-domain holdout. The optimized configuration achieved 48/72
(66.67%) success, statistically indistinguishable from the previous CGNK
configuration at 49/72 (68.06%), while reducing median context by 98.27% versus
a flat-context ablation. A direct cheap-model baseline achieved the best success
rate, 58/72 (80.56%). The evidence supports context localization, not a general
claim that CGNK improves task success. We release the system as a Research
Preview with negative results and environment blocks preserved.

## 2. Problem Statement

Agent systems commonly conflate project planning, tool selection, model calls,
state, and evidence. This makes failures broad, prompts large, and claims hard
to audit. CGNK tests whether a single Agent authority, compositional tree,
execution DAG, bounded executors, localized knowledge, and explicit receipts
can provide a more inspectable substrate.

## 3. Research Questions

The preregistered questions cover quality versus direct execution; context,
token, cost, and latency efficiency; knowledge localization; capability reuse;
evidence fidelity; bounded self-growth; architecture attribution; cross-domain
generalization; complexity cost; and release readiness. The complete wording is
preserved in `preregistration.md`.

## 4. Hypotheses

Seven frozen hypotheses test localized context, capability shortlisting,
search-before-create, raw evidence, cheap-first execution, whole-system
quality/cost frontier effects, and the possibility that some modules are
neutral or harmful. Results are not redefined after observation.

## 5. System Architecture

The canonical path is Agent → CapabilityTree → ExecutionDAG → Component/Block
→ Executor → Result/Test/Artifact → Project State → checkpoint. The Agent owns
intent and composition. Executors cannot become project planners. Tree and DAG,
state, and publication each have one authority. Application roles are views,
not mandatory stages.

## 6. Historical Compatibility: Original RAG/CTCP Parity

The historical parity audit found bottom-up and local retrieval, branch/path
convergence, abstraction navigation, raw drill-down, contradiction and
supersession, local invalidation, version history, query routing, growth, and
internalization implemented or superseded. No legacy idea was reintroduced
solely for parity. See `original_rag_ctcp_parity_audit.md`.

## 7. Architecture Audit

The audited tree contained 246 production Python files and 82,687 lines. It had
one known internal cyclic strongly connected component around knowledge
internalization, persistence, and store integration. No source was deleted
without deterministic reachability and compatibility evidence. Stable,
qualified, experimental, not-recommended, and compatibility surfaces are
separated in release documentation.

## 8. Optimization Method

Development profiling preceded changes. Each retained optimization required a
before measurement, hypothesis, implementation, after measurement, regression
result, and complexity assessment. Formal evaluation began only after source,
task manifest, model routes, budgets, seeds, and pricing were frozen.

## 9. Retrieval Optimization

Indexed/localized retrieval retained exact expected-evidence recall in the
development profiles while reducing p95 retrieval time by 80.09% at 100k nodes
and 76.90% at 250k nodes. The optimization preserves contradiction,
supersession, and raw-evidence traversal rather than ranking summaries alone.

## 10. Context Optimization

Context packing removes duplicate and non-actionable metadata after retrieval.
Development p95 context assembly improved by 99.985% at 100k nodes and 99.995%
at 250k nodes. The final prompt-boundary fix additionally excludes dependency
durations, usage counters, and receipt hashes while retaining modified paths,
interfaces, baseline state, and public test-authority facts.

## 11. Capability Search

The real ten-capability registry is too small to establish a production benefit.
Synthetic scale profiles show exact top-1/top-3 routing and substantial context
reduction, but remain synthetic evidence. The release label is
`NOT_YET_NEEDED_AT_CURRENT_SCALE`, not proven product benefit.

## 12. Persistence and State

Segmented persistence, checkpoints, compaction, compatibility migration, and
failure recovery retain one ProjectKnowledgePack and one run-state authority.
Persistence was not the dominant bottleneck after earlier work; retrieval
candidate growth and context construction were the development targets.

## 13. Self-Growth Longevity

A 500-task bounded simulation completed 500/500 tasks. The production registry
remained 10→10, while the experimental registry grew 10→25 with 15 admitted
capabilities. The final 100 tasks created no new capabilities; reuse plus
parameterization was 53%, composition 26.6%, precision and recall 100%, and no
duplicate/zero-use admissions were observed. This is controlled experimental
evidence, not authorization for unrestricted production self-modification.

## 14. Internal Holdout

The frozen holdout contains 72 tasks: six tasks in each of twelve domains,
stratified into 12 easy, 36 medium, and 24 hard cases. Executors see only public
packets; gold data is evaluator-only. Each baseline receives the same task
identity and one logical provider call. There are no manual task edits.

## 15. Baselines

B0 is direct cheap-model execution. B1 is direct strong-model execution. B2
supplies complete flat context to the cheap model. B3 is the previous CGNK
retrieval path. B4 is the optimized indexed CGNK path. B3/B4 use the same
DeepSeek route; B0/B2 use the same cheap route; B1 uses the frozen Qwen strong
route. The comparison is paired by case.

## 16. Main Results

| Baseline | Success | Tokens | Context p50 | Latency p50 | Known cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 Direct Cheap | 58/72 | 16,854 | 119 | 706.5 ms | $0.006833 |
| B1 Direct Strong | 46/72 | 29,782 known | 119 | 8,527 ms | null |
| B2 Flat Context Cheap | 15/72 | 164,071 | 6,861 | 757 ms | $0.007371 |
| B3 Current CGNK | 49/72 | 16,752 | 119 | 706 ms | $0.006731 |
| B4 Optimized CGNK | 48/72 | 16,716 | 119 | 873.5 ms | $0.006688 |

Unknown usage makes B1 cost null. Direct Cheap is the strongest result on this
holdout. B4 does not improve success over B3.

## 17. Statistical Analysis

B4 versus B2 improved paired success by 45.83 percentage points (95% bootstrap
interval 34.72 to 56.94 pp; exact McNemar p=2.33e-10) and reduced median context
by 98.27%. B4 versus B3 changed success by -1.39 pp (95% interval -4.17 to 0;
McNemar p=1.0). B1 versus B0 changed success by -16.67 pp (95% interval -29.17
to -4.17; McNemar p=0.0169), confounded by a timeout and frozen output-budget
exhaustion. Ten thousand paired bootstrap resamples used seed 56025.

## 18. Ablation Attribution

The B2 result establishes that sending all evidence is harmful here. B3/B4
shows the new index does not improve quality at this task scale, though
development profiling establishes latency scaling benefits. B0 shows that the
holdout often needs little architecture. Therefore gains cannot be attributed
to “CGNK overall”; the supported mechanism is localized context.

## 19. Quality/Cost Frontier

B0 dominates the tested configurations on observed success and known cost. B4
is cheaper than B3 by a small amount but one success lower. B2 consumes nearly
ten times the tokens and performs poorly. B1 has incomplete usage and cannot be
placed on a trustworthy cost frontier. No claim of an improved global Pareto
frontier is made.

## 20. Public Benchmark Preflight

Official revisions and licenses were frozen for CRAG, LongMemEval-V2, BFCL V4,
TUA-Bench, and SWE-bench Pro V2. CRAG required large LFS data beyond available
disk; LongMemEval-V2 required Python 3.11 and model/data endpoints; BFCL's
official environment targets Python 3.10; TUA-Bench and SWE-bench Pro V2 require
a Docker daemon unavailable on the host. These are `ENVIRONMENT_BLOCKED`.
Adapters and pinned revision resolution passed, but no substituted “formal”
public score is reported.

## 21. Failure Analysis

Dominant internal failures were required-answer abstention and term mismatch,
not schema or transport failures. B1 additionally had one transport timeout and
then exhausted its frozen aggregate output budget, leaving later usage unknown.
The release process itself found volatile execution metadata in downstream
project-worker prompts; stable projection fixed that independent framework bug.

## 22. Negative Results

Incremental materialization improves reliability but did not establish token
savings. Minimal Blueprint representation reduced serialized size but showed no
runtime prompt/call benefit. Blueprint and strong role-separation experiments
were directionally harmful for efficiency. Strong growth decisions were
harmful, adaptive hierarchy was neutral as a default, Multi-Agent Runtime is not
recommended, and summary-only evidence cannot preserve exact details.

## 23. Security and Privacy

Current and history compliance scans covered 7,726 historical blobs and found
zero P0 findings. P1/P2 matches were synthetic keys and local-path fixtures or
historical evidence paths. Hidden source was not exposed to providers, public
writes remain approval-required, and Postiz stays behind an independent
AGPL-3.0 service boundary. No credentials or raw restricted datasets are
included in release artifacts.

## 24. Licensing and Provenance

CGNK-owned source and documentation use Apache-2.0. Dependency, benchmark,
snippet, fixture, media, and service provenance were audited separately.
Postiz code is not imported. Public benchmark data is referenced by official
revision and reproduction instructions rather than redistributed.

## 25. Reproducibility

The clean-clone gate installed 0.2.0-rc.2 in a fresh virtual environment,
compiled source, passed the product direction gate and focused tests, and ran a
100-node release benchmark smoke with recall passing. Final regression was
3,001 passed and 363 skipped with zero failures/errors. All nine kernel profiles
passed or were explicitly environment-blocked for live-provider credentials.

## 26. Threats to Validity

The internal holdout is project-authored, each task has one provider execution,
provider nondeterminism is not estimated, and only two provider routes are
tested. Public formal benchmarks are environment-blocked. Frozen budgets hurt
B1 and prevent complete cost comparison. Development scale workloads are
synthetic and do not establish user-visible quality by themselves.

## 27. Release Status

Core substrate, knowledge localization, persistence, deterministic routing, and
repair evidence are release-qualified at their documented levels. Self-Growth,
Persona, Community, and Promotion remain bounded/experimental or approval-
required. Generalization and whole-system benefit are not yet proven. The
appropriate decision is `RELEASE_RESEARCH_PREVIEW`.

## 28. Future Work

Priority work is a reproducible Docker/Python benchmark environment, at least
two external benchmark families, repeated provider trials, and task sets where
project continuity is essential rather than incidental. Multi-Agent execution
should remain off until a current structure demonstrates a measurable benefit.

## 29. Conclusion

CGNK's clearest supported contribution is disciplined localization: it can
reduce irrelevant context by roughly 98% relative to flat evidence while
preserving far higher success. The optimized index is quality-non-inferior to
the previous CGNK path but not more successful. A direct cheap model remains
better on this holdout. The release is therefore useful as a reproducible,
governed research substrate—not evidence that added architecture always helps.
