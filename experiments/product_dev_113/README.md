# ITER-113 engineering DEV infrastructure

This is an append-only continuation of ITER-090's own Source Cabinet candidate.
It is not Direct, a formal holdout, a new product generation authority, or a
second planner. AgentProjectLoop and DAGRunner remain canonical.

Evidence and authorization: `F:/CGKN-ITER-113/`. Paid stages used their exact
`packet-v1/freeze-v*.json` manifests and source archives. Final source v5 is
offline-only; do not silently reuse an older seal against changed files.

The user authorized a fresh available CNY 100, retaining historical CNY
87.98930 and all unknown reservations. This phase adopted 80 requests, one
million tokens including unknown upper bounds, and 3600 development seconds.
It ended at 65 requests / 959867 tokens because the next actual request's upper
bound could not fit. CNY 79.20282 remains; this does not reset the token bound.

## Boundaries and lifecycle

- All candidate file, command, interpreter, browser and test actions use the
  existing non-root, network-none, immutable media image boundary.
- `/input` is read-only; only this run's `/workspace` is writable. No host
  executors, Docker socket, personal connectors, private oracle or Corpus.
- Command/test default timeout is 30 seconds; explicit node
  `timeout_seconds` supports at most 120 seconds. The installed pytest does
  not provide `--timeout`. A timeout destroys processes and recreates the
  same isolated mounts, preserving workspace but not `/tmp` or sessions.
  Actions are never automatically replayed; backend failure is fail closed.
- Services must be explicitly backgrounded by the model with redirected logs.
- Observer gets an isolated disposable snapshot, at most 8 shared model calls,
  and no merge capability. Its reports are proxy claims linked to actual tool
  records, not final independent or human acceptance.
- API Lab resolves credentials. All three configured services use structured
  JSON action envelopes through Chat Completions here. Native tool-call IDs,
  Responses, vision inputs and provider-hosted tools are not used.
- Transport interception is process-global, so admission/transport/settlement
  are serialized under one lock. No live concurrency claim. Unknown requests
  retain their complete reservation; shared counters are not reset on switch.
- Raw results and model-authored PROJECT_STATE.md persist. No host semantic
  summarization. Model switches retain public goals, state and evidence.
- v5 tracks exact repeated observations against source/test/database hashes;
  different semantic expressions still require Agent judgement. It does not
  infer business root causes or invent repair plans.

## Verified local checks

```powershell
python -m pytest experiments/product_dev_113/test_acv.py experiments/product_dev_113/test_transport.py experiments/product_dev_090/test_feedback.py tests/agent/test_project_loop_boundaries.py tests/runtime/test_graph_commit.py -q -p no:cacheprovider
```

The fixed conformance scripts intentionally refuse to overwrite their evidence
directories. Prior raw failures and successive results are retained. See the
iteration report for a directly executable, zero-API-cost candidate review
command using a fresh directory.

No new paid continuation is authorized by running an old command: preserve the
same ledger and candidate, explicitly version any approved technical limit
change, freeze current source and public feedback, and keep held-out results
out of the developer's workspace. Do not repair business files from this host.
