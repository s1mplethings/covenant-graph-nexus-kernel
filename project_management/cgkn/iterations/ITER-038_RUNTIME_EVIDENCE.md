# ITER-038 Runtime Evidence

Recorded: 2026-08-27T21:41:50+08:00

## Scope and authority boundary

This iteration repaired causal relationships inside the reviewed Provider generation mainline. It did not write or seal a generated candidate, add a generation path, change the Telegram default route, package output, or authorize formal delivery evidence. The `PASS` recorded for this iteration is support evidence for the CGKN code change only.

## Causal diagnosis and repair

1. Resume safety previously compared several partial identities in different places. The runtime now persists and validates one `resume_identity` binding the component contract, component specification, exact expanded file manifest, leaf work graph, target file, and target manifest entry. MCP diagnosis consumes the same identity and does not let superseded historical hashes invalidate a complete current checkpoint.
2. Timestamped design artifacts previously influenced the downstream component identity. Design research now exposes a semantic hash that excludes artifact-time metadata while retaining the full manifest hash for traceability.
3. Goal-derived paths and complexity enrichment could both claim architecture authority. A passing `GoalDrivenProjectPlan` is now canonical for goal-derived component paths; generic local applications receive explicit domain-model, repository, service, workflow, entry, and test workstreams instead of a duplicate fixed backend layout.
4. Split order was previously able to masquerade as an API dependency. Automatically expanded sibling leaves now inherit declared shared providers and are not chained merely by file order; dependency normalization reruns after expansion.
5. Small leaf payload size previously overrode interface complexity. Initial component-file generation now selects the configured interface-capable large model, while ordinary small component-generation payloads retain the nano route.
6. Remote connection closures and stale-history comparisons previously obscured the failure source. MCP diagnosis now classifies disconnect/reset/abort/SSL closure failures as Provider transport and reports a compatible exact checkpoint as identity-bound resumable work.
7. Advisory prose could accidentally create a code-symbol requirement. Only the exact phrase `required code symbol <Name>` is accepted.

## Verification evidence

- Python compilation passed for `run_local_pipeline_impl.py`, `design_research_agent.py`, `requirement_decision_lane.py`, and `cgkn_mcp_server.py`.
- Contract, requirement, planning, design, supervisor, MCP, transport, Provider-mainline, and complexity profiles: **465 passed, 2 skipped**. The two pytest skips are the file's environment-sensitive wrapper behavior; the three model-routing cases were rerun directly with `unittest` and all passed.
- Direct model-routing verification: **3 passed**.
- Total targeted passing checks: **468**.
- `git diff --check` found no whitespace errors; it emitted only existing LF-to-CRLF conversion warnings.
- Plugin validation passed.
- Plugin cachebuster advanced from `0.1.0+codex.20260827032813` to `0.1.0+codex.20260827133953`, and `codex plugin add cgkn@personal` completed successfully.
- Source/runtime-cache MCP server SHA-256 values are identical: `91B5006FAD4B528AB06060A8AA1E34E0A9BC8E8C2A57357C9964B2C253AE9A53`.

## Review conclusion

All ITER-038 acceptance criteria are covered by executable regression checks and plugin installation evidence. The repair preserves the Provider mainline and the local-packager delivery boundary. A newly opened Codex task is still the required pickup boundary for the refreshed plugin process.
