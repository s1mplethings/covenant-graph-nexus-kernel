# CGNK MVP Scope

## Purpose

The MVP proves that one high-capability Agent can assemble and maintain a real project workflow from reusable capability blocks while bounded work is executed by cheaper or deterministic executors.

## MVP mainline

Goal -> Agent -> CapabilityTree -> ExecutionDAG -> Component/Block execution -> Result -> Test/Observation -> Project State -> Agent checkpoint

The L6 software-project slice projects this mainline as: Goal -> coordinating Agent DESIGN -> frozen minimal ProjectBlueprint -> cohesive units -> existing CapabilityTree/ExecutionDAG -> bounded workers and deterministic checks -> UnitResult/FailureReport -> affected-only repair. The blueprint is project truth; it is not a second execution graph or state authority.

## P0 required now

- one canonical capability/block input-output interface;
- tree composition with stable node identity;
- Tree-to-DAG compilation with dependency and cycle validation;
- replaceable executor assignment;
- bounded per-node task context;
- persistent project/run state;
- real test/tool execution;
- failure mapped to the smallest affected node/subgraph;
- Agent actions centered on composition changes and project-level decisions;
- one end-to-end project using at least one cheap model/API executor, one deterministic executor, and one external/search/tool capability.

## P1 after the substrate works

- project-management views and milestones;
- coding, testing, and research capability bundles;
- capability registry and reuse;
- library/API discovery and bounded trial;
- first self-growth exercise: learn and register one missing capability.

## P2 after P1

- release/publishing capabilities;
- promotion/content/media capabilities;
- social-platform connectors;
- team-role views such as PM, Developer, Tester, Researcher, Marketing.

## P3 only after repeated functional success

- adaptive executor/model routing;
- quality/cost learning;
- large DAG optimization;
- high concurrency;
- sustained-load and long-horizon reliability tests.

## Explicitly not MVP authorities

- fixed Requirement -> Product Design -> Technical Design -> Build -> QA -> Delivery sequences;
- mandatory virtual-team role chains;
- Provider-owned project planning;
- Fixed10 as a product-readiness gate;
- role-driven/autonomous validation ladders;
- stress, latency, or soak readiness before functional substrate success;
- multiple competing planners, schedulers, runtimes, or execution graphs.

## MVP benchmark

Compare the same real task with and without CGNK and record task success, high-capability Agent calls, cheap executor calls, deterministic tool calls, tokens when available, wall time, retries, affected-subgraph reruns, and final functional result.

The primary optimization target is fewer high-capability decision calls per successful task, not merely fewer tokens per API call.
