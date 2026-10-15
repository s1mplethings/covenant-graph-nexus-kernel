# Capability Tree MVP Architecture

## Composition

The Agent builds a capability tree incrementally. A structural node may group work without being executable. An executable node references one reusable capability/component.

The tree is not execution order.

## Execution

Explicit dependency edges compile executable tree nodes into a DAG. This separation preserves a readable compositional tree while allowing fan-out, fan-in, parallel work, and local reruns.

## Component boundary

Existing cgkn/component contracts are the canonical block boundary: ComponentSpec, PortSpec, ExecutionContext, ComponentResult, and ComponentExecution.

An executor adapter may call a cheap LLM, local model, Provider, search API, script, browser, test runner, or other implementation. The component boundary stays stable.

## Intended Agent actions

- add a capability node;
- connect or remove an execution dependency;
- replace a capability or executor;
- remove or replace a subtree;
- request execution;
- inspect results;
- finish or expand.

The Agent does not need to emit a long fixed PlanningProposal before every project.

## Migration

Existing WorkNode/ProviderJob and formal-delivery systems are compatibility sources. Migration adapts useful capabilities into Blocks instead of extending the old fixed project-generation route. Production code is retired only after callers are proven gone.