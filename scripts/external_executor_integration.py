#!/usr/bin/env python3
"""Bind a trusted external executor to generated-project implementation evidence.

This module is a deterministic integration guard.  It owns no discovery,
Provider, evidence, acceptance, packaging, delivery, or release authority.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0"
_API_PROFILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "av": ("av", ("av.open",)),
    "ffmpeg-python": ("ffmpeg", ("ffmpeg.input",)),
    "imageio-ffmpeg": ("imageio_ffmpeg", ("imageio_ffmpeg.read_frames",)),
    "pypdf": ("pypdf", ("pypdf.PdfReader",)),
    "pdfplumber": ("pdfplumber", ("pdfplumber.open",)),
    "httpx": ("httpx", ("httpx.Client",)),
    "requests": ("requests", ("requests.Session",)),
}
_IGNORED_PARTS = {".git", ".venv", "venv", "tests", "test", "docs", "examples", "__pycache__", "artifacts"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_integration_contracts(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project the selected executor into the smallest enforceable contract."""
    contracts: list[dict[str, Any]] = []
    for result in selection.get("results", []):
        if not isinstance(result, Mapping) or result.get("route") != "external":
            continue
        selected = result.get("selected_executor")
        if not isinstance(selected, Mapping):
            continue
        package = str(selected.get("package") or "").strip()
        version = str(selected.get("version") or "").strip()
        capability_id = str(selected.get("capability_id") or result.get("intent", {}).get("capability_id") or "").strip()
        if not package or not version or not capability_id:
            continue
        module, symbols = _API_PROFILES.get(package.lower(), (package.replace("-", "_"), (package.replace("-", "_"),)))
        identity = {
            "capability_id": capability_id,
            "candidate_id": selected.get("trust_provenance", {}).get("candidate_id"),
            "package": package,
            "version": version,
            "repository": selected.get("repository"),
        }
        contract = {
            "kind": "CGKNExternalExecutorIntegrationContract",
            "schema_version": SCHEMA_VERSION,
            "capability_id": capability_id,
            "executor_type": "external",
            "executor_identity": identity,
            "executor_identity_hash": _digest(identity),
            "dependency": {"package": package, "version": version, "specifier": f"{package}=={version}"},
            "source_usage": {"module": module, "required_api_symbols": list(symbols), "ast_required": True},
            "integration_policy": {
                "adapter_or_wrapper_only": True,
                "substitute_library_forbidden": True,
                "core_reimplementation_forbidden": True,
                "readme_comment_example_not_evidence": True,
            },
            "release_authority": False,
            "formal_acceptance_authority": False,
        }
        contract["contract_hash"] = _digest(contract)
        contracts.append(contract)
    return contracts


def provider_projection(contracts: Iterable[Mapping[str, Any]]) -> str:
    rows = []
    for item in contracts:
        dep = item.get("dependency", {})
        usage = item.get("source_usage", {})
        rows.append({
            "capability_id": item.get("capability_id"),
            "exact_dependency": dep.get("specifier"),
            "required_api_symbols": usage.get("required_api_symbols", []),
            "contract_hash": item.get("contract_hash"),
        })
    if not rows:
        return ""
    return (
        "MANDATORY SELECTED-EXECUTOR INTEGRATION (highest implementation priority): "
        + json.dumps(rows, ensure_ascii=False, sort_keys=True)
        + " Add the exact dependency pin and call the required API from real application source. "
          "An adapter/wrapper is allowed; substituting another library or reimplementing its core is forbidden. "
          "README, comments, tests, examples, and unused imports are not evidence. If impossible, report "
          "SELECTED_EXECUTOR_INTEGRATION_BLOCKED; do not silently replace the executor."
    )


def attach_contracts_to_components(component_pipeline: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach contracts only to matching implementation, dependency, and test components."""
    if not contracts:
        return component_pipeline
    components = component_pipeline.get("components", [])
    for component in components if isinstance(components, list) else []:
        if not isinstance(component, dict):
            continue
        text = " ".join(str(component.get(key, "")) for key in ("id", "name", "goal", "responsibility", "description")).lower()
        matched = [
            contract for contract in contracts
            if str(contract.get("capability_id", "")).replace("-", " ").replace("_", " ").lower() in text
            or any(marker in text for marker in ("foundation", "dependency", "integration", "test", "quality"))
        ]
        if matched:
            component["external_executor_integration_contracts"] = matched
    return component_pipeline


def _dependency_versions(root: pathlib.Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    requirements = root / "requirements.txt"
    if requirements.is_file():
        for raw in requirements.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|>|<|!=)?\s*([^\s;#]*)", raw)
            if match:
                value = match.group(3) if match.group(2) == "==" else f"{match.group(2) or ''}{match.group(3) or ''}"
                found.setdefault(match.group(1).lower(), set()).add(value)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
            for raw in data.get("project", {}).get("dependencies", []):
                match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|>|<|!=)?\s*([^\s;]*)", str(raw))
                if match:
                    value = match.group(3) if match.group(2) == "==" else f"{match.group(2) or ''}{match.group(3) or ''}"
                    found.setdefault(match.group(1).lower(), set()).add(value)
            for name, value in data.get("tool", {}).get("poetry", {}).get("dependencies", {}).items():
                version = value if isinstance(value, str) else value.get("version") if isinstance(value, Mapping) else None
                if isinstance(version, str) and version.startswith("=="):
                    found.setdefault(str(name).lower(), set()).add(version[2:])
        except (OSError, ValueError):
            pass
    return found


def _source_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in root.rglob("*.py") if not any(part.lower() in _IGNORED_PARTS for part in path.relative_to(root).parts))


def _calls(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    aliases: dict[str, str] = {}
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    def dotted(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = dotted(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            value = dotted(node.func)
            if value:
                called.add(value)
    return called


def _source_identity(root: pathlib.Path) -> str:
    rows = []
    for path in _source_files(root):
        rows.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    for name in ("requirements.txt", "pyproject.toml"):
        path = root / name
        if path.is_file():
            rows.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
    return _digest(rows)


def validate_project_integration(
    project_dir: str | pathlib.Path,
    contracts: Iterable[Mapping[str, Any]],
    *,
    runtime_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    require_runtime: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(project_dir).resolve()
    contracts = list(contracts)
    dependencies = _dependency_versions(root)
    source_calls = {str(path.relative_to(root)): sorted(_calls(path)) for path in _source_files(root)}
    results: list[dict[str, Any]] = []
    for contract in contracts:
        package = str(contract.get("dependency", {}).get("package", ""))
        version = str(contract.get("dependency", {}).get("version", ""))
        required = set(contract.get("source_usage", {}).get("required_api_symbols", []))
        actual_calls = {call for calls in source_calls.values() for call in calls}
        dependency_status = "PASS" if version in dependencies.get(package.lower(), set()) else "FAIL"
        source_status = "PASS" if required and required.issubset(actual_calls) else "FAIL"
        runtime = dict((runtime_evidence or {}).get(package, {}))
        runtime_status = "NOT_EVALUATED"
        if runtime:
            runtime_status = "PASS" if (
                runtime.get("exit_code") == 0
                and runtime.get("installed_package", "").lower() == package.lower()
                and str(runtime.get("installed_version")) == version
                and runtime.get("external_api_used") is True
                and bool(runtime.get("output_verified"))
            ) else "FAIL"
        statuses = [dependency_status, source_status] + ([runtime_status] if require_runtime else [])
        failure_codes: list[str] = []
        if dependency_status != "PASS":
            failure_codes.append(
                "SELECTED_EXECUTOR_VERSION_MISMATCH"
                if package.lower() in dependencies else "SELECTED_EXECUTOR_DEPENDENCY_MISSING"
            )
        if source_status != "PASS":
            failure_codes.append("SELECTED_EXECUTOR_SOURCE_USAGE_MISSING")
        if require_runtime and runtime_status != "PASS":
            failure_codes.append("SELECTED_EXECUTOR_RUNTIME_USAGE_MISSING")
        results.append({
            "capability_id": contract.get("capability_id"), "package": package, "version": version,
            "contract_hash": contract.get("contract_hash"), "dependency_status": dependency_status,
            "source_usage_status": source_status, "runtime_status": runtime_status,
            "required_api_symbols": sorted(required), "observed_api_calls": sorted(actual_calls & required),
            "source_files": [name for name, calls in source_calls.items() if required.intersection(calls)],
            "failure_codes": failure_codes,
            "status": "PASS" if all(item == "PASS" for item in statuses) else ("NOT_EVALUATED" if "NOT_EVALUATED" in statuses else "FAIL"),
        })
    overall = "PASS" if results and all(item["status"] == "PASS" for item in results) else ("NOT_EVALUATED" if results and any(item["status"] == "NOT_EVALUATED" for item in results) else "FAIL")
    return {
        "kind": "CGKNExternalExecutorIntegrationReceipt", "schema_version": SCHEMA_VERSION,
        "status": overall, "project_dir": str(root), "project_source_identity": _source_identity(root),
        "contract_set_hash": _digest([item.get("contract_hash") for item in contracts]),
        "failure_code": "SELECTED_EXECUTOR_INTEGRATION_FAILED" if overall == "FAIL" else None,
        "results": results, "release_authority": False, "formal_acceptance_authority": False,
    }


def receipt_is_current(receipt: Mapping[str, Any], project_dir: str | pathlib.Path, contracts: Iterable[Mapping[str, Any]]) -> bool:
    root = pathlib.Path(project_dir).resolve()
    return (
        receipt.get("project_source_identity") == _source_identity(root)
        and receipt.get("contract_set_hash") == _digest([item.get("contract_hash") for item in contracts])
    )


def select_next_candidate(results: Iterable[Mapping[str, Any]], failed_candidate_ids: Iterable[str]) -> dict[str, Any]:
    failed = set(failed_candidate_ids)
    for result in results:
        for candidate in result.get("candidates", []):
            if candidate.get("candidate_id") in failed:
                continue
            if not candidate.get("rejection_reasons") and candidate.get("trial", {}).get("status") == "PASS":
                return {"route": "external", "candidate": dict(candidate), "pipeline_fallback": None}
    return {"route": "agent_build", "candidate": None, "pipeline_fallback": "agent_build"}
