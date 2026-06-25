# CGKN Stale Test Update Report

## Scope

This report records stale integration-test expectations found while preserving Requirement Decision First and strict delivery truth.

## Updated Expectations

1. Telegram provider delivery fixture
   - Old expectation: a fake provider could return PASS without complete delivery evidence and still become ready delivery.
   - Updated handling: the fake provider fixture now produces runnable files, a dependency file, a smoke test, and a real screenshot artifact when the test expects completed delivery.
   - Reason: completed public delivery must pass the normal provider validation, post-build finalization, local packaging, public delivery gate, and manifest route.

2. Telegram backend trigger tests
   - Old expectation: generation confirmation started the historical agent-loop backend.
   - Updated handling: tests now assert the reviewed provider generation driver for the default Telegram route.
   - Reason: CGKN must not reconnect the historical fallback as the Telegram default generation path.

3. Completed project update flow
   - Old failure mode: a post-delivery change could auto-start generation immediately.
   - Updated handling: completed project updates wait for confirmation unless the user explicitly starts.
   - Reason: Requirement Decision First requires revision intent and scope to be confirmed before another implementation pass.

4. Pending decision confirmation
   - Old expectation: the decision path referenced the historical agent-loop backend.
   - Updated handling: the fake provider path is used, and the test asserts provider generation state.
   - Reason: tests should prove the current route instead of preserving an old route assumption.

## Gate Policy

- No final delivery gate was weakened.
- No fake PASS was reintroduced.
- Tests that need complete delivery must provide real zip/screenshot/run evidence through the existing packaging route.
- Tests that only check backend triggering may accept rework when delivery evidence is intentionally incomplete.

## Verification

- `python -m pytest tests/test_telegram_bridge_generation_e2e.py::TelegramBridgeGenerationE2ETests::test_generation_confirmation_runs_backend_and_delivers -q` passed.
- `python -m pytest tests/test_telegram_customer_bridge.py::TelegramCustomerBridgeTests::test_generation_confirmation_starts_backend_thread -q` passed.
- `python -m pytest tests/test_telegram_customer_bridge.py::TelegramCustomerBridgeTests::test_generation_confirmation_does_not_require_backend_control_command -q` passed.
- `python -m pytest tests/test_telegram_customer_bridge.py::TelegramCustomerBridgeTests::test_completed_project_update_waits_for_confirmation -q` passed.
- `python -m pytest tests/test_telegram_customer_bridge.py::TelegramCustomerBridgeTests::test_pending_decision_asks_one_question_and_pauses -q` passed.
