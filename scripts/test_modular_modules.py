#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

import requirement_blueprint

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOW_REF = "flow.modular_project_generation@1"
FLOW_PATH = ROOT / "examples" / "flows" / "modular_project_generation.flow.json"
RESULT_PATH = ROOT / "examples" / "test_results" / "modular_project_generation_module_test_result.json"
RUN_DIR = ROOT / "examples" / "runtime_runs" / "modular-project-generation-smoke"


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ref(doc: dict[str, Any]) -> str:
    return f"{doc['id']}@{doc['version']}"


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def _simulate(module_ref: str, inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    goal_text = inputs.get("goal", {}).get("payload", {}).get("text", "生成一个本地任务看板项目")
    request = inputs.get("request", {}).get("payload", {})
    candidates = inputs.get("candidates", {}).get("payload", {})
    agent_plan = inputs.get("agent_plan", {}).get("payload", {})
    blueprint = inputs.get("project_blueprint", {}).get("payload", {})
    trace = inputs.get("generation_trace", {}).get("payload", {})
    test_graph = inputs.get("test_graph", {}).get("payload", {})

    if module_ref == "module.customer.service@1":
        return {
            "request": _artifact(
                "CustomerRequest",
                {
                    "intent": goal_text,
                    "constraints": ["local-first", "typed-module-boundaries", "test-graph-required"],
                    "acceptance": ["project_blueprint", "generation_trace", "test_graph", "effect_report"],
                },
            )
        }
    if module_ref == "module.requirement_blueprint.generator@1":
        return {
            "requirement_blueprint": requirement_blueprint.build_requirement_blueprint(
                goal_text,
                assume_defaults=True,
            )
        }
    if module_ref == "module.local.librarian@1":
        return {
            "local_index": _artifact(
                "LocalLibraryIndex",
                {
                    "roots": ["libraries", "examples/modules", "examples/artifacts", "examples/flows"],
                    "capabilities": ["contract-validation", "artifact-emission", "local-smoke-tests"],
                },
            )
        }
    if module_ref == "module.online.library_sources@1":
        return {
            "online_sources": _artifact(
                "OnlineLibrarySources",
                {
                    "sources": [
                        {"name": "package-registry", "usage": "dependency lookup"},
                        {"name": "official-docs", "usage": "implementation reference"},
                    ],
                    "network_required": True,
                },
            )
        }
    if module_ref == "module.feature.library_search@1":
        local_caps = inputs["local_index"]["payload"].get("capabilities", [])
        online_sources = inputs["online_sources"]["payload"].get("sources", [])
        return {
            "candidates": _artifact(
                "FeatureLibraryCandidates",
                {
                    "intent": request.get("intent", ""),
                    "local": local_caps,
                    "online": [row.get("name") for row in online_sources],
                    "ranked": ["contract-validation", "artifact-emission", "official-docs"],
                },
            )
        }
    if module_ref == "module.local_agent.plan@1":
        return {
            "agent_plan": _artifact(
                "LocalAgentPlan",
                {
                    "steps": ["intake", "resolve-libraries", "generate-blueprint", "emit-tests", "report-effects"],
                    "candidate_count": len(candidates.get("ranked", [])),
                    "mode": "local-agent",
                },
            )
        }
    if module_ref == "module.adversarial_generation@1":
        return {
            "adversarial_review": _artifact(
                "AdversarialReview",
                {
                    "checks": ["missing-acceptance", "unbounded-network", "direct-module-coupling"],
                    "findings": [],
                    "verdict": "pass",
                    "plan_steps": agent_plan.get("steps", []),
                },
            )
        }
    if module_ref == "module.project.generator@1":
        return {
            "project_blueprint": _artifact(
                "ProjectBlueprint",
                {
                    "name": "local_task_board",
                    "features": ["tickets", "kanban-board", "local-storage", "test-report"],
                    "libraries": candidates.get("ranked", []),
                },
            ),
            "generation_trace": _artifact(
                "GenerationTrace",
                {
                    "events": [
                        "request-normalized",
                        "libraries-ranked",
                        "agent-plan-created",
                        "adversarial-review-passed",
                        "blueprint-emitted",
                    ],
                    "write_root": "generated/",
                },
            ),
        }
    if module_ref == "module.test_graph.emit@1":
        features = blueprint.get("features", [])
        nodes = ["goal", "request", "blueprint"] + [f"test:{feature}" for feature in features]
        return {
            "test_graph": _artifact(
                "TestGraph",
                {
                    "nodes": nodes,
                    "edges": [["goal", "request"], ["request", "blueprint"]]
                    + [["blueprint", f"test:{feature}"] for feature in features],
                    "trace_events": trace.get("events", []),
                },
            )
        }
    if module_ref == "module.effect_report.emit@1":
        return {
            "effect_report": _artifact(
                "EffectReport",
                {
                    "summary": "module smoke outputs are internally consistent",
                    "test_node_count": len(test_graph.get("nodes", [])),
                    "effects": {"network": "declared-only", "provider": "not-used", "fs_write": "generated/**"},
                    "verdict": "pass",
                },
            )
        }
    if module_ref == "module.unified_control@1":
        return {
            "project_blueprint": inputs["project_blueprint"],
            "generation_trace": inputs["generation_trace"],
            "test_graph": inputs["test_graph"],
            "effect_report": inputs["effect_report"],
        }
    raise KeyError(f"no simulator for {module_ref}")


def _mermaid(test_graph: dict[str, Any]) -> str:
    payload = test_graph.get("payload", {})
    lines = ["flowchart TD"]
    for left, right in payload.get("edges", []):
        lines.append(f"  {left.replace(':', '_')} --> {right.replace(':', '_')}")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    flow = _load_json(FLOW_PATH)
    modules = {
        _ref(_load_json(path)): _load_json(path)
        for path in sorted((ROOT / "examples" / "modules").glob("*.module.json"))
    }
    values: dict[tuple[str, str], dict[str, Any]] = {
        ("flow_input", "goal"): _artifact("Goal", {"text": "生成一个本地任务看板项目"})
    }
    module_rows: list[dict[str, Any]] = []
    for node in flow["nodes"]:
        module_ref = node["uses"]
        module = modules[module_ref]
        inputs: dict[str, dict[str, Any]] = {}
        for edge in flow["edges"]:
            target = edge["to"]
            if target.get("node") != node["id"]:
                continue
            source = edge["from"]
            if "flow_input" in source:
                value = values[("flow_input", source["flow_input"])]
            else:
                value = values[(source["node"], source["port"])]
            inputs[target["port"]] = value
        missing = [
            port
            for port, spec in module["ports"]["input"].items()
            if spec.get("required", False) and port not in inputs
        ]
        if missing:
            raise RuntimeError(f"{node['id']} missing required inputs: {missing}")
        outputs = _simulate(module_ref, inputs)
        expected_outputs = set(module["ports"]["output"].keys())
        if set(outputs.keys()) != expected_outputs:
            raise RuntimeError(f"{node['id']} output mismatch expected={sorted(expected_outputs)} actual={sorted(outputs)}")
        for port, value in outputs.items():
            values[(node["id"], port)] = value
            _write_json(RUN_DIR / "artifacts" / f"{node['id']}.{port}.json", value)
        module_rows.append(
            {
                "node": node["id"],
                "module": module_ref,
                "inputs": sorted(inputs.keys()),
                "outputs": sorted(outputs.keys()),
                "status": "pass",
            }
        )
    flow_outputs: dict[str, dict[str, Any]] = {}
    for edge in flow["edges"]:
        target = edge["to"]
        if "flow_output" not in target:
            continue
        source = edge["from"]
        flow_outputs[target["flow_output"]] = values[(source["node"], source["port"])]
    _write_text(RUN_DIR / "artifacts" / "test_graph.mmd", _mermaid(flow_outputs["test_graph"]))
    result = {
        "kind": "ModuleSmokeTestResult",
        "flow_ref": FLOW_REF,
        "ok": True,
        "module_count": len(module_rows),
        "modules": module_rows,
        "outputs": sorted(flow_outputs.keys()),
        "run_dir": str(RUN_DIR),
        "result_path": str(RESULT_PATH),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(RESULT_PATH, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"MODULE_SMOKE: {'OK' if result['ok'] else 'FAIL'} modules={result['module_count']}")
        print(f"result={result['result_path']}")
        print(f"run_dir={result['run_dir']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
