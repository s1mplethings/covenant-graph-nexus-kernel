# Long Context State Process

This process adds durable long-conversation and long-generation state to `flow.modular_project_generation@1`.

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

## Flow Integration

`flow.modular_project_generation@1` accepts `conversation_turn` alongside `goal`. The long-context nodes are part of the main graph:

1. `n_conversation_reduce` runs before the ordinary project generation lines.
2. `n_generation_checkpoint_commit` runs after project generation and effect reporting.
3. `n_context_pack_build` combines compressed state, local agent plan, and checkpoint.
4. `n_unified_control` remains the only final routing point for project outputs and long-context outputs.

## Runtime Pattern

```text
append-turn
  -> reduce
  -> run active module
  -> checkpoint
  -> context-pack
  -> unified-control
  -> repeat
```

## Local Commands

```bash
python scripts/long_context_state.py append-turn --run-dir examples/runtime_runs/my-run --role user --content "Build a resumable generation flow"
python scripts/long_context_state.py reduce --run-dir examples/runtime_runs/my-run
python scripts/long_context_state.py checkpoint --run-dir examples/runtime_runs/my-run --stage project_generator --status running --completed-step intake
python scripts/long_context_state.py context-pack --run-dir examples/runtime_runs/my-run --active-module module.project.generator@1 --purpose project_generation --prompt-max-chars 6000
```

`context-pack` emits both durable bounded context and prompt-ready fields:

1. `key_points` preserves high-signal intent, constraints, open questions, and checkpoint state.
2. `prompt_budget` records the requested max chars, actual prompt chars, rough token estimate, and shrink stage.
3. `prompt_quality` records whether required key-point types survived compression and whether the prompt fits the budget.
4. `prompt_text` is the local compressed prompt intended for one module step or provider call.

The script is deterministic and local-first. Provider-based semantic compression can replace the reducer implementation later without changing the artifact or module contracts.
