# Agent Rules

This repository is CGNK, not CTCP v2.

Agents must not introduce CTCP runtime code, copy the old support bot or monolithic orchestrator, add progress fallback paths, or recreate the Telegram flow.

Agents must not directly modify `FlowSpec` main graphs. Every graph change must be expressed as a `GraphEditProposal`, then previewed, compiled, and checked through diagnostics.

Agents must not weaken schemas, remove diagnostics to pass tests, or replace stable refs with stringly typed contracts. Artifact, module, flow, policy, and proposal refs must remain canonical, for example `artifact.goal@1`, `module.intent.expand@1`, `flow.project_generation@1`, and `policy.safe_project_refactor@1`.

Agents must not commit generated outputs, `final_output`, `project_output`, databases, SQLite files, delivery zips, or built project artifacts into this repository.

Every round must run the relevant tests before moving to the next phase and report changed files, commands run, test results, diagnostics added, whether CTCP code was copied, remaining risks, and the next phase recommendation.
