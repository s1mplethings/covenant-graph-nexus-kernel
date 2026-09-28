import copy
import pathlib

from cgkn.compiler import ArtifactFlowCompiler


ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOW = "flow.artifact_driven_project_refactor@1"


def test_compiled_flow_exposes_component_refs() -> None:
    result = ArtifactFlowCompiler(ROOT).compile(FLOW)
    assert result["ok"], result["diagnostics"]
    assert result["compiled_bundle"]["node_component_refs"]["n_problem_analysis"] == "module.problem.analyze@1"


def test_component_port_type_mismatch_still_fails_at_compile_time() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref]["ports"]["input"]["snapshot"]["artifact_type"] = "artifact.raw_requirement@1"
    assert "CGKN_EDGE_TYPE_MISMATCH" in {item["code"] for item in compiler.compile(FLOW)["diagnostics"]}


def test_invalid_component_port_contract_is_a_compile_diagnostic() -> None:
    compiler = ArtifactFlowCompiler(ROOT)
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref]["ports"]["input"]["snapshot"]["artifact_type"] = "not-versioned"
    result = compiler.compile(FLOW)
    assert not result["ok"]
    assert "CGKN_MODULE_CONTRACT_INVALID" in {item["code"] for item in result["diagnostics"]}
