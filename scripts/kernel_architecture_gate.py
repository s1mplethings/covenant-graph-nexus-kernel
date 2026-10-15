from __future__ import annotations

import argparse
import ast
import json

from kernel_gate_common import ROOT, imported_modules, load_json, module_file, result, source_files


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
    for relative in source_files():
        source_package = ".".join(relative[:-3].split("/")[:2])
        source_level = package_levels.get(source_package)
        if source_level is None:
            errors.append(f"unlayered_source:{relative}")
            continue
        for imported in imported_modules(ROOT / relative):
            target = next((package for package in package_levels if imported == package or imported.startswith(package + ".")), None)
            if target and package_levels[target] > source_level:
                errors.append(f"forbidden_reverse_import:{relative}:{target}")
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
