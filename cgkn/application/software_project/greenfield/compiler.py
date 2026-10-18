from __future__ import annotations

import re
from typing import Any, Mapping

from .contracts import BundleInterfaceContract, BundleKind, BundleSpec, GenerationManifest, canonical_hash
from .cli import StructuredCLIPlan


HELP_CONTRACT = {
    "argv": ["--help"], "exit_code": 0, "stdout_contains": "usage",
    "stderr_forbids": "traceback", "business_file_side_effects": "FORBIDDEN",
    "network": "FORBIDDEN", "shell": "FORBIDDEN",
}


class GenerationManifestCompiler:
    VERSION = "greenfield-manifest-3.0"

    def compile(self, *, project_id: str, project_type: str, package_name: str,
                project_contract: Mapping[str, Any], obligations: Mapping[str, Any],
                interface_contract: Mapping[str, Any], target_paths: tuple[str, ...],
                cli_contract: Mapping[str, Any] | None = None) -> GenerationManifest:
        if not project_id or not package_name or not target_paths:
            raise ValueError("project manifest inputs are incomplete")
        targets = tuple(dict.fromkeys(path.replace("\\", "/") for path in target_paths))
        if len(targets) != len(target_paths):
            raise ValueError("duplicate target path")
        cli_paths = tuple(path for path in targets if path == f"{package_name}/__main__.py")
        init_paths = tuple(path for path in targets if path == f"{package_name}/__init__.py")
        domain_paths = tuple(path for path in targets if path not in cli_paths + init_paths)
        if not cli_paths or not init_paths or not domain_paths:
            raise ValueError("greenfield project requires domain, package/__init__.py, and package/__main__.py")
        raw_plan = cli_contract or project_contract.get("cli_contract")
        if not isinstance(raw_plan, Mapping):
            raise ValueError("STRUCTURED_CLI_CONTRACT_REQUIRED")
        plan = StructuredCLIPlan.from_dict(raw_plan)
        if plan.module_name != f"{package_name}.__main__":
            raise ValueError("CLI_CONTRACT_MODULE_MISMATCH")
        domain_kind = self._domain_kind(project_type)
        domain_interface = self._domain_interface(project_type, package_name, interface_contract, project_contract)
        cli_interface = BundleInterfaceContract(
            module=f"{package_name}.__main__", exports=("build_parser", "main"),
            signatures={"build_parser": "build_parser() -> argparse.ArgumentParser", "main": "main(argv: list[str] | None = None) -> int"},
            controlled_errors=("invalid input -> exit code 2 with non-empty stderr",),
            entrypoint=f"python -m {package_name}", commands=tuple(str(item) for item in interface_contract.get("commands", ())),
            stdout_contract="exactly the declared public behavior; deterministic",
            stderr_contract="controlled user/domain errors use stderr and exact exit code 2; no traceback",
            help_contract=HELP_CONTRACT,
        )
        obligation_refs = tuple(f"obligation.{key}" for key in sorted(obligations))
        domain = self._bundle(
            f"project.{project_id}.bundle.domain@1", domain_kind,
            "Implement domain behavior, public Python API, data model, persistence, and controlled errors.",
            domain_paths, (), (), (domain_interface.interface_hash,), (), obligation_refs,
            ({BundleKind.DOMAIN: "project.domain.simple", BundleKind.DOMAIN_STORE: "project.domain.persistent", BundleKind.LIBRARY_API: "project.domain.library"}[domain_kind]),
            domain_interface, 2800, 64 * 1024,
        )
        init_interface = BundleInterfaceContract(
            module=package_name, exports=domain_interface.exports, signatures=domain_interface.signatures,
            controlled_errors=(), stdout_contract="package import has no output or side effects",
        )
        init = self._bundle(
            f"project.{project_id}.bundle.init@1", BundleKind.INIT,
            "Render package exports deterministically from the frozen domain interface.", init_paths,
            (domain.bundle_id,), (domain_interface.interface_hash,), (init_interface.interface_hash,),
            (domain_interface.interface_hash,), obligation_refs, "deterministic.init", init_interface, 1, 16 * 1024,
            execution_mode="DETERMINISTIC",
        )
        cli = self._bundle(
            f"project.{project_id}.bundle.cli@1", BundleKind.CLI,
            "Implement only argparse/public CLI semantics and call the frozen domain interface.",
            cli_paths, (domain.bundle_id, init.bundle_id), (domain_interface.interface_hash,), (cli_interface.interface_hash,),
            (domain_interface.interface_hash,), obligation_refs + ("obligation.cli_help",),
            "deterministic.cli", cli_interface, 1, 32 * 1024, execution_mode="DETERMINISTIC",
        )
        all_interfaces = {"domain": domain_interface.as_dict(), "cli": cli_interface.as_dict()}
        contract_chars = len(str(project_contract)) + len(str(obligations)) + len(str(all_interfaces))
        if contract_chars > 24_000:
            raise ValueError("BUNDLE_SIZE_CONTRACT_LIMIT")
        return GenerationManifest(
            project_id, project_type, package_name, canonical_hash(project_contract), canonical_hash(obligations),
            canonical_hash(all_interfaces), (domain, init, cli), {domain.bundle_id: (), init.bundle_id: (domain.bundle_id,), cli.bundle_id: (domain.bundle_id, init.bundle_id)},
            ("pyproject.toml", "README.md", "tests/contract", "cli-help-contract"),
            {"route_frozen": True, "fallback": "deny", "transport_retry_per_bundle": 1, "manifest_version": self.VERSION,
             "provider_bundle_kinds": [domain_kind.value], "deterministic_bundle_kinds": ["INIT", "CLI"]},
            {"atomic": True, "overlapping_targets": "FORBIDDEN", "source_hash_verification": "REQUIRED"},
            cli_plan=plan.as_dict(),
        )

    @staticmethod
    def _domain_kind(project_type: str) -> BundleKind:
        if project_type == "PERSISTENT_CRUD":
            return BundleKind.DOMAIN_STORE
        if project_type in {"LIBRARY", "INSTALLABLE_LIBRARY"}:
            return BundleKind.LIBRARY_API
        return BundleKind.DOMAIN

    @staticmethod
    def _domain_interface(project_type: str, package: str, interface: Mapping[str, Any], contract: Mapping[str, Any]) -> BundleInterfaceContract:
        public_api = str(contract.get("behavior_contract", {}).get("public_api", ""))
        match = re.search(r"(?:[A-Za-z_][\w]*\.)?([A-Za-z_]\w*)\s*\(([^)]*)\)", public_api)
        if project_type in {"LIBRARY", "INSTALLABLE_LIBRARY"} and match:
            name = match.group(1)
            signature = f"{name}({match.group(2)})"
            exports = (name, "cli_execute", "ProjectError")
            signatures = {name: signature, "cli_execute": "cli_execute(operation: str, parameters: dict[str, object]) -> dict[str, object]", "ProjectError": "class ProjectError(ValueError)"}
        else:
            exports = ("execute", "ProjectError")
            signatures = {"execute": "execute(operation: str, parameters: dict[str, object]) -> object", "ProjectError": "class ProjectError(ValueError)"}
        return BundleInterfaceContract(
            module=f"{package}.core", exports=exports, signatures=signatures,
            controlled_errors=("invalid user/domain input raises ProjectError", "no network or shell side effects"),
            stdout_contract="domain functions return values and do not print",
        )

    @staticmethod
    def _bundle(bundle_id: str, kind: BundleKind, goal: str, targets: tuple[str, ...], depends: tuple[str, ...],
                required: tuple[str, ...], provided: tuple[str, ...], consumed: tuple[str, ...], obligations: tuple[str, ...],
                task_class: str, interface: BundleInterfaceContract, tokens: int, size: int,
                *, execution_mode: str = "PROVIDER") -> BundleSpec:
        return BundleSpec(
            bundle_id, kind, goal, targets, depends, required, provided, consumed, obligations,
            ("write_file", "patch_file"),
            ("tests", "README.md", "pyproject.toml", "hidden_acceptance", "governance", "artifacts", "network", "shell"),
            {"task_class": task_class, "operation": "GENERATION", "max_lessons": 3, "max_chars": 1600},
            tokens, size, 180, "low", interface, execution_mode=execution_mode,
        )
