from __future__ import annotations

import copy
import json
import pathlib

import pytest

from cgkn.compiler.artifact_graph import ArtifactFlowCompiler, ArtifactGraph


ROOT = pathlib.Path(__file__).resolve().parents[2]
FLOW = "flow.artifact_driven_project_refactor@1"
pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.determinism]


def compiler_with_flow() -> tuple[ArtifactFlowCompiler, dict]:
    compiler = ArtifactFlowCompiler(ROOT)
    flow = copy.deepcopy(compiler.flows[FLOW])
    compiler.flows[FLOW] = flow
    return compiler, flow


def codes(result: dict) -> set[str]:
    return {item["code"] for item in result["diagnostics"]}


@pytest.mark.roundtrip
def test_valid_compile_graph_round_trip_hash_and_no_source_mutation() -> None:
    compiler, flow = compiler_with_flow(); before = copy.deepcopy(flow)
    first = compiler.compile(FLOW); second = compiler.compile(FLOW)
    assert first["ok"] and first["compiled_bundle"]["topological_order"] == second["compiled_bundle"]["topological_order"]
    assert first["compiled_bundle"]["graph_hash"] == second["compiled_bundle"]["graph_hash"]
    graph = first["graph"]
    assert ArtifactGraph.from_dict(graph.as_dict()) == graph
    assert compiler.flows[FLOW] == before
    first["compiled_bundle"]["normalized_flow"]["nodes"].clear()
    assert compiler.flows[FLOW] == before


@pytest.mark.negative
@pytest.mark.parametrize("mutation, expected", [
    (lambda flow: flow["nodes"].append(copy.deepcopy(flow["nodes"][0])), "CGKN_NODE_DUPLICATE"),
    (lambda flow: flow.update(nodes="bad"), "CGKN_NODES_INVALID"),
    (lambda flow: flow["nodes"][0].update(uses="module.unknown@1"), "CGKN_MODULE_NOT_FOUND"),
    (lambda flow: flow.update(edges="bad"), "CGKN_EDGES_INVALID"),
    (lambda flow: flow["edges"].append({"bad": True}), "CGKN_EDGE_INVALID"),
])
def test_malformed_duplicate_and_unknown_graphs_fail_closed(mutation, expected) -> None:
    compiler, flow = compiler_with_flow(); mutation(flow)
    result = compiler.compile(FLOW)
    assert not result["ok"] and expected in codes(result)


def test_disconnected_structural_node_is_valid_and_deterministic() -> None:
    compiler, flow = compiler_with_flow()
    flow["nodes"].append({"id": "documentation", "structural": True})
    result = compiler.compile(FLOW)
    assert result["ok"]
    assert "documentation" in result["compiled_bundle"]["topological_order"]
    assert "documentation" not in result["compiled_bundle"]["node_component_refs"]


@pytest.mark.negative
def test_artifact_graph_from_dict_rejects_extra_or_missing_shape() -> None:
    with pytest.raises(ValueError, match="malformed"):
        ArtifactGraph.from_dict({"flowRef": "x"})


@pytest.mark.negative
def test_unknown_flow_artifact_and_port_mapping_fail_closed() -> None:
    compiler, flow = compiler_with_flow()
    assert "CGKN_FLOW_NOT_FOUND" in codes(compiler.compile("flow.missing@1"))
    flow["inputs"]["raw_requirement"] = "artifact.missing@1"
    flow["edges"][0]["to"]["port"] = "missing"
    result = compiler.compile(FLOW)
    assert {"CGKN_ARTIFACT_TYPE_NOT_FOUND", "CGKN_PORT_NOT_FOUND"}.issubset(codes(result))


def test_descendants_are_deterministic_and_deduplicate_diamonds() -> None:
    graph = ArtifactGraph("f", {}, {"a": ("b", "c"), "b": ("d",), "c": ("d",), "d": ()}, {})
    assert graph.descendants("a") == ["b", "c", "d"]
    assert graph.descendants("missing") == []


@pytest.mark.negative
def test_missing_policy_invalid_contract_and_implementation_fail_closed() -> None:
    compiler, flow = compiler_with_flow()
    flow["policy_ref"] = "missing@1"
    module_ref = flow["nodes"][0]["uses"]
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref].pop("implementation", None)
    compiler.modules[module_ref]["ports"] = "bad"
    result = compiler.compile(FLOW)
    assert {"CGKN_POLICY_NOT_FOUND", "CGKN_MODULE_CONTRACT_INVALID"}.issubset(codes(result))
    compiler, flow = compiler_with_flow()
    module_ref = flow["nodes"][0]["uses"]
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    compiler.modules[module_ref].pop("implementation", None)
    assert "CGKN_RUNTIME_IMPLEMENTATION_MISSING" in codes(compiler.compile(FLOW))


@pytest.mark.negative
def test_unbound_multiple_producer_cycle_and_type_mismatch_fail_closed() -> None:
    compiler, flow = compiler_with_flow()
    target = {"node": "n_problem_analysis", "port": "snapshot"}
    edge = next(item for item in flow["edges"] if item.get("to") == target)
    flow["edges"].append(copy.deepcopy(edge))
    flow["edges"] = [item for item in flow["edges"] if item.get("to") != {"flow_output": "delivery_judgment"}]
    compiler.modules["module.problem.analyze@1"] = copy.deepcopy(compiler.modules["module.problem.analyze@1"])
    compiler.modules["module.problem.analyze@1"]["ports"]["input"]["snapshot"]["artifact_type"] = "artifact.raw_requirement@1"
    cycle_module = compiler.modules["module.problem.analyze@1"]
    cycle_module["ports"]["input"]["back"] = {"artifact_type": "artifact.architecture_decision@1", "required": True}
    flow["edges"].append({"from": {"node": "n_architecture", "port": "architecture"}, "to": {"node": "n_problem_analysis", "port": "back"}})
    result = compiler.compile(FLOW)
    assert {"CGKN_INPUT_MULTI_PRODUCER", "CGKN_OUTPUT_UNBOUND", "CGKN_EDGE_TYPE_MISMATCH", "CGKN_GRAPH_CYCLE"}.issubset(codes(result))


@pytest.mark.negative
def test_projection_context_provider_and_policy_rules_are_enforced() -> None:
    compiler, flow = compiler_with_flow()
    module_ref = "module.problem.analyze@1"
    compiler.modules[module_ref] = copy.deepcopy(compiler.modules[module_ref])
    module = compiler.modules[module_ref]
    module["ports"]["input"]["snapshot"]["projection"] = ["missing"]
    module["context"]["requiredArtifactPorts"] = ["unknown"]
    module["implementation"] = {"kind": "provider"}
    module["effects"].update({"provider_call": False, "network": True, "risk": 999, "fs_write": ["cgkn/secret.py"]})
    policy = compiler.policies[flow["policy_ref"]] = copy.deepcopy(compiler.policies[flow["policy_ref"]])
    policy["network"] = {"allowed": False}
    policy["provider"] = {"allowed": False}
    policy["risk"] = {"max_risk": 0}
    policy["fs"] = {"denied_write": ["cgkn/*"]}
    policy["effect_constraints"].append({"effect": "bad", "scope": "bad", "max": -1})
    found = codes(compiler.compile(FLOW))
    assert {"CGKN_PROJECTION_FIELD_INVALID", "CGKN_CONTEXT_PORT_INVALID", "CGKN_PROVIDER_EFFECT_UNDECLARED", "CGKN_POLICY_EFFECT_DENIED", "CGKN_POLICY_RISK_EXCEEDED", "CGKN_EFFECT_CONSTRAINT_INVALID", "CGKN_POLICY_WRITE_DENIED"}.issubset(found)


@pytest.mark.negative
@pytest.mark.parametrize("edge,expected", [
    ({"from": {"flow_input": "missing"}, "to": {"node": "n_requirement", "port": "requirement"}}, "CGKN_FLOW_INPUT_NOT_FOUND"),
    ({"from": {"node": "n_requirement", "port": "interpretation"}, "to": {"flow_output": "missing"}}, "CGKN_FLOW_OUTPUT_NOT_FOUND"),
    ({"from": {}, "to": {"node": "n_requirement", "port": "requirement"}}, "CGKN_ENDPOINT_INVALID"),
    ({"from": {"node": "missing", "port": "x"}, "to": {"flow_output": "delivery_judgment"}}, "CGKN_NODE_NOT_FOUND"),
])
def test_endpoint_failures_are_explicit(edge, expected) -> None:
    compiler, flow = compiler_with_flow(); flow["edges"].append(edge)
    assert expected in codes(compiler.compile(FLOW))


def test_backward_compatible_artifact_type_and_diagnostic_expected() -> None:
    compiler, _ = compiler_with_flow()
    compiler.registry.specs["artifact.a@1"] = {"compatibility": {"backward_compatible_with": ["artifact.b@1"]}}
    assert compiler._compatible("artifact.a@1", "artifact.b@1")
    assert not compiler._compatible("artifact.a@1", "artifact.c@1")
    assert compiler._diag("CGKN_X", "p", "a", expected="b")["expected"] == "b"
