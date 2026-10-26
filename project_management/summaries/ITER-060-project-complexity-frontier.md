# ITER-060 Project Complexity Frontier

Status: accepted with limits  
Source closure: `56cba0c04abb659f53eadef406c23388fd1cc891`

ITER-060 preregistered and executed a 24-family, 96-attempt architecture
ablation across eight generated-original Python project types and three
complexity tiers. The four baselines used one frozen `deepseek-flash` route,
identical public/hidden contracts, fixed budgets, and local Project Corpus
capture.

The formal result was 92/96 PASS. All four failures were the same HIGH-complexity
library family under every baseline. There were no discordant families, so the
preregistered key-discordant replay was not applicable. Every baseline achieved
23/24 overall, 8/8 LOW, 8/8 MEDIUM, and 7/8 HIGH.

Direct Cheap was the aggregate cost/token Pareto route. Full CGNK did not add a
success advantage and used roughly 8-10% more tokens/context than Direct Cheap
at this scale. The evidence therefore marks Full CGNK, Minimal CGNK, DAG,
state/evidence, and repair-orchestration benefit as neutral; Direct
low-complexity benefit and the complexity frontier are directional. Capability
reuse remains insufficiently tested.

The accepted next direction is an optional-orchestration simplification study,
not a default architecture change. Router and Multi-Agent admission remain
closed. The real corpus stays local-only; Git contains sanitized aggregate
evidence and reproduction metadata.

Regression: 3,065 passed, 364 skipped, 0 failed, 0 errors. Security, history,
license, provenance, and release-asset audits found zero P0 blockers.
