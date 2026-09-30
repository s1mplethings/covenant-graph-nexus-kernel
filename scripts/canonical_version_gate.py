#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED_AUTHORITIES = {
    "requirement", "assumption", "planning", "execution", "provider_scheduler",
    "evidence", "acceptance", "promotion", "packaging", "delivery",
}
VALID_STATES = {"ACTIVE", "COMPAT_ONLY", "SUPERSEDED", "ARCHIVE_ONLY", "REMOVED"}
PRODUCTION_ROOTS = ("cgkn", "scripts")
CURRENT_DOCS = ("README.md", "AGENTS.md", "docs/00_kernel_contract.md", "docs/01_contract_registry.md", "docs/15_release_versioning.md")
RETIRED_PATHS = (
    "scripts/generate_project.py", "scripts/legacy_provider_pipeline.py",
    "scripts/deliver_product_studio.py", "scripts/run_product_studio.py",
    "legacy/generate_project_legacy.py", "legacy/deliver_product_studio.py",
    "legacy/run_product_studio.py",
)


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _version_key(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?", value.strip())
    if not match:
        raise ValueError(f"invalid semantic version: {value}")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), 0 if rc is not None else 1, int(rc or 0)


def _authority_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [f"<invalid:{type(value).__name__}>"]


def _module_name(path: str) -> str:
    return pathlib.PurePosixPath(path).with_suffix("").as_posix().replace("/", ".")


def _imports(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _production_python(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for relative in PRODUCTION_ROOTS:
        base = root / relative
        if base.is_dir():
            yield from base.rglob("*.py")


def validate_repository(
    root: pathlib.Path = ROOT,
    *,
    architecture: dict[str, Any] | None = None,
    deprecations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    architecture = architecture or _read_json(root / "governance" / "current_architecture.json")
    deprecations = deprecations or _read_json(root / "governance" / "deprecation_registry.json")
    product_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    failures: list[dict[str, str]] = []

    if architecture.get("kind") != "CGKNCurrentArchitecture":
        failures.append({"code": "current_architecture_kind_invalid", "detail": str(architecture.get("kind"))})
    if architecture.get("forbidden_parallel_authorities") is not True:
        failures.append({"code": "parallel_authority_policy_missing", "detail": "forbidden_parallel_authorities must be true"})
    if not isinstance(architecture.get("supersedes"), list):
        failures.append({"code": "supersedes_contract_missing", "detail": "supersedes must be a list, including [] when empty"})

    authorities = architecture.get("authorities", {}) if isinstance(architecture.get("authorities"), dict) else {}
    active_authorities: dict[str, str | None] = {}
    duplicate_authorities: list[dict[str, Any]] = []
    for responsibility, raw in authorities.items():
        owners = _authority_values(raw)
        active_authorities[str(responsibility)] = owners[0] if len(owners) == 1 else None
        if len(owners) > 1:
            item = {"responsibility": str(responsibility), "owners": owners}
            duplicate_authorities.append(item)
            failures.append({"code": "duplicate_active_authority", "detail": json.dumps(item, ensure_ascii=False)})
    for responsibility in sorted(REQUIRED_AUTHORITIES):
        if len(_authority_values(authorities.get(responsibility))) != 1:
            failures.append({"code": "required_active_authority_missing", "detail": responsibility})
    clarification = _authority_values(authorities.get("clarification"))
    if len(clarification) > 1:
        failures.append({"code": "duplicate_active_authority", "detail": "clarification"})

    version_mismatches: list[dict[str, str]] = []
    if str(architecture.get("product_version", "")) != product_version:
        version_mismatches.append({"source": "governance/current_architecture.json", "value": str(architecture.get("product_version", "")), "expected": product_version})
    for item in version_mismatches:
        failures.append({"code": "version_mismatch", "detail": json.dumps(item)})

    items = deprecations.get("items", []) if isinstance(deprecations.get("items"), list) else []
    compatibility_items: list[str] = []
    expired_compatibility: list[str] = []
    legacy_producers: list[str] = []
    registry_missing_paths: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            failures.append({"code": "deprecation_item_invalid", "detail": repr(item)})
            continue
        item_id = str(item.get("id", ""))
        if item.get("state") != "COMPAT_ONLY" or item.get("state") not in VALID_STATES:
            failures.append({"code": "deprecation_state_invalid", "detail": item_id})
        compatibility_items.append(item_id)
        if item.get("new_production_forbidden") is not True:
            failures.append({"code": "compatibility_production_not_forbidden", "detail": item_id})
        try:
            if _version_key(product_version) >= _version_key(str(item.get("remove_in", ""))):
                expired_compatibility.append(item_id)
                failures.append({"code": "expired_compatibility", "detail": item_id})
        except ValueError as exc:
            failures.append({"code": "compatibility_version_invalid", "detail": f"{item_id}: {exc}"})
        paths = item.get("paths", []) if isinstance(item.get("paths"), list) else []
        missing = [path for path in paths if not (root / str(path)).exists()]
        if not paths or missing:
            registry_missing_paths.extend(f"{item_id}:{path}" for path in (missing or ["<none>"]))
            failures.append({"code": "removed_item_still_registered", "detail": ", ".join(missing or [item_id])})
        operations = {str(value).lower() for value in item.get("allowed_operations", [])}
        outputs = item.get("canonical_outputs", [])
        if operations & {"write", "produce", "create"} or (isinstance(outputs, list) and outputs):
            legacy_producers.append(item_id)
            failures.append({"code": "compatibility_produces_canonical_output", "detail": item_id})

    superseded = architecture.get("implementations", []) if isinstance(architecture.get("implementations"), list) else []
    superseded_modules: dict[str, str] = {}
    superseded_paths: list[str] = []
    responsibility_owners: dict[str, list[str]] = {}
    for item in superseded:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", ""))
        if state not in VALID_STATES:
            failures.append({"code": "implementation_state_invalid", "detail": str(item.get("id", ""))})
        if state == "ACTIVE":
            responsibility_owners.setdefault(str(item.get("responsibility", "")), []).append(str(item.get("id", "")))
        if state == "SUPERSEDED":
            for path in item.get("paths", []):
                normalized = str(path).replace("\\", "/")
                superseded_paths.append(normalized)
                superseded_modules[_module_name(normalized)] = str(item.get("id", normalized))
    for responsibility, owners in responsibility_owners.items():
        if responsibility and len(owners) > 1:
            duplicate_authorities.append({"responsibility": responsibility, "owners": owners})
            failures.append({"code": "duplicate_active_authority", "detail": f"{responsibility}: {owners}"})

    superseded_production_refs: list[str] = []
    for source in _production_python(root):
        source_rel = source.relative_to(root).as_posix()
        if source_rel in superseded_paths:
            continue
        for imported in _imports(source):
            for module, item_id in superseded_modules.items():
                if imported == module or imported.startswith(module + "."):
                    ref = f"{source_rel}->{item_id}"
                    superseded_production_refs.append(ref)
                    failures.append({"code": "superseded_production_import", "detail": ref})

    retained_retired = [path for path in RETIRED_PATHS if (root / path).exists()]
    for path in retained_retired:
        failures.append({"code": "retired_path_present", "detail": path})

    stale_current_docs: list[str] = []
    stale_claims = architecture.get("forbidden_current_claims", []) if isinstance(architecture.get("forbidden_current_claims"), list) else []
    for relative in CURRENT_DOCS:
        path = root / relative
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        for claim in stale_claims:
            if str(claim) in text:
                stale_current_docs.append(f"{relative}:{claim}")
    for ref in stale_current_docs:
        failures.append({"code": "stale_current_documentation", "detail": ref})

    status = "PASS" if not failures else "NEEDS_REWORK"
    return {
        "status": status,
        "product_version": product_version,
        "active_authorities": active_authorities,
        "compatibility_items": compatibility_items,
        "expired_compatibility": expired_compatibility,
        "superseded_production_refs": superseded_production_refs,
        "duplicate_authorities": duplicate_authorities,
        "stale_current_docs": stale_current_docs,
        "legacy_producers": legacy_producers,
        "version_mismatches": version_mismatches,
        "retired_paths_present": retained_retired,
        "registry_missing_paths": registry_missing_paths,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CGKN canonical version and retirement governance.")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    result = validate_repository(pathlib.Path(args.root))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"canonical_version_gate: {result['status']} ({len(result['failures'])} failures)")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
