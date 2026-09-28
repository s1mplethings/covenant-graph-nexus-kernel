from cgkn.component import Component, ComponentResult, ExecutionContext, ModuleComponentAdapter


def test_module_adapter_satisfies_component_protocol_and_executes_injected_boundary() -> None:
    module = {"id":"module.x","version":"1","ports":{"input":{},"output":{}},"effects":{},"implementation":{"kind":"local_function"}}
    component = ModuleComponentAdapter(module, lambda contract, inputs, context: ComponentResult(metadata={"run": context.run_id}))
    assert isinstance(component, Component)
    result = component.execute(ExecutionContext("run1", {"id":"n"}, {}), {})
    assert result.metadata["run"] == "run1"
