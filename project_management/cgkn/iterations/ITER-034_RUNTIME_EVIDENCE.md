# ITER-034 runtime evidence

## Scope and authority

The ProjectPulse candidate was generated and repaired only through the existing reviewed CGKN Provider route rooted at `artifacts/codex_cgkn_combined_real_test_20260822`. No ProjectPulse source or test was hand-authored into the candidate. API key-usage-limit responses were handled by the existing bounded Ollama fallback under the same leaf validation and post-build chain.

This record is support evidence for closing the CGKN development iteration. It is not formal delivery authority.

## Real candidate evidence

- Candidate: `artifacts/codex_cgkn_combined_real_test_20260822/.cgkn/agent-kit/generated-project_candidate`
- Phase log: `artifacts/codex_cgkn_combined_real_test_20260822/.cgkn/agent-kit/runs/provider_phase_log.jsonl`
- Final post-build receipt: `runs/artifacts/candidate_post_build_finalize.json` reports `status: pass` and `candidate_only: true`.
- Goal acceptance: `runs/artifacts/goal_acceptance.json` reports `PASS`, 15 acceptance behaviors, 15 mapped substantive tests, and real pytest return code 0.
- Candidate pytest: `15 passed`.
- Candidate `TEST_REPORT.md` reports `test_status: pass`, `candidate_only: true`, and `PROVIDER_TRANSPORT_BLOCKED` as the known limit.

The 15 behaviors cover CRUD, stable listing, summary, import/export, atomic persistence, corrupt storage, status filtering, duplicate identifiers, merge, replace, CLI exit codes, and module/console entry parity.

## Runtime and installation probes

A fresh end-to-end CLI probe produced these outcomes:

- add, complete, filtered list, summary, export, merge import, replace import, delete, and final summary returned 0;
- duplicate-ID merge and malformed JSON import returned 2;
- the persistence file SHA-256 stayed unchanged after both rejected imports;
- no `.tmp` sibling remained after successful atomic saves;
- delete returned a JSON Task mapping rather than failing serialization.

The latest candidate built `projectpulse-0.1.0-py3-none-any.whl` successfully with SHA-256 `e0a5e546c4e496bc6393fa7c51c0f55b8fbd52f82bb038e6c8e7571eed22d545`. A clean virtual environment installed that wheel without network dependencies. The installed `projectpulse` console entry completed add/delete with exit code 0, and `python -m projectpulse --data-file ... summary` returned exit code 0 and valid JSON.

The final README contains copyable commands with the required global `--data-file` position for CRUD, status filtering, export, merge and replace imports, plus both console and `python -m projectpulse` entry forms.

## CGKN regression evidence

- `tests/test_formal_provider_fallback.py`: 294 passed.
- `tests/test_goal_driven_dynamic_project_plan.py`: 15 passed.
- `tests/test_kernel_contract.py`: 31 passed.

The added guards cover explicit setuptools package discovery, runtime `None` placeholders, malformed-import error propagation, command-local Task serialization, exact bounded repair prompts, and executable README usage.

## Formal limit

Provider semantic review remained blocked by `PROVIDER_TRANSPORT_BLOCKED` after HTTP 403 key-usage-limit responses. The final generation result is therefore `ASK_USER_REVIEW`, `formal_delivery_authority` is false, and `final_delivery_allowed` is false. No `final_project_bundle.zip` or `delivery_manifest.json` exists. The official generated-project test tool also refused to run because no formal `generated-project` directory was recorded. No packaging or delivery gate was bypassed.

## Canonical credential plugin follow-up

After credential replacement succeeded with a live `pong` response, the restarted Codex task exposed no CGKN MCP tools. The source plugin manifest was found to forward only the compatibility variable `OPENAI_API_KEY`, which the reviewed credential replacer intentionally clears. The manifest now forwards `CGKN_OPENAI_API_KEY` and `CGKN_OPENAI_BASE_URL`, and the guarded generation entry accepts the canonical credential, the explicit process override, or the legacy compatibility variable without logging any value.

- `tests/test_cgkn_mcp_plugin.py`: 7 passed.
- `tests/test_kernel_contract.py`: 31 passed.
- Plugin validation: passed after cachebuster update to `0.1.0+codex.20260824004901`.
- Reinstall from the current managed process remained pending because Windows denied execution of the packaged `codex.exe`; the source change and regression evidence are complete, but a user-terminal `codex plugin add cgkn@personal` plus a new Codex task are required to load the updated MCP tools.
