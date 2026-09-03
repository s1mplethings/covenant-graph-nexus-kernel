# Customer Status And Codex Delivery

The active Codex task is the only public interaction surface. Customer status
is rendered through `scripts/customer_status.py`; preview and final artifact
selection lives under `scripts/conversation_delivery/`.

- `candidate_review_sender.py` selects canonical review artifacts.
- `final_delivery_sender.py` exposes final artifacts only after the gate passes.
- `status_renderer.py` produces customer-safe status text.
- `retry_recovery.py` maps recoverable failures to continue/cancel choices.

These modules return text and absolute local artifact paths to the Codex app.
They contain no network listener or messaging transport. Internal manifests,
logs, and evidence remain internal unless the user explicitly requests them.
