# MVP Decision Efficiency Benchmark

This benchmark answers one product question:

> Can CGKN complete the same real task with fewer high-capability Agent decision calls while preserving functional success?

## Compared modes

- `direct_agent`: the high-capability Agent handles the task without CGKN delegation.
- `cgkn_delegated`: the Agent builds/edits a CapabilityTree, CGKN compiles an ExecutionDAG, and bounded work is delegated to cheap or deterministic executors.

## Required controls

Both modes use the same visible goal, starting project snapshot, acceptance criteria, environment, time limit, and allowed tools. Hidden acceptance is evaluator-only. A repository, CI, or schema PASS cannot replace real functional acceptance.

## Required metrics

- functional_success;
- high_capability_agent_calls;
- cheap_executor_calls;
- deterministic_tool_calls;
- external_capability_calls;
- total input/output tokens when available;
- wall time;
- retries;
- affected-subgraph reruns;
- whole-project reruns;
- human interventions;
- final acceptance coverage.

## First MVP gate

The first benchmark contains one real vertical slice. CGKN passes only when:

1. both modes are evaluated against the same functional acceptance;
2. the CGKN result is functionally successful;
3. evaluator evidence is bound to the produced result/project state;
4. CGKN uses fewer high-capability Agent calls than the direct baseline;
5. at least one cheap model/API executor, one deterministic executor, and one external/search/tool capability are used;
6. any repair is limited to the affected node/subgraph.

Large benchmark catalogs, Fixed10, concurrency, latency, and soak are explicitly outside this first gate.
