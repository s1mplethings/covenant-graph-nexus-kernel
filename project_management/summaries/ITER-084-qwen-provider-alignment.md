# ITER-084 — Qwen Provider alignment

- Backlog: `PB-063` remains `needs_rework` pending a fresh CGKN MCP process and a newly authorized smoke.
- Attune reference: `QWEN_API_KEY`, `QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`, `qwen3.7-flash`, Chat Completions, and `enable_thinking=false`.
- Original CGKN runtime: a different Windows User `CGKN_OPENAI_API_KEY`, the same base URL, and Responses API. The key differed from Attune's local Qwen key and belonged to a free-quota-exhausted account.
- Repair: shared `QWEN_API_KEY`/`QWEN_BASE_URL` now precede compatibility credentials; Alibaba Model Studio selects Chat Completions; explicit no-reasoning maps to `enable_thinking=false`; safe plugin diagnostics expose source name, host, model, and presence only.
- Local environment: the existing Attune values were projected into same-named Windows User variables without printing or persisting the credential in the repository.
- Zero-API evidence: 127 focused tests passed; management validation and Python compilation passed.
- Canonical publish: commit `907a59186fa60be19db104b0451dd430f2489b16` was pushed normally and fetched remote SHA matched.
- Sole smoke: the persistent MCP server had not reloaded the patched modules. Its diagnostic still reported `canonical_user`, `CGKN_OPENAI_BASE_URL(User)`, endpoint `/responses`, and HTTP 403 free-quota exhausted after one attempt.
- Fail-closed result: no provenance generation followed the failed smoke; no candidate or resume-safe assertion was created. Restart/reload the CGKN plugin process before any later explicitly authorized smoke.
