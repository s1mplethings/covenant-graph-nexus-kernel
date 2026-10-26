import pytest

from cgkn.component import Component, ComponentResult, ExecutionContext, ModuleComponentAdapter


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def test_module_adapter_satisfies_component_protocol_and_executes_injected_boundary() -> None:
    module = {"id":"module.x","version":"1","ports":{"input":{},"output":{}},"effects":{},"implementation":{"kind":"local_function"}}
    component = ModuleComponentAdapter(module, lambda contract, inputs, context: ComponentResult(metadata={"run": context.run_id}))
    assert isinstance(component, Component)
    result = component.execute(ExecutionContext("run1", {"id":"n"}, {}), {})
    assert result.metadata["run"] == "run1"


@pytest.mark.negative
def test_component_result_nested_values_are_immutable() -> None:
    source = {"out": {"items": [1]}}
    result = ComponentResult(output_contents=source, diagnostics=({"nested": {"x": 1}},), metadata={"values": [1]})
    source["out"]["items"].append(2)
    assert result.output_contents["out"]["items"] == (1,)
    with pytest.raises(TypeError):
        result.diagnostics[0]["nested"]["x"] = 2
