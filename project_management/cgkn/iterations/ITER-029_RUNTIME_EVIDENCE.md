# ITER-029 Runtime Evidence

Date: 2026-08-20

## Increment

Implemented `tools/cgkn-agent-kit` as an independently installable Python 3.10+
companion package. Its `cgkn-agent` command can initialize support state in any
local project, build a bounded redacted escalation, use Codex as an optional
read-only advisory supervisor, seal manual or Codex drafts through CGKN's
existing supervisor contract, and invoke only the reviewed Provider generation
facade.

## Installation and package evidence

- Editable install: `cgkn-agent-kit 0.1.0` installed successfully.
- Installed entrypoint: `D:\anaconda\Scripts\cgkn-agent.exe`.
- Installed entrypoint probe: `cgkn-agent 0.1.0`.
- Clean wheel: `cgkn_agent_kit-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `b4bae3a3b99353184c599e9778c24aba82ae51a05976a106e43834acea3fbff3`.
- The final wheel installed into a separate temporary target and
  `python -m cgkn_agent_kit.cli --version` returned `cgkn-agent 0.1.0`.

## Automated tests

With third-party pytest plugin auto-loading disabled:

```text
python -m pytest tools/cgkn-agent-kit/tests/test_agent_kit.py \
  tests/test_codex_capability_supervisor.py \
  tests/test_kernel_contract.py \
  tests/test_run_local_pipeline_usage.py \
  tests/test_formal_provider_fallback.py -q

231 passed, 141 skipped in 14.54s
```

The skipped cases are conditionally skipped cases in the existing Provider test
profiles. There were no failed tests. A first run without disabling external
plugin auto-loading was interrupted by the host's broken `pytest-qt`/QtCore DLL;
the repository-controlled test profile itself then passed.

## Real cross-project smoke

The installed `cgkn-agent.exe` was executed against:

```text
D:\CGKN\artifacts\cgkn_agent_kit_smoke_20260820\sample project
```

The path intentionally contains a space. Results:

- `init`: created `.cgkn/agent-kit.json` and ignored runtime support directory.
- `doctor`: found the reviewed Provider mainline and reported no stored secrets.
- `prepare`: created a hashed `CGKNCodexCapabilityEscalation` using the actual
  deterministic supervisor.
- Secret containment: a temporary `.env` marker was absent from every `.cgkn`
  artifact; the temporary marker file was removed after the check.
- `generate --allow-network --dry-run`: produced exactly one invocation of
  `scripts/run_local_pipeline.py` with `--codex-capability-brief`, `--use-api`,
  `--allow-provider`, and `--allow-network`; the argv contained no credential.

## Known local limitation

The Microsoft Store Codex executable was discovered at the desktop app's
WindowsApps path, but Windows returned access denied for both `--version` and
`codex exec`. `doctor` therefore reports `ready_for_codex_automation=false`, and
`assist` exits visibly with code 2. It does not fall back to Provider or a local
model pretending to be Codex. The manual Agent draft plus `seal` workflow is
usable, and Provider generation remains usable with a process-only credential.

## Contract review

- Agent support artifacts remain advisory and `NOT_EVALUATED`.
- The Agent cannot author the generated candidate or authorize evidence,
  packaging, or delivery.
- API keys are neither accepted as command arguments nor written to config.
- Runtime support paths cannot escape `.cgkn`; project scans skip sensitive
  filenames, build trees, large/binary files, and symbolic links.
- Online research is explicit and is forwarded only to the existing Provider
  route.
- No Telegram mainline, packager, public gate, or delivery exit was added.

Evidence status: `PASS_WITH_LIMITS` because the reusable package, manual Agent
workflow, Provider command handoff, packaging, and tests pass, while automatic
Codex execution is blocked by the installed WindowsApps executable permission.
