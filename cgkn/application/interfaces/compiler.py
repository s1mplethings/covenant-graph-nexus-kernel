from __future__ import annotations

from cgkn.application.requirements.obligation import FrozenMapping, ObligationSet

from .contracts import ExecutableInterfaceContract, ExecutableInterfaceContractSet, InterfaceKind


CSV_INTERFACE_OBLIGATIONS = {
    "OBL-CSV-INPUT-OUTPUT",
    "OBL-CSV-CLI-HELP",
    "OBL-CSV-PREVIEW",
    "OBL-CSV-DEDUP-COLUMN",
    "OBL-CSV-FILL-EMPTY",
}


class InterfaceContractCompiler:
    def compile_csv(self, obligations: ObligationSet) -> ExecutableInterfaceContractSet:
        known = {item.obligation_id for item in obligations.obligations}
        missing = sorted(CSV_INTERFACE_OBLIGATIONS - known)
        if missing:
            raise ValueError("missing CSV interface obligations: " + ",".join(missing))
        provenance = FrozenMapping({"compiler": "csv_interface_contract_compiler@1", "authority": "public_contract"})
        scope = ("cli_csv_cleaner",)
        contracts = (
            ExecutableInterfaceContract(
                "INTERFACE-CSV-MODULE-001", InterfaceKind.PYTHON_MODULE, "csv_cleaner",
                ("OBL-CSV-INPUT-OUTPUT", "OBL-CSV-CLI-HELP"),
                FrozenMapping({"module": "csv_cleaner", "package_init": "csv_cleaner/__init__.py", "module_entrypoint": "csv_cleaner/__main__.py"}),
                scope=scope, provenance=provenance,
            ),
            ExecutableInterfaceContract(
                "INTERFACE-CSV-CLEAN-FUNCTION-001", InterfaceKind.PYTHON_FUNCTION, "csv_cleaner.core.clean_csv",
                ("OBL-CSV-INPUT-OUTPUT", "OBL-CSV-DEDUP-COLUMN", "OBL-CSV-FILL-EMPTY"),
                FrozenMapping({
                    "module": "csv_cleaner.core", "name": "clean_csv", "exported": True,
                    "parameters": [
                        {"name": "input_path", "kind": "POSITIONAL_OR_KEYWORD", "required": True},
                        {"name": "output_path", "kind": "POSITIONAL_OR_KEYWORD", "required": True},
                    ],
                }),
                optional=FrozenMapping({"parameters": [
                    {"name": "dedupe_column", "kind": "POSITIONAL_OR_KEYWORD", "default_present": True},
                    {"name": "fill", "kind": "POSITIONAL_OR_KEYWORD", "default_present": True},
                ]}),
                compatibility_policy=FrozenMapping({"allow_additional_optional_parameters": True}),
                scope=scope, provenance=provenance,
            ),
            ExecutableInterfaceContract(
                "INTERFACE-CSV-CLI-001", InterfaceKind.CLI, "python -m csv_cleaner",
                tuple(sorted(CSV_INTERFACE_OBLIGATIONS)),
                FrozenMapping({
                    "entrypoint": ["python", "-m", "csv_cleaner"],
                    "positionals": [
                        {"name": "input", "index": 0, "required": True},
                        {"name": "output", "index": 1, "required": True},
                    ],
                }),
                optional=FrozenMapping({"options": {
                    "--dedupe-column": {"takes_value": True},
                    "--fill": {"takes_value": True},
                    "--preview": {"takes_value": True},
                    "--help": {"takes_value": False},
                }}),
                forbidden=FrozenMapping({"options": ["-o", "--output"]}),
                compatibility_policy=FrozenMapping({"allow_additional_options": False, "preserve_positional_order": True}),
                scope=scope, provenance=provenance,
            ),
        )
        return ExecutableInterfaceContractSet(contracts, obligations.as_dict()["obligation_set_hash"])
