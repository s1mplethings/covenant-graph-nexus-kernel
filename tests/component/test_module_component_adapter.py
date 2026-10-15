import json
import pathlib

import pytest

from cgkn.component import ModuleComponentAdapter


ROOT = pathlib.Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def test_real_module_contract_adapts_without_losing_identity_or_metadata() -> None:
    module = json.loads((ROOT / "specs/modules/problem_analyze.module.json").read_text(encoding="utf-8"))
    component = ModuleComponentAdapter(module)
    spec = component.spec
    assert spec.ref == "module.problem.analyze@1"
    assert spec.input_port("snapshot").artifact_type == "artifact.project_snapshot@1"
    assert spec.input_port("snapshot").projection == ("modules", "boundaries", "importantFiles", "knownRisks")
    assert spec.output_port("analysis").artifact_type == "artifact.problem_analysis@1"
    assert spec.effects["fs_read"] == () and spec.effects["network"] is False
    assert spec.metadata["implementation"]["entrypoint"] == module["implementation"]["entrypoint"]
    assert spec.metadata["context"]["maxChars"] == module["context"]["maxChars"]
    module["implementation"]["entrypoint"] = "mutated"
    assert component.spec.metadata["implementation"]["entrypoint"] != "mutated"


@pytest.mark.negative
def test_adapter_without_executor_fails_and_executor_receives_plain_copy() -> None:
    module = {"id": "module.x", "version": "1", "ports": {}}
    with pytest.raises(RuntimeError, match="no runtime executor"):
        ModuleComponentAdapter(module).execute(None, {})
    seen = {}
    adapter = ModuleComponentAdapter(module, lambda contract, _inputs, _context: seen.setdefault("contract", contract))
    assert adapter.execute(None, {}) == module
    assert isinstance(seen["contract"], dict)
