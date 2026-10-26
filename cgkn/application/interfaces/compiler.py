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
    def compile_notes(self, obligations: ObligationSet) -> ExecutableInterfaceContractSet:
        known = {item.obligation_id for item in obligations.obligations}
        needed = {"OBL-NOTES-ADD", "OBL-NOTES-LIST", "OBL-NOTES-SHOW", "OBL-NOTES-DELETE", "OBL-NOTES-CLI-HELP"}
        if missing := sorted(needed - known):
            raise ValueError("missing Notes interface obligations: " + ",".join(missing))
        provenance = FrozenMapping({"compiler": "notes_interface_contract_compiler@1", "authority": "public_contract"})
        scope = ("local_json_notes",)
        def function(identifier: str, name: str, obligations_: tuple[str, ...], params: list[dict], optional: list[dict] = []):
            return ExecutableInterfaceContract(identifier, InterfaceKind.PYTHON_FUNCTION, f"notes.service.{name}", obligations_,
                FrozenMapping({"module": "notes.service", "name": name, "exported": True, "parameters": params}),
                optional=FrozenMapping({"parameters": optional}), compatibility_policy=FrozenMapping({"allow_additional_optional_parameters": False}),
                scope=scope, provenance=provenance)
        required_path = {"name": "path", "kind": "POSITIONAL_OR_KEYWORD", "required": True}
        required_id = {"name": "note_id", "kind": "POSITIONAL_OR_KEYWORD", "required": True}
        contracts = (
            ExecutableInterfaceContract("INTERFACE-NOTES-MODULE-001", InterfaceKind.PYTHON_MODULE, "notes", ("OBL-NOTES-CLI-HELP",),
                FrozenMapping({"module": "notes", "package_init": "notes/__init__.py", "module_entrypoint": "notes/__main__.py"}), scope=scope, provenance=provenance),
            function("INTERFACE-NOTES-ADD-001", "add_note", ("OBL-NOTES-ADD", "OBL-NOTES-ADD-TAG"),
                [required_path, {"name": "text", "kind": "POSITIONAL_OR_KEYWORD", "required": True}],
                [{"name": "tag", "kind": "POSITIONAL_OR_KEYWORD", "default_present": True}]),
            function("INTERFACE-NOTES-LIST-001", "list_notes", ("OBL-NOTES-LIST", "OBL-NOTES-LIST-TAG"), [required_path],
                [{"name": "tag", "kind": "POSITIONAL_OR_KEYWORD", "default_present": True}]),
            function("INTERFACE-NOTES-SHOW-001", "show_note", ("OBL-NOTES-SHOW",), [required_path, required_id]),
            function("INTERFACE-NOTES-DELETE-001", "delete_note", ("OBL-NOTES-DELETE",), [required_path, required_id]),
            ExecutableInterfaceContract("INTERFACE-NOTES-CLI-001", InterfaceKind.CLI, "python -m notes", tuple(sorted(known)),
                FrozenMapping({"entrypoint": ["python", "-m", "notes"], "subcommands": {
                    "add": {"positionals": [{"name": "text", "index": 0, "required": True}], "options": {"--tag": {"takes_value": True}}},
                    "list": {"positionals": [], "options": {"--tag": {"takes_value": True}}},
                    "show": {"positionals": [{"name": "id", "index": 0, "required": True}], "options": {}},
                    "delete": {"positionals": [{"name": "id", "index": 0, "required": True}], "options": {}},
                }}), optional=FrozenMapping({"options": {"--help": {"takes_value": False}}}),
                forbidden=FrozenMapping({"subcommands": ["create", "remove", "get", "ls", "new"], "options": ["--id"]}),
                compatibility_policy=FrozenMapping({"allow_additional_subcommands": False, "allow_additional_options": False, "preserve_positional_order": True}),
                scope=scope, provenance=provenance),
        )
        return ExecutableInterfaceContractSet(contracts, obligations.as_dict()["obligation_set_hash"])

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
