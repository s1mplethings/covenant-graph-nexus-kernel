from __future__ import annotations

import ast
import hashlib
import json
import pathlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tuple(value: Iterable[Any] | None) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or ()))


def _safe_path(value: str) -> str:
    path = pathlib.PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or str(path) in {".", ""}:
        raise ValueError(f"unsafe project-relative path: {value!r}")
    return path.as_posix()


class BlueprintStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    EXECUTING = "EXECUTING"
    REPAIRING = "REPAIRING"
    DONE = "DONE"
    FAILED = "FAILED"


class UnitKind(str, Enum):
    IMPLEMENTATION = "implementation"
    TESTS = "tests"
    DOCUMENTATION = "documentation"
    VERIFICATION = "verification"
    ACCEPTANCE = "acceptance"


@dataclass(frozen=True)
class BlueprintUnit:
    unit_id: str
    purpose: str
    kind: str
    owns: tuple[str, ...]
    reads: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    executor_ref: str = ""
    instruction: str = ""
    required_interfaces: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    allowed_effects: tuple[str, ...] = ()
    max_actions: int = 5
    max_files: int = 5
    max_output_bytes: int = 64_000
    status: str = "PENDING"

    def __post_init__(self) -> None:
        if not self.unit_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in self.unit_id):
            raise ValueError("invalid unit_id")
        if self.kind not in {item.value for item in UnitKind}:
            raise ValueError(f"invalid unit kind: {self.kind}")
        owns = tuple(_safe_path(item) for item in self.owns)
        reads = tuple(_safe_path(item) for item in self.reads)
        if len(set(owns)) != len(owns) or len(owns) > 5 or len(owns) > self.max_files:
            raise ValueError("unit owns must be unique and contain at most five paths")
        if set(owns) & set(reads):
            raise ValueError("unit reads and owns must not overlap")
        if self.kind in {UnitKind.IMPLEMENTATION.value, UnitKind.TESTS.value, UnitKind.DOCUMENTATION.value} and not owns:
            raise ValueError("provider unit requires owned paths")
        if self.kind in {UnitKind.VERIFICATION.value, UnitKind.ACCEPTANCE.value} and owns:
            raise ValueError("deterministic verification/acceptance units cannot own files")
        if self.kind in {UnitKind.VERIFICATION.value, UnitKind.ACCEPTANCE.value} and not self.executor_ref.startswith("local.") and self.executor_ref != "project.acceptance@1":
            raise ValueError("verification/acceptance requires a deterministic executor")
        if self.kind in {UnitKind.IMPLEMENTATION.value, UnitKind.TESTS.value, UnitKind.DOCUMENTATION.value} and self.executor_ref != "llm.cheap@1":
            raise ValueError("production units require the bounded worker executor")
        if min(self.max_actions, self.max_files, self.max_output_bytes) < 1:
            raise ValueError("unit limits must be positive")
        object.__setattr__(self, "owns", owns)
        object.__setattr__(self, "reads", reads)

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id, "purpose": self.purpose, "kind": self.kind,
            "owns": list(self.owns), "reads": list(self.reads), "depends_on": list(self.depends_on),
            "executor_ref": self.executor_ref, "instruction": self.instruction,
            "required_interfaces": list(self.required_interfaces), "acceptance": list(self.acceptance),
            "allowed_effects": list(self.allowed_effects), "max_actions": self.max_actions,
            "max_files": self.max_files, "max_output_bytes": self.max_output_bytes, "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BlueprintUnit":
        return cls(
            unit_id=str(value["unit_id"]), purpose=str(value.get("purpose", "")), kind=str(value["kind"]),
            owns=_tuple(value.get("owns")), reads=_tuple(value.get("reads")), depends_on=_tuple(value.get("depends_on")),
            executor_ref=str(value.get("executor_ref", "")), instruction=str(value.get("instruction", "")),
            required_interfaces=_tuple(value.get("required_interfaces")), acceptance=_tuple(value.get("acceptance")),
            allowed_effects=_tuple(value.get("allowed_effects")), max_actions=int(value.get("max_actions", 5)),
            max_files=int(value.get("max_files", 5)), max_output_bytes=int(value.get("max_output_bytes", 64_000)),
            status=str(value.get("status", "PENDING")),
        )


@dataclass(frozen=True)
class BlueprintCheck:
    check_id: str
    kind: str
    command: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {UnitKind.VERIFICATION.value, UnitKind.ACCEPTANCE.value}:
            raise ValueError("check kind must be verification or acceptance")

    def as_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "kind": self.kind, "command": list(self.command), "depends_on": list(self.depends_on), "acceptance": list(self.acceptance)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BlueprintCheck":
        return cls(str(value["check_id"]), str(value["kind"]), _tuple(value.get("command")), _tuple(value.get("depends_on")), _tuple(value.get("acceptance")))


@dataclass(frozen=True)
class ProjectBlueprint:
    schema_version: str
    project_id: str
    revision: int
    goal: str
    constraints: tuple[str, ...]
    units: tuple[BlueprintUnit, ...]
    checks: tuple[BlueprintCheck, ...]
    status: str = BlueprintStatus.DRAFT.value
    blueprint_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != "1.0" or not self.project_id or self.revision < 1:
            raise ValueError("invalid blueprint identity")
        if self.status not in {item.value for item in BlueprintStatus}:
            raise ValueError("invalid blueprint status")
        self.validate()
        expected = _hash(self.as_dict(include_hash=False))
        if self.blueprint_hash and self.blueprint_hash != expected:
            raise ValueError("blueprint hash mismatch")
        object.__setattr__(self, "blueprint_hash", expected)

    @property
    def by_id(self) -> dict[str, BlueprintUnit]:
        return {item.unit_id: item for item in self.units}

    def validate(self) -> None:
        ids = [item.unit_id for item in self.units]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate unit id")
        owners: dict[str, str] = {}
        for unit in self.units:
            for path in unit.owns:
                if path in owners:
                    raise ValueError(f"ownership collision: {path}")
                owners[path] = unit.unit_id
            unknown = set(unit.depends_on) - set(ids)
            if unknown or unit.unit_id in unit.depends_on:
                raise ValueError(f"invalid dependency for {unit.unit_id}")
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = self.by_id

        def visit(unit_id: str) -> None:
            if unit_id in visiting:
                raise ValueError("blueprint dependency cycle")
            if unit_id in visited:
                return
            visiting.add(unit_id)
            for dependency in by_id[unit_id].depends_on:
                visit(dependency)
            visiting.remove(unit_id)
            visited.add(unit_id)

        for unit_id in ids:
            visit(unit_id)
        check_ids = [item.check_id for item in self.checks]
        if len(check_ids) != len(set(check_ids)) or set(check_ids) & set(ids):
            raise ValueError("duplicate check id")
        if self.status != BlueprintStatus.DRAFT.value:
            if not any(item.kind == UnitKind.ACCEPTANCE.value for item in self.checks):
                raise ValueError("frozen blueprint requires acceptance coverage")
            if not self.units:
                raise ValueError("frozen blueprint requires units")
        known = set(ids) | set(check_ids)
        for check in self.checks:
            if not set(check.depends_on) <= known or check.check_id in check.depends_on:
                raise ValueError(f"invalid check dependency: {check.check_id}")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version, "project_id": self.project_id, "revision": self.revision,
            "goal": self.goal, "constraints": list(self.constraints), "units": [item.as_dict() for item in self.units],
            "checks": [item.as_dict() for item in self.checks], "status": self.status,
        }
        return value | ({"blueprint_hash": self.blueprint_hash} if include_hash else {})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectBlueprint":
        return cls(
            str(value.get("schema_version", "")), str(value.get("project_id", "")), int(value.get("revision", 0)),
            str(value.get("goal", "")), _tuple(value.get("constraints")),
            tuple(BlueprintUnit.from_dict(item) for item in value.get("units", ())),
            tuple(BlueprintCheck.from_dict(item) for item in value.get("checks", ())),
            str(value.get("status", BlueprintStatus.DRAFT.value)), str(value.get("blueprint_hash", "")),
        )

    def freeze(self) -> "ProjectBlueprint":
        if self.status != BlueprintStatus.DRAFT.value:
            raise ValueError("only a draft blueprint may be frozen")
        return replace(self, status=BlueprintStatus.FROZEN.value, blueprint_hash="")


def apply_blueprint_edits(blueprint: ProjectBlueprint, edits: Iterable[Mapping[str, Any]]) -> ProjectBlueprint:
    """Apply one Agent design decision atomically to a preview, then validate/freeze."""
    if blueprint.status != BlueprintStatus.DRAFT.value:
        raise ValueError("design edits require a draft blueprint")
    goal, constraints = blueprint.goal, list(blueprint.constraints)
    units = {item.unit_id: item for item in blueprint.units}
    checks = {item.check_id: item for item in blueprint.checks}
    finish = False
    for raw in edits:
        operation = str(raw.get("operation", "")); payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("edit payload must be an object")
        if operation == "set_goal": goal = str(payload.get("goal", ""))
        elif operation == "add_constraint": constraints.append(str(payload.get("constraint", "")))
        elif operation == "add_unit":
            unit = BlueprintUnit.from_dict(payload)
            if unit.unit_id in units: raise ValueError("duplicate unit id")
            units[unit.unit_id] = unit
        elif operation == "update_unit":
            unit_id = str(payload.get("unit_id", ""))
            if unit_id not in units: raise ValueError("unknown unit")
            merged = units[unit_id].as_dict() | {key: value for key, value in payload.items() if key != "unit_id"}
            units[unit_id] = BlueprintUnit.from_dict(merged)
        elif operation == "remove_unit":
            units.pop(str(payload.get("unit_id", "")), None)
        elif operation == "add_check":
            check = BlueprintCheck.from_dict(payload)
            if check.check_id in checks: raise ValueError("duplicate check id")
            checks[check.check_id] = check
        elif operation == "remove_check": checks.pop(str(payload.get("check_id", "")), None)
        elif operation == "finish_design": finish = True
        else: raise ValueError(f"unsupported BlueprintEdit: {operation}")
    preview = ProjectBlueprint("1.0", blueprint.project_id, blueprint.revision, goal, tuple(constraints), tuple(units.values()), tuple(checks.values()))
    return preview.freeze() if finish else preview


@dataclass(frozen=True)
class FunctionInterface:
    name: str
    parameters: tuple[str, ...]
    defaults: int = 0

    def as_dict(self) -> dict[str, Any]: return {"name": self.name, "parameters": list(self.parameters), "defaults": self.defaults}


@dataclass(frozen=True)
class ClassInterface:
    name: str
    methods: tuple[FunctionInterface, ...]

    def as_dict(self) -> dict[str, Any]: return {"name": self.name, "methods": [item.as_dict() for item in self.methods]}


@dataclass(frozen=True)
class ObservedInterfaceManifest:
    module: str
    functions: tuple[FunctionInterface, ...] = ()
    classes: tuple[ClassInterface, ...] = ()
    imports: tuple[str, ...] = ()
    exports: tuple[str, ...] = ()
    main_guard: bool = False
    cli_options: tuple[str, ...] = ()
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        expected = _hash(self.as_dict(include_hash=False))
        if self.manifest_hash and self.manifest_hash != expected: raise ValueError("manifest hash mismatch")
        object.__setattr__(self, "manifest_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"module": self.module, "functions": [item.as_dict() for item in self.functions], "classes": [item.as_dict() for item in self.classes], "imports": list(self.imports), "exports": list(self.exports), "main_guard": self.main_guard, "cli_options": list(self.cli_options)}
        return value | ({"manifest_hash": self.manifest_hash} if include_hash else {})


def extract_python_interface(source: str, module: str) -> ObservedInterfaceManifest:
    tree = ast.parse(source, filename=module)
    functions: list[FunctionInterface] = []; classes: list[ClassInterface] = []; imports: set[str] = set(); exports: list[str] = []; options: set[str] = set(); main_guard = False

    def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInterface:
        args = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
        if node.args.vararg: args.append("*" + node.args.vararg.arg)
        args.extend(arg.arg for arg in node.args.kwonlyargs)
        if node.args.kwarg: args.append("**" + node.args.kwarg.arg)
        return FunctionInterface(node.name, tuple(args), len(node.args.defaults) + sum(item is not None for item in node.args.kw_defaults))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"): functions.append(signature(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = tuple(signature(item) for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"))
            classes.append(ClassInterface(node.name, methods))
        elif isinstance(node, ast.Import): imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom): imports.add(("." * node.level) + (node.module or ""))
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)): exports.extend(item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and "__main__" in ast.unparse(node.test): main_guard = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"add_argument", "add_parser"}:
            options.update(str(arg.value) for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"))
    return ObservedInterfaceManifest(module, tuple(sorted(functions, key=lambda item: item.name)), tuple(sorted(classes, key=lambda item: item.name)), tuple(sorted(imports)), tuple(sorted(exports)), main_guard, tuple(sorted(options)))


def interface_breaks(old: ObservedInterfaceManifest, new: ObservedInterfaceManifest, required: Iterable[str] = ()) -> tuple[str, ...]:
    failures: list[str] = []
    if old.module != new.module: failures.append("public module changed")
    new_functions = {item.name: item for item in new.functions}
    for before in old.functions:
        after = new_functions.get(before.name)
        if after is None: failures.append(f"public function removed: {before.name}")
        elif after.parameters[:len(before.parameters)] != before.parameters: failures.append(f"incompatible parameters: {before.name}")
    if old.main_guard and not new.main_guard: failures.append("entrypoint main guard removed")
    for option in set(old.cli_options) - set(new.cli_options): failures.append(f"CLI option removed: {option}")
    available = set(new.exports) | set(new_functions) | {item.name for item in new.classes} | set(new.cli_options)
    for item in required:
        if item not in available: failures.append(f"required interface missing: {item}")
    return tuple(failures)


@dataclass(frozen=True)
class UnitResult:
    unit_id: str; status: str; changed_files: tuple[str, ...] = (); produced_artifact_refs: tuple[str, ...] = (); observed_interfaces: tuple[str, ...] = (); test_evidence: tuple[str, ...] = (); provider_usage: tuple[tuple[str, str], ...] = (); duration: int = 0; error: str = ""; result_hash: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"SUCCEEDED", "FAILED", "BLOCKED", "NEEDS_REVIEW"}: raise ValueError("invalid UnitResult status")
        value = self.as_dict(include_hash=False); expected = _hash(value)
        if self.result_hash and self.result_hash != expected: raise ValueError("result hash mismatch")
        object.__setattr__(self, "result_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"unit_id": self.unit_id, "status": self.status, "changed_files": list(self.changed_files), "produced_artifact_refs": list(self.produced_artifact_refs), "observed_interfaces": list(self.observed_interfaces), "test_evidence": list(self.test_evidence), "provider_usage": dict(self.provider_usage), "duration": self.duration, "error": self.error}
        return value | ({"result_hash": self.result_hash} if include_hash else {})


@dataclass(frozen=True)
class FailureReport:
    unit_id: str; failure_type: str; owner_file: str = ""; owner_interface: str = ""; first_project_frame: str = ""; failed_check: str = ""; expected: str = ""; observed: str = ""; affected_units: tuple[str, ...] = (); suggested_action: str = ""; evidence_refs: tuple[str, ...] = (); failure_hash: str = ""

    def __post_init__(self) -> None:
        allowed = {"SYNTAX_ERROR", "IMPORT_ERROR", "NAME_ERROR", "INTERFACE_MISMATCH", "TEST_FAILURE", "RUNTIME_FAILURE", "SCOPE_VIOLATION", "PROVIDER_FAILURE", "UNKNOWN"}
        if self.failure_type not in allowed: raise ValueError("invalid failure type")
        expected = _hash(self.as_dict(include_hash=False))
        if self.failure_hash and self.failure_hash != expected: raise ValueError("failure hash mismatch")
        object.__setattr__(self, "failure_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"unit_id": self.unit_id, "failure_type": self.failure_type, "owner_file": self.owner_file, "owner_interface": self.owner_interface, "first_project_frame": self.first_project_frame, "failed_check": self.failed_check, "expected": self.expected, "observed": self.observed, "affected_units": list(self.affected_units), "suggested_action": self.suggested_action, "evidence_refs": list(self.evidence_refs)}
        return value | ({"failure_hash": self.failure_hash} if include_hash else {})


@dataclass(frozen=True)
class FileBundle:
    unit_id: str; files: tuple[tuple[str, str], ...]; summary: str = ""; needs_escalation: bool = False; escalation_reason: str = ""; schema_version: str = "1.0"; kind: str = "file_bundle"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FileBundle":
        if set(value) != {"schema_version", "kind", "unit_id", "files", "summary", "needs_escalation", "escalation_reason"} or value.get("schema_version") != "1.0" or value.get("kind") != "file_bundle": raise ValueError("invalid FileBundle envelope")
        files = tuple((_safe_path(str(item["path"])), str(item["content"])) for item in value.get("files", ()))
        if not files or len({path for path, _ in files}) != len(files): raise ValueError("FileBundle files must be non-empty and unique")
        return cls(str(value["unit_id"]), files, str(value["summary"]), bool(value["needs_escalation"]), str(value["escalation_reason"]))


@dataclass(frozen=True)
class PatchBundle:
    unit_id: str; patches: tuple[tuple[str, str, str], ...]; summary: str = ""; needs_escalation: bool = False; escalation_reason: str = ""; schema_version: str = "1.0"; kind: str = "patch_bundle"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatchBundle":
        if set(value) != {"schema_version", "kind", "unit_id", "patches", "summary", "needs_escalation", "escalation_reason"} or value.get("schema_version") != "1.0" or value.get("kind") != "patch_bundle": raise ValueError("invalid PatchBundle envelope")
        patches = tuple((_safe_path(str(item["path"])), str(item["find"]), str(item["replace"])) for item in value.get("patches", ()))
        if not patches or any(not find for _, find, _ in patches) or len({path for path, _, _ in patches}) != len(patches): raise ValueError("PatchBundle patches must be non-empty and path-unique")
        return cls(str(value["unit_id"]), patches, str(value["summary"]), bool(value["needs_escalation"]), str(value["escalation_reason"]))
