# ITER-031 runtime evidence

## Outcome

`cgkn@personal` is installed and enabled as a Codex personal plugin. A fresh, read-only Codex CLI task discovered the `cgkn` MCP server and called `cgkn_status` exactly once for `D:\CGKN`. The MCP result reported `ok: true`, `initialized: false`, and formal evidence status `NOT_EVALUATED`.

The previous user-level standalone `use-cgkn` Skill junction was removed after that live MCP pickup succeeded. The plugin retains a small internal Skill only to teach Codex the guarded tool sequence.

## Verification

- Plugin validator: passed for `plugins/cgkn`.
- Plugin Skill quick validator: passed.
- Protocol and boundary profile: `6 passed` for `tests/test_cgkn_mcp_plugin.py`.
- Applicable regression profile: `54 passed` across the MCP plugin, capability supervisor, Agent Kit, and kernel contract tests.
- Live Codex integration: completed MCP call with `server=cgkn`, `tool=cgkn_status`, and no shell simulation.
- Personal marketplace status: `cgkn@personal  installed, enabled  0.1.0+codex.20260822054733`.

## Preserved limits

- No tool input schema accepts an API key or token.
- `cgkn_generate` requires `RUN_REVIEWED_PROVIDER`, a hash-valid ready brief, and `OPENAI_API_KEY` from the parent process environment.
- Generation delegates only to the existing `scripts/run_local_pipeline.py` Provider route.
- The MCP server does not call a packager, authorize formal evidence, or deliver artifacts.
- Generated-project tests use detected pytest/npm profiles only, accept no arbitrary command, and strip secret-like environment variables.
- This iteration did not repeat a credentialed Provider generation. That remains a real-runtime follow-up, not inferred PASS.
