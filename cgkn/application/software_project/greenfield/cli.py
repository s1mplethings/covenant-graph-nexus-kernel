from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class CLIArgumentKind(str, Enum):
    POSITIONAL = "POSITIONAL"
    OPTION = "OPTION"


class CLIValueType(str, Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    PATH = "PATH"


class CLIArgumentAction(str, Enum):
    STORE = "STORE"
    STORE_TRUE = "STORE_TRUE"
    APPEND = "APPEND"


class CLIOutputMode(str, Enum):
    COMMAND_OUTCOME = "COMMAND_OUTCOME"
    TEXT = "TEXT"
    JSON = "JSON"
    JSON_LINES = "JSON_LINES"
    SILENT = "SILENT"


@dataclass(frozen=True)
class CLIArgumentSpec:
    argument_id: str
    kind: CLIArgumentKind
    flags: tuple[str, ...]
    dest: str
    value_type: CLIValueType = CLIValueType.STRING
    required: bool = False
    default: Any = None
    nargs: str | int | None = None
    repeatable: bool = False
    action: CLIArgumentAction = CLIArgumentAction.STORE
    choices: tuple[str, ...] = ()
    metavar: str = ""

    def __post_init__(self) -> None:
        if not self.argument_id or not self.dest or not self.flags:
            raise ValueError("CLI_ARGUMENT_INVALID")
        if self.kind is CLIArgumentKind.POSITIONAL and any(flag.startswith("-") for flag in self.flags):
            raise ValueError("CLI_POSITIONAL_FLAG_INVALID")
        if self.kind is CLIArgumentKind.OPTION and not all(flag.startswith("-") for flag in self.flags):
            raise ValueError("CLI_OPTION_FLAG_INVALID")
        if self.repeatable and self.action is not CLIArgumentAction.APPEND:
            raise ValueError("CLI_REPEATABLE_REQUIRES_APPEND")

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(kind=self.kind.value, value_type=self.value_type.value, action=self.action.value, flags=list(self.flags), choices=list(self.choices))
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CLIArgumentSpec":
        return cls(str(value["argument_id"]), CLIArgumentKind(str(value["kind"])), tuple(value["flags"]), str(value["dest"]),
                   CLIValueType(str(value.get("value_type", "STRING"))), bool(value.get("required", False)), value.get("default"),
                   value.get("nargs"), bool(value.get("repeatable", False)), CLIArgumentAction(str(value.get("action", "STORE"))),
                   tuple(value.get("choices", ())), str(value.get("metavar", "")))


@dataclass(frozen=True)
class CLIDispatchSpec:
    domain_module: str
    callable_name: str
    operation: str
    parameter_mapping: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.domain_module or not self.callable_name or not self.operation:
            raise ValueError("CLI_DISPATCH_INVALID")
        for value in self.parameter_mapping.values():
            if isinstance(value, str) and value.startswith("$args."):
                if not value.removeprefix("$args.").isidentifier():
                    raise ValueError("CLI_DISPATCH_ARGUMENT_INVALID")
            elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
                continue
            else:
                raise ValueError("CLI_DISPATCH_LITERAL_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return {"domain_module": self.domain_module, "callable_name": self.callable_name, "operation": self.operation,
                "parameter_mapping": dict(self.parameter_mapping)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CLIDispatchSpec":
        return cls(str(value["domain_module"]), str(value["callable_name"]), str(value["operation"]), dict(value.get("parameter_mapping", {})))


@dataclass(frozen=True)
class CLIOutputSpec:
    mode: CLIOutputMode = CLIOutputMode.COMMAND_OUTCOME
    json_flag_dest: str = ""
    stable_json: bool = True
    trailing_newline: bool = True
    value_path: str = ""
    error_when_false: str = ""
    error_message: str = "domain operation failed"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "mode": self.mode.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CLIOutputSpec":
        return cls(CLIOutputMode(str(value.get("mode", "COMMAND_OUTCOME"))), str(value.get("json_flag_dest", "")),
                   bool(value.get("stable_json", True)), bool(value.get("trailing_newline", True)), str(value.get("value_path", "")),
                   str(value.get("error_when_false", "")), str(value.get("error_message", "domain operation failed")))


@dataclass(frozen=True)
class CLIErrorMapping:
    exception_name: str = "ProjectError"
    exit_code: int = 2
    stream: str = "stderr"
    message_policy: str = "EXCEPTION_MESSAGE"

    def __post_init__(self) -> None:
        if self.stream not in {"stdout", "stderr"} or self.exit_code < 1:
            raise ValueError("CLI_ERROR_MAPPING_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CLIErrorMapping":
        return cls(str(value.get("exception_name", "ProjectError")), int(value.get("exit_code", 2)),
                   str(value.get("stream", "stderr")), str(value.get("message_policy", "EXCEPTION_MESSAGE")))


@dataclass(frozen=True)
class DomainCommandContract:
    callable_name: str = "execute"
    error_type: str = "ProjectError"
    outcome_kinds: tuple[str, ...] = ("text", "json", "json_lines", "silent")
    accept_legacy_raw: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "outcome_kinds": list(self.outcome_kinds)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainCommandContract":
        return cls(str(value.get("callable_name", "execute")), str(value.get("error_type", "ProjectError")), tuple(value.get("outcome_kinds", ("text", "json", "json_lines", "silent"))), bool(value.get("accept_legacy_raw", False)))


@dataclass(frozen=True)
class CLICommandSpec:
    command_id: str
    subcommand_name: str
    help_text: str
    positionals: tuple[CLIArgumentSpec, ...]
    options: tuple[CLIArgumentSpec, ...]
    dispatch: CLIDispatchSpec
    output: CLIOutputSpec = field(default_factory=CLIOutputSpec)
    error_mappings: tuple[CLIErrorMapping, ...] = field(default_factory=lambda: (CLIErrorMapping(),))
    obligation_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"command_id": self.command_id, "subcommand_name": self.subcommand_name, "help_text": self.help_text,
                "positionals": [item.as_dict() for item in self.positionals], "options": [item.as_dict() for item in self.options],
                "dispatch": self.dispatch.as_dict(), "output": self.output.as_dict(),
                "error_mappings": [item.as_dict() for item in self.error_mappings], "obligation_refs": list(self.obligation_refs)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CLICommandSpec":
        return cls(str(value["command_id"]), str(value.get("subcommand_name", "")), str(value.get("help_text", "")),
                   tuple(CLIArgumentSpec.from_dict(item) for item in value.get("positionals", ())),
                   tuple(CLIArgumentSpec.from_dict(item) for item in value.get("options", ())), CLIDispatchSpec.from_dict(value["dispatch"]),
                   CLIOutputSpec.from_dict(value.get("output", {})), tuple(CLIErrorMapping.from_dict(item) for item in value.get("error_mappings", ({},))),
                   tuple(value.get("obligation_refs", ())))


@dataclass(frozen=True)
class StructuredCLIPlan:
    program_name: str
    module_name: str
    entrypoint: str
    commands: tuple[CLICommandSpec, ...]
    global_options: tuple[CLIArgumentSpec, ...] = ()
    help_contract: Mapping[str, Any] = field(default_factory=dict)
    error_mappings: tuple[CLIErrorMapping, ...] = field(default_factory=lambda: (CLIErrorMapping(),))
    output_policy: Mapping[str, Any] = field(default_factory=lambda: {"stable_json": True})
    side_effect_policy: Mapping[str, Any] = field(default_factory=lambda: {"help": "FORBIDDEN"})
    domain_contract: DomainCommandContract = field(default_factory=DomainCommandContract)
    plan_version: str = "1.0"
    plan_hash: str = ""

    def __post_init__(self) -> None:
        if not self.program_name or not self.module_name or not self.entrypoint or not self.commands:
            raise ValueError("CLI_CONTRACT_INCOMPLETE")
        subcommands = [item.subcommand_name for item in self.commands]
        if len(self.commands) > 1 and (not all(subcommands) or len(set(subcommands)) != len(subcommands)):
            raise ValueError("CLI_CONTRACT_UNSUPPORTED")
        expected = _hash(self.as_dict(include_hash=False))
        if self.plan_hash and self.plan_hash != expected:
            raise ValueError("CLI_PLAN_HASH_MISMATCH")
        object.__setattr__(self, "plan_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"program_name": self.program_name, "module_name": self.module_name, "entrypoint": self.entrypoint,
                 "commands": [item.as_dict() for item in self.commands], "global_options": [item.as_dict() for item in self.global_options],
                 "help_contract": dict(self.help_contract), "error_mappings": [item.as_dict() for item in self.error_mappings],
                 "output_policy": dict(self.output_policy), "side_effect_policy": dict(self.side_effect_policy),
                 "domain_contract": self.domain_contract.as_dict(), "plan_version": self.plan_version}
        if include_hash:
            value["plan_hash"] = self.plan_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuredCLIPlan":
        return cls(str(value["program_name"]), str(value["module_name"]), str(value["entrypoint"]),
                   tuple(CLICommandSpec.from_dict(item) for item in value.get("commands", ())),
                   tuple(CLIArgumentSpec.from_dict(item) for item in value.get("global_options", ())), dict(value.get("help_contract", {})),
                   tuple(CLIErrorMapping.from_dict(item) for item in value.get("error_mappings", ({},))), dict(value.get("output_policy", {})),
                   dict(value.get("side_effect_policy", {})), DomainCommandContract.from_dict(value.get("domain_contract", {})),
                   str(value.get("plan_version", "1.0")), str(value.get("plan_hash", "")))


class DeterministicCLICompiler:
    VERSION = "deterministic-cli-1.0"
    UNSUPPORTED = ("interactive_tui", "shell_completion", "python_callback", "nested_mutually_exclusive")

    def render_main(self, plan: StructuredCLIPlan) -> str:
        data = json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source = _RUNTIME.replace("__PLAN_JSON__", repr(data)).replace("__COMPILER_VERSION__", self.VERSION)
        ast.parse(source)
        return source

    def render_init(self, *, domain_module: str, exports: tuple[str, ...]) -> str:
        names = tuple(dict.fromkeys(name for name in exports if name.isidentifier() and name != "cli_execute"))
        if not names:
            return '"""Generated package exports."""\n'
        module = domain_module.rsplit(".", 1)[-1]
        return f"from .{module} import {', '.join(names)}\n\n__all__ = {names!r}\n"


_RUNTIME = r'''"""Generated by __COMPILER_VERSION__; do not hand edit."""
import argparse
import json
import sys
from importlib import import_module

_PLAN = json.loads(__PLAN_JSON__)

def _add_argument(parser, spec):
    kwargs = {}
    if spec.get("action") == "STORE_TRUE": kwargs["action"] = "store_true"
    elif spec.get("action") == "APPEND": kwargs["action"] = "append"
    if spec.get("value_type") == "INTEGER": kwargs["type"] = int
    if spec.get("required") and spec["kind"] == "OPTION": kwargs["required"] = True
    if spec.get("default") is not None: kwargs["default"] = spec["default"]
    if spec.get("nargs") is not None: kwargs["nargs"] = spec["nargs"]
    if spec.get("choices"): kwargs["choices"] = spec["choices"]
    if spec.get("metavar"): kwargs["metavar"] = spec["metavar"]
    if spec["kind"] == "OPTION": kwargs["dest"] = spec["dest"]
    parser.add_argument(*spec["flags"], **kwargs)

def build_parser():
    parser = argparse.ArgumentParser(prog=_PLAN["program_name"])
    for spec in _PLAN["global_options"]: _add_argument(parser, spec)
    if len(_PLAN["commands"]) > 1:
        subs = parser.add_subparsers(dest="_command", required=True)
        for command in _PLAN["commands"]:
            target = subs.add_parser(command["subcommand_name"], help=command["help_text"])
            for spec in command["positionals"] + command["options"]: _add_argument(target, spec)
            target.set_defaults(_command_id=command["command_id"])
    else:
        command = _PLAN["commands"][0]
        for spec in command["positionals"] + command["options"]: _add_argument(parser, spec)
        parser.set_defaults(_command_id=command["command_id"])
    return parser

def _emit(outcome, output, args):
    kind = outcome.get("kind") if output["mode"] == "COMMAND_OUTCOME" else output["mode"].lower()
    value = outcome.get("value")
    if output.get("json_flag_dest") and getattr(args, output["json_flag_dest"], False): kind = "json"
    if kind == "silent": return
    if kind == "json": text = json.dumps(value, ensure_ascii=False, sort_keys=output.get("stable_json", True), separators=(",", ":"))
    elif kind == "json_lines": text = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in value)
    elif kind == "text": text = str(value)
    else: raise ValueError("invalid CommandOutcome kind")
    end = "\n" if output.get("trailing_newline", True) else ""
    sys.stdout.write(text + end)

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    command = next(item for item in _PLAN["commands"] if item["command_id"] == args._command_id)
    dispatch = command["dispatch"]
    parameters = {}
    for key, value in dispatch["parameter_mapping"].items():
        parameters[key] = getattr(args, value[6:]) if isinstance(value, str) and value.startswith("$args.") else value
    module = import_module(dispatch["domain_module"])
    try:
        outcome = getattr(module, dispatch["callable_name"])(dispatch["operation"], parameters)
        if not isinstance(outcome, dict) or set(outcome) != {"kind", "value"}:
            if _PLAN["domain_contract"].get("accept_legacy_raw"):
                failure_field = command["output"].get("error_when_false")
                if failure_field and isinstance(outcome, dict) and outcome.get(failure_field) is False:
                    raise getattr(module, "ProjectError")(command["output"].get("error_message", "domain operation failed"))
                value_path = command["output"].get("value_path")
                if value_path and isinstance(outcome, dict): outcome = outcome[value_path]
                legacy_kind = "json" if command["output"].get("json_flag_dest") and getattr(args, command["output"]["json_flag_dest"], False) else "json"
                outcome = {"kind": legacy_kind, "value": outcome}
            else: raise ValueError("invalid CommandOutcome")
        _emit(outcome, command["output"], args)
        return 0
    except getattr(module, "ProjectError") as exc:
        mapping = next((item for item in command["error_mappings"] if item["exception_name"] == "ProjectError"), {"exit_code":2,"stream":"stderr"})
        stream = sys.stderr if mapping["stream"] == "stderr" else sys.stdout
        stream.write(str(exc) + "\n")
        return mapping["exit_code"]

if __name__ == "__main__":
    raise SystemExit(main())
'''
