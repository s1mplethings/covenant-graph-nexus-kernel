#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "test_results" / "local_pipeline_composition_result.json"

CORE_PROJECT_GENERATION = [
    "module.customer.service@1",
    "module.requirement_blueprint.generator@1",
    "module.local.librarian@1",
    "module.feature.library_search@1",
    "module.local_agent.plan@1",
    "module.adversarial_generation@1",
    "module.project.generator@1",
    "module.test_graph.emit@1",
    "module.effect_report.emit@1",
    "module.unified_control@1",
]


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ref_of(doc: dict[str, Any]) -> str:
    return f"{doc['id']}@{doc['version']}"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", str(text or "").lower())


def doc_text(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("id", "type_name"):
        if key in doc:
            parts.append(str(doc[key]))
    metadata = doc.get("metadata", {})
    if isinstance(metadata, dict):
        parts.extend(str(v) for v in metadata.values() if isinstance(v, (str, int, float, bool)))
    ports = doc.get("ports", {})
    if isinstance(ports, dict):
        parts.append(json.dumps(ports, ensure_ascii=False))
    requires = doc.get("requires", {})
    if isinstance(requires, dict):
        parts.append(json.dumps(requires, ensure_ascii=False))
    return " ".join(parts)


def load_contracts() -> dict[str, Any]:
    modules = [load_json(p) for p in sorted((ROOT / "examples" / "modules").glob("*.module.json"))]
    artifacts = [load_json(p) for p in sorted((ROOT / "examples" / "artifacts").glob("*.artifact_type.json"))]
    flows = [load_json(p) for p in sorted((ROOT / "examples" / "flows").glob("*.flow.json"))]
    policies = [load_json(p) for p in sorted((ROOT / "examples" / "policies").glob("*.policy.json"))]
    return {
        "modules": modules,
        "artifacts": artifacts,
        "flows": flows,
        "policies": policies,
    }


def score_modules(goal: str, modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query = Counter(tokenize(goal))
    scored: list[dict[str, Any]] = []
    for module in modules:
        text_tokens = Counter(tokenize(doc_text(module)))
        score = sum(min(count, text_tokens.get(tok, 0)) for tok, count in query.items())
        module_id = module["id"]
        lowered_goal = goal.lower()
        if any(word in lowered_goal for word in ("api", "llm", "模型", "大模型")) and "api_gateway" in module_id:
            score += 8
        if any(word in lowered_goal for word in ("项目", "project", "生成", "pipeline", "管线")):
            if module_id in {
                "module.customer.service",
                "module.local.librarian",
                "module.local.pipeline_composer_agent",
                "module.project.generator",
                "module.unified_control",
            }:
                score += 5
        scored.append(
            {
                "module_ref": ref_of(module),
                "score": score,
                "purpose": str(module.get("metadata", {}).get("purpose", "")),
                "network": bool(module.get("effects", {}).get("network")),
                "provider_call": bool(module.get("effects", {}).get("provider_call")),
                "inputs": sorted(module.get("ports", {}).get("input", {}).keys()),
                "outputs": sorted(module.get("ports", {}).get("output", {}).keys()),
            }
        )
    return sorted(scored, key=lambda row: (-int(row["score"]), row["module_ref"]))


def optional_local_model_hint(goal: str, catalog: dict[str, Any]) -> dict[str, Any]:
    cmd = str(os.environ.get("CGNK_LOCAL_MODEL_CMD", "")).strip()
    prompt = {
        "task": (
            "Act as CGNK local librarian and route manager. Inspect available_modules, choose the route for this "
            "project request, and return strict JSON with selected_modules, librarian_notes, route_notes, and risks."
        ),
        "goal": goal,
        "available_modules": [ref_of(m) for m in catalog["modules"]],
        "module_purposes": {
            ref_of(m): str(m.get("metadata", {}).get("purpose", ""))
            for m in catalog["modules"]
        },
    }
    if not cmd:
        return ollama_model_hint(prompt)
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(prompt, ensure_ascii=False),
            capture_output=True,
            text=True,
            shell=True,
            cwd=str(ROOT),
            timeout=60,
        )
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": str(exc)}
    if proc.returncode != 0:
        return {"enabled": True, "ok": False, "error": proc.stderr.strip()[:500]}
    try:
        doc = json.loads(proc.stdout)
    except Exception:
        doc = extract_json(proc.stdout)
        if doc is None:
            return {"enabled": True, "provider": "command", "ok": False, "error": "local model returned non-json", "preview": proc.stdout[:500]}
    return {"enabled": True, "provider": "command", "ok": True, "result": doc}


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def get_json(url: str, timeout: int) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1))
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first : last + 1])
    for candidate in candidates:
        try:
            doc = json.loads(candidate)
        except Exception:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def choose_ollama_model(host: str) -> str:
    configured = str(os.environ.get("CGNK_OLLAMA_MODEL", "")).strip()
    if configured:
        return configured
    tags = get_json(host.rstrip("/") + "/api/tags", timeout=5)
    models = [str(row.get("name", "")).strip() for row in tags.get("models", []) if isinstance(row, dict)]
    for preferred in ("qwen2.5:7b-instruct", "qwen2:7b"):
        if preferred in models:
            return preferred
    return models[0] if models else ""


def ollama_model_hint(prompt: dict[str, Any]) -> dict[str, Any]:
    host = str(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).strip().rstrip("/")
    try:
        model = choose_ollama_model(host)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, json.JSONDecodeError) as exc:
        return {"enabled": False, "provider": "ollama", "ok": False, "error": f"ollama unavailable: {exc}"}
    if not model:
        return {"enabled": False, "provider": "ollama", "ok": False, "error": "no ollama models installed"}
    model_prompt = (
        "You are the local CGNK pipeline composer agent. "
        "Return only JSON. The JSON shape is {\"selected_modules\": [string], \"notes\": string}. "
        "selected_modules must only contain refs from available_modules.\n\n"
        + json.dumps(prompt, ensure_ascii=False, indent=2)
    )
    try:
        doc = post_json(
            host + "/api/generate",
            {"model": model, "prompt": model_prompt, "stream": False, "options": {"temperature": 0}},
            timeout=90,
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, json.JSONDecodeError) as exc:
        return {"enabled": True, "provider": "ollama", "model": model, "ok": False, "error": f"ollama request failed: {exc}"}
    response = str(doc.get("response", "")).strip()
    parsed = extract_json(response)
    if parsed is None:
        return {"enabled": True, "provider": "ollama", "model": model, "ok": False, "error": "ollama returned non-json", "preview": response[:500]}
    return {"enabled": True, "provider": "ollama", "model": model, "ok": True, "result": parsed}


def base_edges_for_selected(selected: list[str], flows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_set = set(selected)
    for flow in flows:
        if ref_of(flow) == "flow.modular_project_generation@1":
            node_to_module = {node["id"]: node["uses"] for node in flow.get("nodes", [])}
            edges: list[dict[str, Any]] = []
            for edge in flow.get("edges", []):
                src = edge.get("from", {})
                dst = edge.get("to", {})
                if "node" in src and node_to_module.get(src["node"]) not in selected_set:
                    continue
                if "node" in dst and node_to_module.get(dst["node"]) not in selected_set:
                    continue
                edges.append(edge)
            return edges
    return []


def module_block_reason(module: dict[str, Any], policy: dict[str, Any], *, allow_network: bool, allow_provider: bool) -> str:
    effects = module.get("effects", {})
    if bool(effects.get("network")) and not allow_network:
        return "requires explicit --allow-network"
    if bool(effects.get("provider_call")) and not allow_provider:
        return "requires explicit --allow-provider"
    if bool(effects.get("network")) and not policy.get("network", {}).get("allowed", False):
        return "network denied by flow policy"
    if bool(effects.get("provider_call")) and not policy.get("provider", {}).get("allowed", False):
        return "provider denied by flow policy"
    max_risk = int(policy.get("risk", {}).get("max_risk", 0))
    if int(effects.get("risk", 0)) > max_risk:
        return f"risk exceeds policy max_risk={max_risk}"
    return ""


def route_quality_report(
    *,
    selected: list[str],
    edges: list[dict[str, Any]],
    flow: dict[str, Any],
    modules_by_ref: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    external_routes: list[dict[str, Any]],
    allow_network: bool,
    allow_provider: bool,
) -> dict[str, Any]:
    node_to_module = {node["id"]: node["uses"] for node in flow.get("nodes", [])}
    selected_set = set(selected)
    connected_nodes: set[str] = set()
    bound_inputs: dict[tuple[str, str], int] = {}
    output_sources: set[str] = set()
    for edge in edges:
        src = edge.get("from", {})
        dst = edge.get("to", {})
        if "node" in src:
            connected_nodes.add(src["node"])
        if "node" in dst:
            connected_nodes.add(dst["node"])
            bound_inputs[(dst["node"], dst["port"])] = bound_inputs.get((dst["node"], dst["port"]), 0) + 1
        if "flow_output" in dst:
            output_sources.add(dst["flow_output"])

    connected_modules = {
        node_to_module[node_id]
        for node_id in connected_nodes
        if node_to_module.get(node_id) in selected_set
    }
    flow_modules = set(node_to_module.values())
    unbound_inputs: list[dict[str, str]] = []
    for node in flow.get("nodes", []):
        module_ref = node.get("uses")
        if module_ref not in selected_set:
            continue
        module = modules_by_ref.get(module_ref, {})
        for port, spec in module.get("ports", {}).get("input", {}).items():
            if spec.get("required", False) and (node["id"], port) not in bound_inputs:
                unbound_inputs.append({"node": node["id"], "module": module_ref, "port": port})

    policy_blocked_modules = []
    for module_ref in selected:
        reason = module_block_reason(
            modules_by_ref.get(module_ref, {}),
            policy,
            allow_network=allow_network,
            allow_provider=allow_provider,
        )
        if reason:
            policy_blocked_modules.append({"module": module_ref, "reason": reason})

    route_score = 100
    route_score -= 20 * len(selected_set - connected_modules)
    route_score -= 15 * len(unbound_inputs)
    route_score -= 15 * len(policy_blocked_modules)
    route_score -= 10 * len([row for row in external_routes if row.get("status") == "blocked"])
    route_score = max(0, route_score)

    return {
        "selected_module_count": len(selected),
        "connected_module_count": len(connected_modules),
        "edge_count": len(edges),
        "orphan_modules": sorted(selected_set - connected_modules),
        "modules_not_in_base_flow": sorted(selected_set - flow_modules),
        "unbound_inputs": unbound_inputs,
        "unbound_input_count": len(unbound_inputs),
        "policy_blocked_modules": policy_blocked_modules,
        "blocked_external_routes": [row for row in external_routes if row.get("status") == "blocked"],
        "available_external_routes": [row for row in external_routes if row.get("status") == "available"],
        "bound_flow_outputs": sorted(output_sources),
        "route_compile_status": "pass" if not unbound_inputs and not policy_blocked_modules and not (selected_set - connected_modules) else "fail",
        "route_score": route_score,
    }


def compose(goal: str, *, allow_network: bool = True, allow_provider: bool = True) -> dict[str, Any]:
    catalog = load_contracts()
    modules_by_ref = {ref_of(module): module for module in catalog["modules"]}
    flows_by_ref = {ref_of(flow): flow for flow in catalog["flows"]}
    policies_by_ref = {ref_of(policy): policy for policy in catalog["policies"]}
    modular_flow = flows_by_ref.get("flow.modular_project_generation@1", {})
    modular_policy = policies_by_ref.get(modular_flow.get("policy_ref", ""), {})
    scored = score_modules(goal, catalog["modules"])
    valid_refs = {row["module_ref"] for row in scored}
    lowered = goal.lower()
    model_hint = optional_local_model_hint(goal, catalog)
    selected: list[str] = []
    if model_hint.get("ok"):
        hinted = model_hint.get("result", {}).get("selected_modules", [])
        if isinstance(hinted, list):
            for ref in hinted:
                if isinstance(ref, str) and ref not in selected and ref in valid_refs:
                    selected.append(ref)
    if not selected:
        selected = [ref for ref in CORE_PROJECT_GENERATION if ref in valid_refs]
    required_control_modules = [
        "module.customer.service@1",
        "module.requirement_blueprint.generator@1",
        "module.local.librarian@1",
        "module.local_agent.plan@1",
        "module.project.generator@1",
        "module.test_graph.emit@1",
        "module.effect_report.emit@1",
        "module.unified_control@1",
    ]
    for ref in required_control_modules:
        if ref not in selected and ref in valid_refs:
            selected.append(ref)
    if allow_network and "module.online.library_sources@1" not in selected and "module.online.library_sources@1" in valid_refs:
        insert_at = selected.index("module.feature.library_search@1") if "module.feature.library_search@1" in selected else len(selected)
        selected.insert(insert_at, "module.online.library_sources@1")
    selected = list(dict.fromkeys(selected))
    support_modules = ["module.local.pipeline_composer_agent@1"]
    external_routes: list[dict[str, Any]] = []
    wants_api = bool(
        re.search(r"(接|调用|连接|使用|启用|with|use|call)\s*(api|openai|provider|llm|大模型)", lowered)
        or any(word in lowered for word in ("openai api", "provider api", "api 调用", "api调用", "大模型接口"))
    )
    if wants_api:
        api_ref = "module.external.api_gateway@1"
        reason = module_block_reason(
            modules_by_ref.get(api_ref, {}),
            modular_policy,
            allow_network=allow_network,
            allow_provider=allow_provider,
        )
        external_routes.append(
            {
                "module": api_ref,
                "purpose": "OpenAI-compatible provider/API call",
                "status": "blocked" if reason else "available",
                "reason": reason,
                "missing_adapter": "No producer for artifact.external_api_request@1 in flow.modular_project_generation@1",
            }
        )
    local_index = {
        "kind": "LocalLibraryIndex",
        "payload": {
            "module_count": len(catalog["modules"]),
            "artifact_count": len(catalog["artifacts"]),
            "flow_count": len(catalog["flows"]),
            "policy_count": len(catalog["policies"]),
            "top_matches": scored[:12],
        },
    }
    project_understanding = {
        "kind": "ProjectUnderstandingIndex",
        "payload": {
            "retrieval_strategy": "structured_catalog_plus_lexical_rag",
            "why_not_pure_vector_rag": "CGNK contracts are structured JSON; deterministic parsing preserves ports, effects, and policies before any semantic ranking.",
            "optional_local_model": model_hint,
            "local_librarian": {
                "provider": model_hint.get("provider", "none"),
                "model": model_hint.get("model", ""),
                "catalog_basis": "examples/modules + examples/artifacts + examples/flows + examples/policies",
                "top_local_matches": scored[:8],
                "notes": model_hint.get("result", {}).get("librarian_notes", "") if isinstance(model_hint.get("result"), dict) else "",
            },
            "route_manager": {
                "provider": model_hint.get("provider", "structured"),
                "model": model_hint.get("model", ""),
                "selection_source": "ollama" if model_hint.get("ok") else "contract_catalog_deterministic",
                "local_model_scope": ["local_librarian", "route_manager"],
                "provider_scope": ["project_generation", "project_repair", "final_project_logic"],
                "notes": model_hint.get("result", {}).get("route_notes", "") if isinstance(model_hint.get("result"), dict) else "",
                "risks": model_hint.get("result", {}).get("risks", []) if isinstance(model_hint.get("result"), dict) else [],
                "support_modules": support_modules,
            },
            "known_flows": [ref_of(flow) for flow in catalog["flows"]],
            "capability_groups": {
                "intake": ["module.customer.service@1"],
                "requirement_blueprint": ["module.requirement_blueprint.generator@1"],
                "local_understanding": ["module.local.librarian@1", "module.local.pipeline_composer_agent@1"],
                "generation": ["module.project.generator@1"],
                "verification": ["module.test_graph.emit@1", "module.effect_report.emit@1"],
                "delivery_or_external": ["module.external.api_gateway@1"],
            },
        },
    }
    edges = base_edges_for_selected(selected, catalog["flows"])
    quality = route_quality_report(
        selected=selected,
        edges=edges,
        flow=modular_flow,
        modules_by_ref=modules_by_ref,
        policy=modular_policy,
        external_routes=external_routes,
        allow_network=allow_network,
        allow_provider=allow_provider,
    )
    pipeline_plan = {
        "kind": "PipelineCompositionPlan",
        "payload": {
            "requirement": goal,
            "selected_modules": selected,
            "support_modules": support_modules,
            "external_routes": external_routes,
            "edges": edges,
            "outputs": ["requirement_blueprint", "project_blueprint", "generation_trace", "test_graph", "effect_report"],
            "gaps": (
                quality["unbound_inputs"]
                + [{"module": ref, "reason": "selected module has no route edges"} for ref in quality["orphan_modules"]]
                + quality["policy_blocked_modules"]
                + quality["blocked_external_routes"]
            ),
            "route_quality_report": quality,
            "executor": {
                "flow": "flow.local_pipeline_execution@1",
                "command": "python scripts/run_local_pipeline.py --plan examples/test_results/local_pipeline_composition_result.json",
                "provider_route": "External API routes are reported separately and require explicit runtime approval flags."
            },
            "control": "route through module.unified_control@1 when executing a generated project pipeline",
        },
    }
    return {
        "kind": "LocalPipelineCompositionRun",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "goal": goal,
        "local_index": local_index,
        "project_understanding": project_understanding,
        "pipeline_plan": pipeline_plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=True, allow_provider=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-network", dest="allow_network", action="store_true", help="Allow network routes. Enabled by default for mixed API mode.")
    parser.add_argument("--no-network", dest="allow_network", action="store_false", help="Disable network routes for a fully local composition.")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true", help="Allow provider/API routes. Enabled by default for mixed API mode.")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false", help="Disable provider/API routes.")
    args = parser.parse_args()
    result = compose(
        args.goal,
        allow_network=bool(args.allow_network),
        allow_provider=bool(args.allow_provider),
    )
    out_path = pathlib.Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    write_json(out_path, result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        selected = result["pipeline_plan"]["payload"]["selected_modules"]
        print(f"PIPELINE_COMPOSITION: OK modules={len(selected)}")
        print(f"out={out_path}")
        for ref in selected:
            print(f"  {ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
