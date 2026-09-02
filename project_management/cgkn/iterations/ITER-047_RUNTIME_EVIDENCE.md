# ITER-047 Runtime Evidence

Evidence status: `PASS_WITH_LIMITS`

## Scope accepted

- Added a durable, hash-linked runtime supervision protocol for checkpoints, results, supervisor state, and Telegram service heartbeats.
- Added a host that starts or attaches to the existing Telegram bridge, launches the first Codex assessment read-only, and resumes the stored Codex thread for later checkpoints.
- Added an opt-in Telegram Provider-start gate. A blocked intake resumes only through the existing reviewed Provider generation route after a matching `observe` or `resume` result.
- Added startup, Provider-output, and Provider-failure checkpoints without adding a generation, packaging, or delivery route.
- Kept whiteboard plus `agent_session` support communication and `local_packager` as the only delivery exit.

## Authority and secret boundary

- Result actions are restricted to `observe`, `advise`, `repair_cgkn`, `request_user_decision`, `resume`, and `halt`.
- `repair_cgkn` currently enters `waiting_repair_executor`; the read-only assessor cannot mutate the repository.
- Candidate writing, formal evidence, packaging, and delivery authority are fixed to false in every checkpoint and result.
- Absolute, traversal, generated-candidate, artifact, runtime-state, and credential-bearing repair targets are rejected.
- The Telegram token was inherited from the environment. It was not included in the child command, checkpoint, result, state, or evidence output.

## Verification

- Protocol, host, Telegram gate, and kernel regression after final Windows launch fixes: `41 passed` in `7.37s`.
- Core supervision, kernel, Telegram, and backend regression before the final launch-only fixes: `66 passed` in `105.55s`.
- Full repository regression: `1444 passed, 396 skipped, 5 warnings` in `555.15s`; no failures. The warnings are existing duplicate-ZIP and `jsonschema.RefResolver` warnings.
- A separate real read-only Codex smoke processed two hash-linked checkpoints with the same thread `01a058a0-48a6-7351-b0d1-5fc0b99f5298` and advanced its cursor to 2.
- The detached production-shaped runtime then processed startup and reattachment checkpoints with the same thread `01a058bc-30c5-7891-9044-5b9dc30aa6a5`, advanced its cursor to 2, and left zero pending checkpoints.
- The live status showed the supervisor `ready`, Telegram service process alive, and a fresh `CGKNRuntimeServiceHeartbeat`.
- Both live results used action `observe`, set `advisory_only=true`, and kept candidate-write, formal-evidence, package, and delivery authority false.

## Defects found and corrected by real startup

- Windows decoded Codex JSONL through the local code page, which failed on UTF-8 output. The adapter now explicitly uses UTF-8 with bounded replacement handling, and the runner options are regression-tested.
- `os.kill(pid, 0)` raised WinError 87 on this Windows host. Process health now uses a read-only Windows process handle plus `GetExitCodeProcess`, including a regression for exited-but-still-referenced children.
- Launching the Telegram bridge by file path omitted the repository root from import resolution. The host now launches `python -m scripts.telegram_live_bridge` from the repository root, and the exact command shape is regression-tested.

## Evidence boundary

- `PASS_WITH_LIMITS` applies to the first persistent-supervision vertical increment: durable identity, real same-thread resume, process and heartbeat health, bounded result validation, Telegram checkpoints, and opt-in Provider gating.
- Automatic application of `repair_cgkn` is intentionally not implemented. It requires a separate governed executor with auditable diff, rollback, proportional regression, and resume receipt.
- This management evidence does not become formal generated-project evidence and cannot authorize Provider output, packaging, or public delivery.
