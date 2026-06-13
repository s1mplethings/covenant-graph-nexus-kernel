# Local Studio

Local Studio is a local management surface for conversations, active projects, revisions, rollback, and redelivery requests.

It is not a generator and it must not introduce a new formal generation path.

## CLI

The first implementation is `scripts/local_studio_cli.py`.

Supported commands include:

- `list-conversations`
- `show-conversation <conversation_id>`
- `new-project <conversation_id> "<request>"`
- `revise <conversation_id> "<change>"`
- `status <conversation_id>`
- `list-projects`
- `show-project <project_id>`
- `list-revisions <project_id>`
- `rollback <project_id> --rev <n>`
- `redeliver <conversation_id>`
- `execute-revision <conversation_id> <revision_manifest_path>`

All generation or revision requests go through `MainAgentManager`. The CLI does not call the legacy simulator, `generate_project.py`, or `run_local_pipeline.py` as a formal delivery route.

`revise` prepares revision state. `execute-revision` is the explicit Phase 2 execution command and requires host-provided provider, finalization, package, and public gate adapters. If those adapters are not supplied, the CLI reports a blocked request instead of silently choosing a legacy route.

## Data

Conversations live under `examples/local_studio/conversations/<conversation_id>/`.

Managed project state lives under `generated/managed_projects/<project_id>/` with `current`, `revisions`, `snapshots`, `manifests`, and `reports`.

## Delivery

Local Studio may show project status and references, but public delivery still depends on `local_packager`, `public_delivery_gate`, and `delivery_manifest`. A revision is promoted only after the public gate allows delivery.
