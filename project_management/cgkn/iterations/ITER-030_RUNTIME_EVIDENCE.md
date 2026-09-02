# ITER-030 Runtime Evidence

Date: 2026-08-21

## Delivered connection

- Repository skill: `skills/use-cgkn/`.
- Global Codex discovery path: `C:\Users\sunom\.agents\skills\use-cgkn`.
- The global path is a directory junction to the reviewed repository skill, so
  local updates do not create a second drifting copy.
- UI invocation: `$use-cgkn`; implicit invocation remains enabled for requests
  that specifically ask to use CGKN.
- The structure and the global junction both pass the bundled
  `skill-creator/scripts/quick_validate.py` validator.

## Direct Codex smoke

The active Codex task followed the skill against this isolated project:

```text
D:\CGKN\artifacts\use_cgkn_skill_smoke_20260821\sample project
```

Observed sequence:

1. `cgkn-agent init` created project-local non-secret support config.
2. `cgkn-agent doctor` found the reviewed Provider mainline.
3. `cgkn-agent prepare` produced request
   `codex-escalation-f243666b2a127cf0` with one bounded README excerpt and no
   secret input.
4. The active Codex task authored only `codex_draft.json`; it did not launch
   nested `codex exec` and did not write generated product source.
5. `cgkn-agent seal` produced a hash-valid ready
   `CGKNCodexCapabilityBrief` with brief SHA-256
   `a6dfa9d28feef6c706d32d2f7885a65fd29d408a48cdc360f934e9acc2502723`.
6. The deterministic whiteboard projection accepted that brief.
7. `cgkn-agent generate --allow-network --dry-run` constructed only the
   reviewed `scripts/run_local_pipeline.py --codex-capability-brief` command;
   no credential appeared in argv.

The desktop WindowsApps `codex.exe` remains inaccessible to direct PowerShell
launch, but the installed skill intentionally does not use that nested route.
The already-running Codex performs the advisory supervisor role directly.

## Regression evidence

```text
python -m pytest tests/test_use_cgkn_skill.py \
  tools/cgkn-agent-kit/tests/test_agent_kit.py \
  tests/test_codex_capability_supervisor.py \
  tests/test_kernel_contract.py -q

50 passed in 9.03s
```

The first skill-specific run exposed one wording assertion that did not
normalize Markdown line wrapping; the behavioral instructions were present.
The test was corrected to inspect normalized text and the complete profile then
passed.

## Boundaries verified

- The skill is advisory and cannot claim formal PASS.
- Provider remains the only generated-source author.
- No nested Codex, legacy generator, second planning authority, packager, or
  delivery exit is introduced.
- Credentials remain process-only and cannot be CLI arguments or project
  configuration.
- A live Provider generation was not run in this iteration because no
  process-only Provider credential was supplied; the existing reviewed command
  handoff was verified by dry-run.

Evidence status: `PASS_WITH_LIMITS`. Global skill installation, validation,
direct request-to-brief behavior, and regression tests pass. A newly started
Codex task or app restart may be needed for the UI skill list to re-enumerate
the newly installed personal skill, and live Provider generation remains
credential-dependent.
