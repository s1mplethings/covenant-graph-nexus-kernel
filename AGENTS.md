# CGKN Kernel Contract - Do Not Break

`CGKN` is the current formal project name. `CGNK` may remain only in historical filenames, legacy compatibility notes, or internal compatibility markers.

- `docs/01_contract_registry.md` is the authoritative formal artifact/status/schema registry.
- Formal evidence statuses are only `PASS`, `PASS_WITH_LIMITS`, `NOT_EVALUATED`, `BLOCKED`, `BLOCKED_PROVIDER`, `BLOCKED_LOCAL_MODEL`, `BLOCKED_ENVIRONMENT`, `NEEDS_REWORK`, and `FAIL`.
- Workflow states such as `queued`, `running`, `waiting_user_review`, `delivery_sending`, and `final_delivered` are not evidence statuses.
- Legacy status names may be interpreted only through `legacy/status_adapter.py`.

- You may modify generated project files.
- You may modify tests when explicitly asked.
- You may add approved skills only through reviewed changes.
- You must not replace the Codex conversation generation mainline.
- Codex conversation default generation must stay on the reviewed API/provider project generation route: provider output validation -> post-build finalization -> local_packager -> public_delivery_gate -> delivery_manifest.json.
- `pipeline_manifest` + `dynamic_pipeline_runner` are preserved as the support/experimental planning lane, not a second Codex conversation default public delivery route.
- You must preserve whiteboard + agent_session as shared communication.
- You must preserve local_packager as the only delivery exit.
- If you need to change kernel files, update docs/00_kernel_contract.md and tests/test_kernel_contract.py or the rule guard in the same commit.
- Prefer deleting or isolating legacy branches over adding more compatibility paths.
- Do not add a new formal generation path.
- If you add a fallback, record pipeline_fallback and test it.
- If a change increases user-visible internal jargon, reject it.
- Prefer moving legacy code into legacy/ over keeping it inside kernel files.
- codex_conversation.py must stay focused on Codex conversation intake, backend dialogue, generation confirmation, guarded public replies, and delivery handoff.
- Do not reconnect legacy simulator/run_local_pipeline/generate_project.py as Codex conversation mainline.
- Do not reintroduce fixed local pipeline generation.
- Do not expose legacy internal jargon to users.
- Move project/domain-specific generated-project compatibility patches into skills, adapters, or legacy modules instead of adding them to codex_conversation.py.
- `docs/14_codex_cgkn_runtime_supervision_baseline.md` is the normative runtime ownership baseline: CGKN is the independently running system, Codex conversation is a CGKN-owned interface, and Codex starts or attaches to CGKN and supervises declared checkpoints.
- Do not treat a new one-shot Codex process per Codex conversation message as the target architecture. Request-scoped Codex calls are bounded specialist or transitional adapters only.
- Persistent Codex supervision must resume an identity-bound supervisor thread, preserve CGKN as the long-running owner of Codex conversation/project state, and keep every Provider, evidence, packaging, and delivery authority boundary intact.
- Persistent Codex supervision is a sparse read-only False-Pass Auditor for high-value positive transitions only. Ordinary Provider work, retries, and test failures must not invoke Codex. Canonical audit actions route deterministically: project issues to Provider, evidence issues to canonical rechecking, and actual kernel issues to a separate allowlisted governed Codex repair.
- `ProviderJob` is the only project-work concurrency unit. Provider authors isolated PatchSets; CGKN deterministically enforces dependencies, ownership, concurrency, merge order, affected-only repair, and PASS reuse. CGKN must not repair customer-project behavior with domain-specific kernel code.
- Agents must not default to reimplementing a mature generic capability. When a capability is eligible, they must consume the canonical External Executor Discovery result before Agent Build. Agents and Providers may not assert a library's latest version, license, security, or maintenance state from memory, stars, or README reputation. They cannot upgrade canonical security or maintenance `REVIEW`, `BLOCK`, or `UNKNOWN` to PASS. Only license `ALLOW`, GitHub maintenance `PASS`, OSV security `PASS` for the same exact version, complete metadata, compatibility, and an isolated bounded trial PASS may become a selected executor.
- The production mainline must create one `project_decomposition_tree.json` before Provider generation. Plan, issue, repair, and evidence records reuse its node ids; an unmapped failure cannot create a generic Provider repair, and the tree never authorizes release.
- When the user asks to build a real project for use or testing, prefer the Usage Beta lane with `codex_surrogate` unless the user explicitly requests live Provider. Do not block Usage Beta solely because repository-global formal readiness is incomplete, and never bypass project-level Goal Fidelity, runtime, core capability, primary user path, or delivery gates.

## Canonical repository publish contract

- `scripts/canonical_repo_publish.py` is the sole repository staging, commit, normal-push, and remote-SHA verification authority.
- Every publish must bind a read-only SourceIdentity, explicit ChangeManifest, and current TestReceipt. Unknown, secret-like, runtime, generated, cache, log, temporary, screenshot, and local-state paths fail closed or are excluded; review-only durable evidence and migrations require explicit selection.
- Never use implicit bulk staging (`git add .`, `git add -A`), `git commit -a`, force push, automatic `git reset --hard`, automatic `git clean -fd`, or treat a zero push exit code as proof of publication. The fetched remote branch SHA must equal the committed SHA.
- `scripts/release_candidate_gate.py` evaluates release readiness only and must not regain independent file classification, staging, commit, push, or publish authority.
- Repository publication and CI are governance/control evidence only. They cannot authorize product acceptance, packaging, public delivery, or formal evidence PASS.

## CGKN self-hosted project management

- CGKN uses the approved `skills/manage-pmp-agile-quality` method for its own non-trivial development and exposes the same tailored method to generated projects.
- When the user asks Codex to operate above the context librarian, or a validated `CGKNCodexCapabilityEscalation` is present, use `skills/supervise-cgkn-capabilities`. Codex is an external advisory capability supervisor: consume the bounded librarian handoff, return a validated brief through `agent_session` and whiteboard support state, and never impersonate the Provider, write a sealed generated candidate, authorize formal evidence, package, or deliver.
- Tailor predictive, adaptive, or hybrid delivery from requirements uncertainty, technical uncertainty, criticality, and feedback needs; do not impose one fixed ceremony set.
- Preserve stable governance and delivery contracts while implementing the smallest useful vertical increment through an ordered backlog.
- Define measurable acceptance and quality metrics before implementation; build quality into each increment through prevention, assurance, control, and improvement.
- Read relevant bounded enterprise experience before planning and record evidence-backed usage outcomes after review.
- Keep `workflow_state` and `experience_state` separate from formal `EvidenceStatus`.
- Management packs, iterations, retrospectives, and experience records are support artifacts and cannot authorize formal delivery PASS.
- For non-trivial CGKN changes, update `project_management/current/active_iteration.json` and close it with test/review evidence. Summarize completed release-level history under `project_management/summaries/`; do not add an unbounded iteration archive back to HEAD.
