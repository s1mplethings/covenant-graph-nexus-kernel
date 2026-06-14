# Project Revision Lane

The project revision lane lets CGNK continue work on an active project without treating every user change as a brand-new project.

It is not a second public delivery route. A successful revision must still use the reviewed provider generation route, post-build finalization, `local_packager`, `public_delivery_gate`, and a `delivery_manifest`.

## Phase 1 Scope

Phase 1 only prepares revision state.

This phase prepares revision state only.

It creates:

- revision request
- revision plan
- revision workspace
- revision manifest
- revision goal

It does not yet execute provider-backed revision generation.

## Phase 2 Execution Contract

Phase 2 adds provider-backed revision execution.

Revision execution is not a second public delivery route. It is a controlled revision entry into the same provider route and must still complete through `local_packager`, `public_delivery_gate`, and `delivery_manifest`.

The formal Phase 2 flow is:

```text
project_revision_request
-> run_provider_revision_job
-> post_build_finalize
-> local_packager
-> public_delivery_gate
-> mark_revision_success
-> deliver revN
```

Success requires:

- provider execution writes the revision workspace
- post-build finalization runs
- package exists
- delivery manifest exists
- `public_delivery_gate.delivery_allowed` is true
- `changed_files` is recorded or a warning explains why it could not be calculated

Revision `changed_files` excludes internal test environments, caches, package bundles, and delivery manifests so revision history remains human-readable.

Gate failure or provider failure must leave `current` unchanged.

## Active Project Rules

Each conversation may bind one `active_project` with:

- `project_id`
- `current_worktree`
- `latest_delivery_manifest`
- `latest_project_package`
- `revision_index`
- `latest_revision_manifest`
- `status`

Revision requests are allowed only when an active project exists. Explicit new-project wording wins over revision hints.

## Revision Manifest

Each revision writes a `ProjectRevisionManifest` that records:

- `previous_manifest_ref`
- `previous_package_ref`
- `previous_project_dir`
- `previous_revision_index`
- `revision_mode`
- `full_regenerate_reason`
- `revision_workspace`
- `changed_files`
- `package_path`
- `delivery_manifest`
- `public_delivery_gate`

`previous_manifest_ref` is required so a revision cannot silently lose the prior delivery context.

## Modes

`patch` is reserved for a future patch engine.

`controlled_regenerate` is the first supported mode. It creates a separate revision workspace and builds a constrained provider goal from the previous project context and the new user request.

`full_regenerate` must be explicit and must record why it was needed.

## Failure Rule

A failed revision must not promote its workspace to `current`, must not update the latest package, and must leave the previous active project intact. It records a failed manifest for later repair.

## Delivery Rule

README-only or docs-only output is not a successful revision. Public delivery must be a safe media/package artifact and must pass `public_delivery_gate`.
