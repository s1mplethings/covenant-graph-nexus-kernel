# CGKN Agent Kit

`cgkn-agent` makes the existing Agent-assisted CGKN workflow usable from any
local project. It is a companion, not a second generator: an Agent produces a
bounded advisory brief, then CGKN's reviewed Provider route remains the only
source author and continues through its existing validation and delivery gates.

## Install for your own machine

From the CGKN checkout:

```powershell
py -m pip install --user -e D:\CGKN\tools\cgkn-agent-kit
```

For an isolated global command, use `pipx` when available:

```powershell
pipx install D:\CGKN\tools\cgkn-agent-kit
```

## Use in any project

```powershell
cd D:\work\my-project
cgkn-agent init --cgkn-root D:\CGKN
cgkn-agent doctor
cgkn-agent assist --goal "Build the requested project" --gap "Need architecture and acceptance guidance" --category planning_gap
```

The automatic Agent step uses `codex exec` with an ephemeral session, an
explicit read-only sandbox, and a strict JSON output schema. If Codex CLI is not
usable, create a draft with another Agent and seal it through the same contract:

```powershell
cgkn-agent prepare --goal "Build the requested project" --gap "Need architecture guidance" --category planning_gap
cgkn-agent seal --draft D:\work\agent-draft.json
```

To inspect the exact Provider invocation without spending tokens:

```powershell
cgkn-agent generate --goal "Build the requested project" --dry-run
```

To run generation with a process-only Provider credential and opt in to CGKN's
existing online research inputs:

```powershell
$env:OPENAI_API_KEY = Read-Host "Provider key"
cgkn-agent generate --goal "Build the requested project" --allow-network
Remove-Item Env:OPENAI_API_KEY
```

No command accepts an API key argument or writes a key to configuration. Runtime
support artifacts are placed under `.cgkn/agent-kit/`, which is ignored by the
generated local `.gitignore`. The small `.cgkn/agent-kit.json` file contains only
the local CGKN checkout path and non-secret workflow settings.

## Publish later

This directory has its own `pyproject.toml`, source package, schema, tests, and
README. It is distributed with CGKN under Apache-2.0. Splitting it into a
dedicated repository or publishing it to a package registry remains a separate
release decision.
