# Main Agent Manager

`scripts/main_agent_manager.py` is a lightweight coordinator. It classifies a user turn, updates conversation state, prepares revision workspaces, selects models through `model_policy`, and returns a response payload to the caller.

It is not a replacement for the provider generation route.

## Responsibilities

- Receive user input from Telegram, Local CLI, or a future Local UI.
- Load and update the local conversation schema.
- Classify new project, revision, status, review, repair, and rollback requests.
- Prepare revision manifests and workspaces.
- Select task models through `model_policy`.
- Keep delivery requirements attached to the formal route.

## Boundaries

`MainAgentManager` must not:

- Bypass provider output validation.
- Produce final zip delivery directly.
- Bypass `local_packager`.
- Bypass `public_delivery_gate`.
- Treat internal JSON, Markdown, logs, or manifests as public attachments.
- Use `backend_controls` as an execution queue.
- Reconnect the legacy simulator as a formal generation path.

## Domains

The programming domain owns generation, repair, QA, packaging, and public gate execution.

The history and change domain owns active project state, revision history, workspaces, snapshots, changed files, and rollback.

`MainAgentManager` coordinates those domains without merging them into one large implementation.
