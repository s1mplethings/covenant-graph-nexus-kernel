# ITER-045 Runtime Evidence

Evidence status: `PASS_WITH_LIMITS`

## Accepted design behavior

- GUI, interface, visual-redesign, and Telegram Mini App language freezes a `product_design` support state before generation.
- Telegram-origin interface work defaults to two complementary surfaces: Bot conversation for intake/confirmation and a mobile-first Mini App for repeated visual interaction.
- The frozen acceptance checks require one explicit action with typed input/output, a unified action contract, Telegram light/dark themes, safe-area and accessibility behavior, server-side `initData` validation, real screenshots, and a walkthrough recording.
- Media-only questions and short non-visual function requests do not acquire GUI scope. English words such as `build` do not accidentally match the interface term `ui`.
- Every generation entry remains blocked while Codex supervision or user design confirmation is pending, including an explicit request to start immediately.

## Codex supervision evidence

- The adapter emits a bounded, redacted, hashed `CGKNCodexCapabilityEscalation` into per-chat support storage and records the handoff in `agent_session`.
- The local Codex command is opt-in and runs with `exec --ephemeral --sandbox read-only` plus a strict output schema.
- A real local `codex.exe` smoke completed with `status=ready`, `workflow_state=ready`, 8 guidance items, and 8 acceptance checks.
- The sealed result retained `advisory_only=true`, `candidate_write_authorized=false`, `formal_evidence_authorized=false`, `package_authorized=false`, and `delivery_authorized=false`.
- The validated brief is projected only into whiteboard support state and remains `awaiting_user_confirmation` until the user explicitly approves the design.

## Telegram integration evidence

- `TelegramClient.send_message` adds an `打开操作面板` Web App button only for a valid HTTPS Mini App URL.
- Telegram `web_app_data` is normalized as one user message and re-enters the existing `handle_text` intake path.
- A validated Codex brief is passed only as advisory Provider context; Provider output validation, post-build finalization, `local_packager`, `public_delivery_gate`, and `delivery_manifest.json` remain the reviewed generation and delivery route.

## Verification evidence

- Test-marker contract plus default design-supervision profile: `7 passed, 1 skipped` in `0.56s`.
- Design-supervision profile with Telegram-marked boundary enabled: `7 passed` in `0.56s`.
- Full repository regression: `1436 passed, 396 skipped, 5 warnings` in `652.63s`; no failures.
- The first full run found only a missing Telegram profile marker on the new test file. The test was marked at the actual Web App runtime boundary, leaving pure offline design tests in the default profile; both profiles and the subsequent full regression passed.

## Evaluation limit

- No public HTTPS Mini App deployment URL was supplied during this iteration, so a live Telegram client launch, theme rendering on a real device, and the `web_app_data` round trip are `NOT_EVALUATED`.
- No generated candidate, package, or public delivery was authorized by Codex supervision. A future live acceptance must still use the unchanged Provider and `local_packager` route.
