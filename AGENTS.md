# CGKN Kernel Contract - Do Not Break

`CGKN` is the current formal project name. `CGNK` may remain only in historical filenames, legacy compatibility notes, or internal compatibility markers.

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
