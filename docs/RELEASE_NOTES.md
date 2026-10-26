# CGNK 0.2.0-rc.6 Research Preview

CGNK is a composable capability kernel for evidence-grounded agentic project
work. This candidate adds the preregistered ITER-060 project-complexity frontier
and architecture ablation; it does not change the default architecture.

## Complexity-frontier evaluation

- 24 formal generated-original Python project families covered eight project
  types and LOW, MEDIUM, and HIGH complexity tiers.
- Each family ran through Direct Cheap, Direct Cheap with flat state, Minimal
  CGNK, and Full CGNK using the same `deepseek-flash` route and frozen budgets.
- All 96 formal attempts were captured into the local Project Corpus; 92 passed
  and four failed. The four failures were the same HIGH family under every
  baseline, so no discordant replay was applicable.
- LOW and MEDIUM success were 100% for all routes. HIGH success was 87.5% for
  all routes. Direct Cheap had the lowest aggregate cost per success.
- Full CGNK, Minimal CGNK, DAG, state/evidence, and repair-orchestration benefit
  are `NEUTRAL` at the tested scale. Direct low-complexity benefit and the
  existence of a directional complexity frontier are `PROVEN_DIRECTIONALLY`.

## Architecture decision

The evidence supports a future simplification experiment: keep state/evidence
primitives and make full orchestration optional. It does not support enabling an
Architecture Router, Multi-Agent runtime, or a new authority in this release.
Capability reuse remains `INSUFFICIENT_EVIDENCE` and requires a separate
cross-family reuse study.

## Corpus and security boundary

The real Project Corpus remains local-only. The release includes aggregate
results, IDs, hashes, analysis, and the technical report, not generated project
contents or private evaluator packets. Current-tree and history compliance
audits passed with zero P0 findings. Projects are generated-original and use
the Python standard library; no third-party dataset is redistributed.

## Reproduction and limitations

See `docs/REPRODUCIBILITY.md` and `research/release-060/`. The sample is
directional rather than statistically conclusive, uses one qualified cheap
model, and does not establish benefit for capability reuse, public benchmarks,
Router admission, or Multi-Agent execution.

No PyPI package, container image, Zenodo record, arXiv submission, leaderboard
entry, complete corpus, or social announcement is published by this release.

## License and citation

CGNK-owned work is Apache-2.0. Third-party assets retain their own licenses; see
`docs/THIRD_PARTY_LICENSES.md`. Report vulnerabilities through `SECURITY.md`.
Citation metadata is in `CITATION.cff`.
