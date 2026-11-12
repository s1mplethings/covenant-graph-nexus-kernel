# ITER-090 execution and lifecycle

This is engineering DEV, not a blind comparison or a release gate. No Direct run.
All Agent/worker phases share 80 Provider requests, 1,000,000 tokens, 3600 development
seconds and the authorization/continuous ledger. The old four-decision limit is
not used. Unknown paid outcomes retain their original reservation. One inference
transport retry total is allowed; it is separately reserved and billed.

Every capability node defaults to **30 seconds**. Set `config.timeout_seconds`
explicitly to request up to **120 seconds**, including `workspace.test@1`.
`pytest_args` are pytest CLI arguments; they do not change the executor timeout.
The installed pytest has no pytest-timeout plugin. In particular, `--timeout`
is not a substitute for the executor's `timeout_seconds` field.

Tool timeout destroys the entire development container and its child processes,
then recreates the same isolated mounts and policy. Saved `/workspace` persists;
process state, browser state and `/tmp` do not. No action is replayed. The Agent
must inspect effects and explicitly choose a retry. Backend recreation failure
is fail closed. Services must be backgrounded by the model with redirected output.

The Agent sees its own action summaries, the last six raw results, and complete
own-result references. Outputs above 12,000 characters in the compact interface
have a deterministic prefix/hash/reference; model-selected commands can read
specific ranges. No host business summaries are supplied. Worker read observations
are returned with completion, including when the final action list is empty.

`view_proxy.py` only displays one frozen-candidate inspection environment. It binds
loopback, forwards to that container's localhost application, and exposes no host
filesystem, Docker control or external URL endpoint. It is a viewer, not a model
execution tool or publication route. Stop its recorded PID to close the viewer.
