# CGKN Kernel Contract - Do Not Break

`CGKN` is the current formal project name. `CGNK` may remain only in historical filenames, legacy compatibility notes, or internal compatibility markers.

- `docs/01_contract_registry.md` is the authoritative formal artifact/status/schema registry.
- Formal evidence statuses are only `PASS`, `PASS_WITH_LIMITS`, `NOT_EVALUATED`, `BLOCKED`, `BLOCKED_PROVIDER`, `BLOCKED_LOCAL_MODEL`, `BLOCKED_ENVIRONMENT`, `NEEDS_REWORK`, and `FAIL`.
- Workflow states such as `queued`, `running`, `waiting_user_review`, `delivery_sending`, and `final_delivered` are not evidence statuses.
- Legacy status names may be interpreted only through `legacy/status_adapter.py`.

- You may modify generated project files.
- You may modify tests when explicitly asked.
- You may add approved skills only through reviewed changes.
- You must not replace the Telegram generation mainline.
- Telegram default generation must stay on the reviewed API/provider project generation route: provider output validation -> post-build finalization -> local_packager -> public_delivery_gate -> delivery_manifest.json.
- `pipeline_manifest` + `dynamic_pipeline_runner` are preserved as the support/experimental planning lane, not a second Telegram default public delivery route.
- You must preserve whiteboard + agent_session as shared communication.
- You must preserve local_packager as the only delivery exit.
- If you need to change kernel files, update docs/00_kernel_contract.md and tests/test_kernel_contract.py or the rule guard in the same commit.
- Prefer deleting or isolating legacy branches over adding more compatibility paths.
- Do not add a new formal generation path.
- If you add a fallback, record pipeline_fallback and test it.
- If a change increases user-visible internal jargon, reject it.
- Prefer moving legacy code into legacy/ over keeping it inside kernel files.
- telegram_live_bridge.py must stay focused on Telegram intake, backend dialogue, generation confirmation, guarded public replies, and delivery handoff.
- Do not reconnect legacy simulator/run_local_pipeline/generate_project.py as Telegram mainline.
- Do not reintroduce fixed local pipeline generation.
- Do not expose legacy internal jargon to users.
- Move project/domain-specific generated-project compatibility patches into skills, adapters, or legacy modules instead of adding them to telegram_live_bridge.py.

## CGKN self-hosted project management

- CGKN uses the approved `skills/manage-pmp-agile-quality` method for its own non-trivial development and exposes the same tailored method to generated projects.
- Tailor predictive, adaptive, or hybrid delivery from requirements uncertainty, technical uncertainty, criticality, and feedback needs; do not impose one fixed ceremony set.
- Preserve stable governance and delivery contracts while implementing the smallest useful vertical increment through an ordered backlog.
- Define measurable acceptance and quality metrics before implementation; build quality into each increment through prevention, assurance, control, and improvement.
- Read relevant bounded enterprise experience before planning and record evidence-backed usage outcomes after review.
- Keep `workflow_state` and `experience_state` separate from formal `EvidenceStatus`.
- Management packs, iterations, retrospectives, and experience records are support artifacts and cannot authorize formal delivery PASS.
- For non-trivial CGKN changes, update or create an applicable iteration record under `project_management/cgkn/` and close it with test/review evidence. Tailor this to a short record for small fixes.
