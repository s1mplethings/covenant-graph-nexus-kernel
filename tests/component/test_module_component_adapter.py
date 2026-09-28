import json
import pathlib

from cgkn.component import ModuleComponentAdapter


ROOT = pathlib.Path(__file__).resolve().parents[2]


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
