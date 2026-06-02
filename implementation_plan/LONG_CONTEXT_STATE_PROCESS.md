# Long Context State Process

This process adds durable long-conversation and long-generation state without changing the current project-generation baseline.

## Artifacts

1. `artifact.conversation_turn@1` stores append-only user, agent, tool, and system turns.
2. `artifact.conversation_state@1` stores the compressed durable state used by later modules.
3. `artifact.decision_ledger@1` stores decisions, defaults, alternatives, and rationale.
4. `artifact.generation_checkpoint@1` stores resumable generation checkpoints.
5. `artifact.context_pack@1` stores bounded context for one active module or provider call.

## Modules

1. `module.conversation.reduce@1` reduces many turns into `conversation_state` and `decision_ledger`.
2. `module.context_pack.build@1` builds bounded context from state and checkpoint.
3. `module.generation_checkpoint.commit@1` commits resume checkpoints after key generation stages.

## Runtime Pattern

```text
append-turn
  -> reduce
  -> context-pack
  -> run active module
  -> checkpoint
  -> repeat
```

## Local Commands

```bash
python scripts/long_context_state.py append-turn --run-dir examples/runtime_runs/my-run --role user --content "Build a resumable generation flow"
python scripts/long_context_state.py reduce --run-dir examples/runtime_runs/my-run
python scripts/long_context_state.py checkpoint --run-dir examples/runtime_runs/my-run --stage project_generator --status running --completed-step intake
python scripts/long_context_state.py context-pack --run-dir examples/runtime_runs/my-run --active-module module.project.generator@1
```

The script is deterministic and local-first. Provider-based semantic compression can replace the reducer implementation later without changing the artifact or module contracts.
