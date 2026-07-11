# Customer Status And Telegram Delivery

`scripts/customer_status.py` translates internal state into user-facing status without exposing internal gate terms, tracebacks, or truth-module jargon.

Public statuses include queued, provider checking, generating, building, repairing tests, capturing screenshot, capturing video, ready for review, packaging final, final ready, waiting for provider quota, needs user decision, and failed with recovery options.

Telegram delivery is split into helper modules under `scripts/telegram_delivery/`:

- `telegram_candidate_review_sender.py`: sends candidate review artifacts only and may mark `candidate_review_sent` or `ask_user_review_sent`.
- `telegram_final_delivery_sender.py`: sends final delivery only after the final gate passes.
- `telegram_status_renderer.py`: renders public status through `customer_status.py`.
- `telegram_retry_recovery.py`: turns provider quota, transport, and delivery failures into retry/continue/cancel options.

Candidate review and final delivery must use different language. Candidate review must not mark `delivered`, `final_delivered`, `delivery_manifest_sent`, or `PASS_FINAL`. `PASS_FINAL` can be shown only after final delivery gate success.
