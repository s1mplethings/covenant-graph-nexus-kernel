# ITER-037 Runtime Evidence

## Outcome

CGKN's local MCP now exposes one deterministic, read-only failure diagnosis through `cgkn_diagnose_failure`. The same compact diagnosis is embedded in `cgkn_generate` and `cgkn_status`; MCP boundary errors also include a stable `failure` object.

The diagnosis separates:

- one primary failure with category, stage, component, target, error type, and bounded summary;
- Provider transport, local fallback rejection, Provider response parsing, and checkpoint identity drift as contributing failures;
- missing project files, absent candidate materialization, and unreached delivery as downstream effects;
- resume availability from resume safety.

It performs no generation, retry, packaging, or delivery action and always reports formal evidence `NOT_EVALUATED`.

## Real failure replay

The read-only MCP tool was run against:

`workspaces/kaoyan-408-companion-retest-20260826/.cgkn/agent-kit`

Observed result:

- generation status: `BLOCKED`;
- primary category: `provider_output_contract`;
- primary target: `backend/stages_part_01.py`;
- contributing categories: `provider_transport`, `local_model_output_contract`, `provider_response_parse`, `checkpoint_identity_drift`;
- downstream effects: `missing_required_artifacts`, `candidate_not_materialized`, `delivery_not_reached`;
- observed counts: 37 leaf failures, 10 Provider transport failures, and 10 local-model attempts;
- resume: available but unsafe because the recorded component specification identity drifted;
- recommended action: start a fresh reviewed generation run and do not auto-resume that checkpoint.

This reproduces the prior user-visible ambiguity and proves that the new contract identifies the internal root cause directly instead of presenting the missing files as the cause.

## Verification

- `python -m py_compile plugins/cgkn/scripts/cgkn_mcp_server.py` — PASS.
- `python -m pytest -q tests/test_cgkn_mcp_plugin.py tests/test_use_cgkn_skill.py tests/test_kernel_contract.py tests/test_adaptive_project_management_context.py tests/test_pmp_agile_quality_schemas.py tests/test_pmp_agile_quality_manager.py` — 67 passed.
- `quick_validate.py plugins/cgkn/skills/use-cgkn` — PASS.
- `validate_plugin.py plugins/cgkn` — PASS.
- Management project pack validation — PASS.
- `ITER-037.json` validation — PASS.
- `git diff --check` for the changed contract/plugin/test/iteration files — PASS (line-ending notices only).
- Plugin cachebuster updated to `0.1.0+codex.20260827032813` and `codex plugin add cgkn@personal` completed successfully.
- The installed MCP copy listed `cgkn_diagnose_failure` and replayed the real failure as `provider_output_contract`, `resume.safe=false`, formal evidence `NOT_EVALUATED`.

## Review

Accepted. The smallest useful vertical increment is complete: failures are machine-identifiable without changing the reviewed Provider generation route or formal evidence authority.

The approved quality experience was applied by keeping diagnostic support truth separate from formal delivery truth. The bounded phase-log tail prevents an unbounded MCP payload while preserving exact source-artifact references for deeper inspection.
