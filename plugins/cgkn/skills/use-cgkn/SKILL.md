---
name: use-cgkn
description: Use the installed CGKN plugin tools to plan, generate, test, or inspect a project from Codex.
---

# Use CGKN through the plugin

Use the `cgkn_*` MCP tools. Do not replace them with direct shell calls to CGKN scripts.

## Normal sequence

1. Call `cgkn_doctor` or `cgkn_status` for the target project.
2. Call `cgkn_init` when the project has no `.cgkn/agent-kit.json`.
3. Call `cgkn_prepare` with the user's goal and the concrete planning gap.
4. Draft a bounded advisory response from the returned request. Keep the Agent role advisory: do not claim Provider authority, formal evidence PASS, packaging, or delivery authority.
5. Call `cgkn_seal_brief` with that draft.
6. Call `cgkn_plan_generation` with an explicit `provider_mode` and show the reviewed route before execution when useful. Use `live` by default for compatibility. When the user requires zero real Provider calls and names Codex surrogate, use `codex_surrogate`; never add `allow_network` or live Provider flags. Use `deterministic_replay` only with response fixtures that existed before the run.
7. When Provider configuration or connectivity is uncertain and the user requested direct diagnosis, call `cgkn_probe_provider` with `RUN_PROVIDER_PROBE` before generation. Report its bounded diagnostic category and keep its formal evidence status `NOT_EVALUATED`.
8. Call `cgkn_generate` only when the user requested generation and supply its exact confirmation token. In `codex_surrogate` mode, `WAITING_SURROGATE_RESPONSE` is a safe pause: call `cgkn_surrogate_status`, read the canonical request and its bounded context reference, author only the requested Provider payload, and call `cgkn_submit_surrogate_response` with that job and attempt. Then call `cgkn_generate` again with the same goal and mode; it resumes the same run. Repeat until the ordinary verification and delivery gates finish.
9. Call `cgkn_test_generated` only when the user requested project tests and supply its exact confirmation token.
10. Call `cgkn_status` to report actual artifacts, test evidence, and blockers. When generation or status reports a failure, call `cgkn_diagnose_failure` and report its primary failure separately from contributing failures and downstream effects. Resume only when `resume.safe` is true; otherwise follow the returned next action. Artifact presence, diagnostic output, and workflow completion are not formal evidence PASS.

## Safety boundaries

- Never pass API keys or tokens as tool arguments. Provider credentials may only come from CGKN's configured environment resolver: the process override or canonical Windows User environment.
- A Provider probe may resolve the canonical Windows User-level `CGKN_OPENAI_API_KEY`, but it must not return, persist, or log the credential and cannot authorize generation or delivery.
- Never ask CGKN tools to start nested Codex sessions.
- Never edit a surrogate request, response, receipt, design artifact, or candidate directly. Submit Provider text only through `cgkn_submit_surrogate_response`; request identity and hashes are bound by the tool.
- A surrogate response has Provider authorship only inside the generated-project boundary. It cannot modify the CGKN kernel, Product Design Governance, frozen partial acceptance, maturity policy, proxy gate, evidence gate, or delivery authority.
- Never author or modify a sealed Provider candidate through these tools.
- Never bypass `local_packager`, the public delivery gate, or the reviewed Provider mainline.
- Treat Agent guidance as bounded support evidence, not delivery authorization.
