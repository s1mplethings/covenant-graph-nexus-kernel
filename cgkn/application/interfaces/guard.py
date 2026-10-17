from __future__ import annotations

from typing import Any

from cgkn.application.requirements.obligation import FrozenMapping, thaw

from .contracts import ExecutableInterfaceContract, ExecutableInterfaceContractSet, InterfaceKind
from .evidence import InterfaceContractEvidence, InterfaceContractStatus
from .extractor import ObservedInterfaceManifest


def _evidence(
    contract: ExecutableInterfaceContract,
    status: InterfaceContractStatus,
    observed: dict[str, Any],
    failure_class: str | None = None,
    required_action: str | None = None,
    expected: dict[str, Any] | None = None,
) -> InterfaceContractEvidence:
    suffix = contract.contract_id.removeprefix("INTERFACE-")
    return InterfaceContractEvidence(
        f"EVIDENCE-INTERFACE-{suffix}", contract.contract_id, status,
        FrozenMapping(expected if expected is not None else thaw(contract.required)), FrozenMapping(observed),
        failure_class, required_action,
    )


def _guard_module(contract: ExecutableInterfaceContract, manifest: ObservedInterfaceManifest) -> InterfaceContractEvidence:
    required = thaw(contract.required)
    module = str(required["module"])
    observed = thaw(manifest.modules).get(module)
    if observed is None:
        return _evidence(contract, InterfaceContractStatus.FAIL, {"module": module, "exists": False}, "ENTRYPOINT_MISSING", f"create required Python module {module}")
    entrypoint = required.get("module_entrypoint")
    if entrypoint and not any(item.get("path") == entrypoint for item in thaw(manifest.modules).values()):
        return _evidence(contract, InterfaceContractStatus.FAIL, observed, "ENTRYPOINT_MISSING", f"create required module entrypoint {entrypoint}")
    return _evidence(contract, InterfaceContractStatus.PASS, observed)


def _guard_function(contract: ExecutableInterfaceContract, manifest: ObservedInterfaceManifest) -> InterfaceContractEvidence:
    required = thaw(contract.required)
    observed = thaw(manifest.functions).get(contract.subject_ref)
    if observed is None:
        return _evidence(contract, InterfaceContractStatus.FAIL, {"function": contract.subject_ref, "exists": False}, "FUNCTION_MISSING", f"define required function {contract.subject_ref}")
    if required.get("exported") and not observed.get("exported"):
        return _evidence(contract, InterfaceContractStatus.FAIL, observed, "SIGNATURE_MISMATCH", f"export {contract.subject_ref} as a public function")
    actual = observed.get("parameters", [])
    for index, expected in enumerate(required.get("parameters", [])):
        if index >= len(actual) or any(actual[index].get(key) != expected.get(key) for key in ("name", "kind", "required")):
            return _evidence(contract, InterfaceContractStatus.FAIL, observed, "SIGNATURE_MISMATCH", f"parameter {index} must be {expected}")
    optional_by_name = {item["name"]: item for item in thaw(contract.optional).get("parameters", [])}
    actual_by_name = {item["name"]: item for item in actual}
    for name, expected in optional_by_name.items():
        found = actual_by_name.get(name)
        if found is None or (expected.get("default_present") and not found.get("default_present")):
            return _evidence(contract, InterfaceContractStatus.FAIL, observed, "SIGNATURE_MISMATCH", f"optional parameter {name} must have a default")
    return _evidence(contract, InterfaceContractStatus.PASS, observed)


def _guard_cli(contract: ExecutableInterfaceContract, manifest: ObservedInterfaceManifest) -> InterfaceContractEvidence:
    expected = thaw(contract.required)
    observed = thaw(manifest.cli)
    if manifest.unresolved:
        return _evidence(contract, InterfaceContractStatus.UNRESOLVED, observed | {"unresolved": list(manifest.unresolved)}, "UNRESOLVED_INTERFACE", "replace dynamic argparse declarations with statically declared public arguments")
    if observed.get("entrypoint") != expected.get("entrypoint"):
        return _evidence(contract, InterfaceContractStatus.FAIL, observed, "ENTRYPOINT_MISSING", "provide python -m csv_cleaner through csv_cleaner/__main__.py")
    actual_positionals = observed.get("positionals", [])
    actual_options = observed.get("options", {})
    for positional in expected.get("positionals", []):
        index = int(positional["index"])
        if index < len(actual_positionals) and actual_positionals[index].get("name") == positional["name"]:
            continue
        option_matches = [value for value in actual_options.values() if value.get("dest") == positional["name"]]
        if option_matches:
            option = option_matches[0]
            return _evidence(
                contract, InterfaceContractStatus.FAIL, option, "POSITIONAL_TO_OPTIONAL",
                f"make {positional['name']} the second required positional argument; do not add -o or --output",
                {"name": positional["name"], "kind": "POSITIONAL", "index": index},
            )
        return _evidence(contract, InterfaceContractStatus.FAIL, {"positionals": actual_positionals}, "MISSING_POSITIONAL", f"add {positional['name']} as required positional index {index}", positional)
    forbidden = set(thaw(contract.forbidden).get("options", []))
    present_forbidden = sorted(forbidden & set(actual_options))
    if present_forbidden:
        return _evidence(contract, InterfaceContractStatus.FAIL, {"options": present_forbidden}, "EXTRA_FORBIDDEN_OPTION", "remove forbidden option aliases: " + ", ".join(present_forbidden), {"forbidden_options": sorted(forbidden)})
    for flag, option in thaw(contract.optional).get("options", {}).items():
        actual = actual_options.get(flag)
        if actual is None or actual.get("takes_value") != option.get("takes_value"):
            return _evidence(contract, InterfaceContractStatus.FAIL, {"options": actual_options}, "MISSING_OPTION", f"declare {flag} with takes_value={option.get('takes_value')}", {flag: option})
    return _evidence(contract, InterfaceContractStatus.PASS, observed)


def guard_interface(contract: ExecutableInterfaceContract, manifest: ObservedInterfaceManifest) -> InterfaceContractEvidence:
    if contract.interface_kind is InterfaceKind.PYTHON_MODULE:
        return _guard_module(contract, manifest)
    if contract.interface_kind is InterfaceKind.PYTHON_FUNCTION:
        return _guard_function(contract, manifest)
    return _guard_cli(contract, manifest)


def guard_interfaces(contracts: ExecutableInterfaceContractSet, manifest: ObservedInterfaceManifest) -> tuple[InterfaceContractEvidence, ...]:
    return tuple(guard_interface(contract, manifest) for contract in contracts.contracts)
