from __future__ import annotations

import argparse
import ast
import json

from kernel_gate_common import ROOT, imported_modules, load_json, module_file, result, source_files


def _package(relative: str) -> str:
    return ".".join(relative[:-3].split("/")[:2])


def _cycles(graph: dict[str, set[str]]) -> list[str]:
    found: set[str] = set(); active: list[str] = []; visited: set[str] = set()
    def visit(node: str) -> None:
        if node in active:
            cycle = active[active.index(node):] + [node]
            found.add("->".join(cycle))
            return
        if node in visited: return
        active.append(node)
        for target in sorted(graph.get(node, set())): visit(target)
        active.pop(); visited.add(node)
    for node in sorted(graph): visit(node)
    return sorted(found)


def check() -> dict:
    errors: list[str] = []
    try:
        layers = load_json("governance/kernel_layers.json")
        authorities = load_json("governance/kernel_authorities.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return result("CGKNKernelArchitectureGate", [f"governance_unreadable:{exc}"])
    package_levels: dict[str, int] = {}
    for entry in layers.get("layers", []):
        level = int(str(entry.get("id", "L-1"))[1:])
        for package in entry.get("packages", []):
            if package in package_levels:
                errors.append(f"duplicate_layer_package:{package}")
            package_levels[str(package)] = level
    canonicals: list[str] = []
    for name, entry in dict(authorities.get("authorities", {})).items():
        canonical = entry.get("canonical")
        refs = canonical if isinstance(canonical, list) else [canonical]
        for ref in refs:
            if not isinstance(ref, str):
                errors.append(f"invalid_canonical:{name}")
                continue
            canonicals.append(ref)
            if ":" not in ref:
                if not (ROOT / ref).exists(): errors.append(f"missing_canonical:{name}:{ref}")
                continue
            path = module_file(ref)
            if not path.is_file():
                errors.append(f"missing_canonical:{name}:{ref}")
                continue
            symbol = ref.split(":", 1)[1]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if symbol not in {node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}:
                errors.append(f"missing_canonical_symbol:{name}:{ref}")
    if len(canonicals) != len(set(canonicals)):
        errors.append("duplicate_canonical_authority")
    same_layer_graph: dict[str, set[str]] = {package: set() for package in package_levels}
    for relative in source_files():
        source_package = _package(relative)
        source_level = package_levels.get(source_package)
        if source_level is None:
            errors.append(f"unlayered_source:{relative}")
            continue
        for imported in imported_modules(ROOT / relative):
            target = next((package for package in package_levels if imported == package or imported.startswith(package + ".")), None)
            if target and package_levels[target] > source_level:
                errors.append(f"forbidden_reverse_import:{relative}:{target}")
            if target and target != source_package and package_levels[target] == source_level:
                same_layer_graph[source_package].add(target)
    for cycle in _cycles(same_layer_graph): errors.append(f"same_layer_package_cycle:{cycle}")
    for relative in sorted(path for path in source_files() if path.startswith("cgkn/agent/")):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"write_text", "write_bytes", "unlink", "replace"}:
                errors.append(f"agent_direct_file_mutation:{relative}:{node.lineno}")
        imports = imported_modules(ROOT / relative)
        if any(name == "subprocess" or name.startswith("subprocess.") for name in imports): errors.append(f"agent_direct_subprocess:{relative}")
    for relative in sorted(path for path in source_files() if path.startswith("cgkn/providers/")):
        imports = imported_modules(ROOT / relative)
        if any(name.startswith(("cgkn.agent", "cgkn.runtime")) for name in imports): errors.append(f"provider_forbidden_import:{relative}")
    for relative in sorted(path for path in source_files() if path.startswith("cgkn/orchestration/")):
        if any(name.startswith("cgkn.providers") for name in imported_modules(ROOT / relative)): errors.append(f"orchestration_provider_import:{relative}")
    growth_text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in source_files() if path.startswith("cgkn/growth/"))
    if "CapabilityRegistry" not in growth_text: errors.append("growth_registry_boundary_missing")
    if any(token in growth_text for token in ('write_text("cgkn/', "write_text('cgkn/", 'write_bytes("cgkn/', "write_bytes('cgkn/")): errors.append("growth_kernel_write_detected")
    runner_path = ROOT / "cgkn/runtime/runner.py"
    if not runner_path.is_file():
        errors.append("artifact_runner_missing")
    else:
        runner_text = runner_path.read_text(encoding="utf-8")
        if any(token in runner_text for token in ("ExecutionDAG", "RunState", "NodeExecutionRecord")): errors.append("artifact_runner_second_scheduler")
    invalidation_path = ROOT / "cgkn/runtime/invalidation.py"
    if not invalidation_path.is_file():
        errors.append("runtime_invalidation_missing")
    else:
        invalidation_text = invalidation_path.read_text(encoding="utf-8")
        if ".descendants(" not in invalidation_text or "while " in invalidation_text: errors.append("runtime_invalidation_duplicates_graph_closure")
    runtime_text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in source_files() if path.startswith("cgkn/runtime/"))
    for role in ("ProjectManager", "ResearchAgent", "MarketingAgent"):
        if role in runtime_text: errors.append(f"runtime_role_dependency:{role}")
    expected = set(authorities.get("compatibility_entrypoints", []))
    if not expected or any(not (ROOT / path).is_file() for path in expected):
        errors.append("compatibility_entrypoint_missing")
    architecture = load_json("governance/current_architecture.json")
    if "not the MVP planning or composition authority" not in str(architecture.get("compatibility_rule", "")):
        errors.append("compatibility_not_marked_non_authoritative")
    return result("CGKNKernelArchitectureGate", errors, source_count=len(source_files()), authority_count=len(authorities.get("authorities", {})))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.parse_args()
    value = check(); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["status"] == "PASS" else 1)
