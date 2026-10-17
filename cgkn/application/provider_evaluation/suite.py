from __future__ import annotations

import ast
import builtins
import inspect
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import BenchmarkBudget, ProviderBenchmarkCase, canonical_hash


BENCHMARK_VERSION = "provider-micro-suite-v1"
CODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"const": "solution.py"},
        "content": {"type": "string", "minLength": 1, "maxLength": 6000},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}
STRUCTURED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "result": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["result"],
    "additionalProperties": False,
}
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "capability": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                },
                "required": ["id", "capability", "depends_on"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["nodes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class BenchmarkValidation:
    functional_valid: bool
    interface_valid: bool = True
    scope_valid: bool = True
    repair_required: bool = False


def _case(
    case_id: str,
    task_class: str,
    role: str,
    response_schema: Mapping[str, Any],
    facts: Sequence[str],
    validation: Sequence[str],
) -> ProviderBenchmarkCase:
    budget = BenchmarkBudget(timeout_seconds=90, max_input_tokens=3000, max_output_tokens=1600)
    return ProviderBenchmarkCase(
        case_id=case_id,
        task_class=task_class,
        role=role,
        input_contract={"prompt_facts": {"type": "array", "items": {"type": "string"}}},
        expected_output_contract=dict(response_schema),
        budget=budget,
        timeout=budget.timeout_seconds,
        validation=tuple(validation),
        risk="LOW",
        benchmark_version=BENCHMARK_VERSION,
        prompt_facts=tuple(facts),
    )


def benchmark_cases() -> tuple[ProviderBenchmarkCase, ...]:
    return (
        _case("structured-identifiers", "structured.output", "worker", STRUCTURED_SCHEMA, (
            "Input labels in order: '  Alpha Project  ', 'Beta_ITEM', 'alpha project'.",
            "Return result with each label stripped, lowercased, spaces and underscores replaced by one hyphen; keep duplicates and order.",
        ), ("schema", "required_fields", "unknown_fields", "exact_result")),
        _case("structured-dependencies", "structured.output", "worker", STRUCTURED_SCHEMA, (
            "Input dependency names: 'urllib3', 'Requests', 'requests', 'certifi'.",
            "Return result as unique lowercase dependency names sorted lexically.",
        ), ("schema", "required_fields", "unknown_fields", "exact_result")),
        _case("composition-feature", "agent.composition", "agent", PLAN_SCHEMA, (
            "Plan a tiny feature with exactly these nodes: inspect(workspace.inspect), implement(project.file.patch), test(local.python-test).",
            "implement depends on inspect; test depends on implement; no other nodes.",
        ), ("schema", "node_set", "dependency_order")),
        _case("composition-repair", "agent.composition", "agent", PLAN_SCHEMA, (
            "Plan a bounded repair with exactly these nodes: inspect(workspace.inspect), repair(project.file.patch), verify(local.python-test).",
            "repair depends on inspect; verify depends on repair; no other nodes.",
        ), ("schema", "node_set", "dependency_order")),
        _case("codegen-normalize", "worker.codegen", "worker", CODE_SCHEMA, (
            "Create solution.py defining normalize_identifier(text).",
            "It returns stripped lowercase text with every maximal run of non-alphanumeric characters replaced by one hyphen, with leading/trailing hyphens removed.",
            "Use only Python standard syntax and no imports.",
        ), ("schema", "syntax", "function_contract", "interface", "scope")),
        _case("codegen-clamp", "worker.codegen", "worker", CODE_SCHEMA, (
            "Create solution.py defining clamp_int(value, lower, upper).",
            "Raise ValueError when lower > upper; otherwise return value limited inclusively to the bounds.",
            "Use only Python standard syntax and no imports.",
        ), ("schema", "syntax", "function_contract", "interface", "scope")),
        _case("repair-average", "worker.repair", "worker", CODE_SCHEMA, (
            "Existing solution.py: def average(values): return sum(values) / (len(values) - 1)",
            "Failure evidence: average([2, 4]) returned 6.0; expected 3.0. Empty input must raise ValueError.",
            "Return the complete repaired solution.py; preserve the function name and one-argument interface; no imports.",
        ), ("schema", "syntax", "repair_correctness", "interface", "scope")),
        _case("repair-unique", "worker.repair", "worker", CODE_SCHEMA, (
            "Existing solution.py: def unique_ordered(values): return list(set(values))",
            "Failure evidence: unique_ordered(['b','a','b']) did not deterministically preserve first-seen order; expected ['b','a'].",
            "Return the complete repaired solution.py; preserve the function name and one-argument interface; no imports.",
        ), ("schema", "syntax", "repair_correctness", "interface", "scope")),
    )


def suite_hash(cases: Sequence[ProviderBenchmarkCase] | None = None) -> str:
    rows = cases or benchmark_cases()
    return canonical_hash({"benchmark_version": BENCHMARK_VERSION, "cases": [row.as_dict() for row in rows]})


def system_prompt(task_class: str) -> str:
    if task_class == "agent.composition":
        return "Return only the requested JSON plan. Use only supplied public facts. Do not add nodes, source code, credentials, or claims about hidden tests."
    if task_class in {"worker.codegen", "worker.repair"}:
        return "Return only the requested JSON object. The content field must contain complete Python source. Do not use imports, shell, network, filesystem access, or hidden-test assumptions."
    return "Return only the requested JSON object, exactly matching the schema and public facts."


class _SafeCode(ast.NodeVisitor):
    _forbidden = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Lambda, ast.With, ast.AsyncWith, ast.Try, ast.Delete, ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom, ast.Await)
    _calls = {"len", "min", "max", "sum", "str", "int", "float", "bool", "ValueError", "range", "enumerate"}

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, self._forbidden):
            raise ValueError(f"forbidden syntax: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise ValueError("private attribute access is forbidden")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id not in self._calls:
            raise ValueError(f"call is not allowlisted: {node.func.id}")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if not isinstance(node.exc, ast.Call) or not isinstance(node.exc.func, ast.Name) or node.exc.func.id != "ValueError":
            raise ValueError("only ValueError may be raised")
        self.generic_visit(node)


def _load_function(value: Mapping[str, Any], name: str, parameters: Sequence[str]):
    if value.get("path") != "solution.py" or not isinstance(value.get("content"), str):
        return None, False, False
    try:
        tree = ast.parse(value["content"], filename="solution.py")
        _SafeCode().visit(tree)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if len(functions) != 1 or functions[0].name != name:
            return None, False, True
        namespace: dict[str, Any] = {}
        safe_builtins = {key: getattr(builtins, key) for key in ("len", "min", "max", "sum", "str", "int", "float", "bool", "ValueError", "range", "enumerate")}
        exec(compile(tree, "solution.py", "exec"), {"__builtins__": safe_builtins}, namespace)
        function = namespace[name]
        interface = list(inspect.signature(function).parameters) == list(parameters)
        return function, interface, True
    except Exception:
        return None, False, True


def evaluate(case_id: str, value: Mapping[str, Any]) -> BenchmarkValidation:
    if case_id == "structured-identifiers":
        return BenchmarkValidation(value.get("result") == ["alpha-project", "beta-item", "alpha-project"])
    if case_id == "structured-dependencies":
        return BenchmarkValidation(value.get("result") == ["certifi", "requests", "urllib3"])
    if case_id in {"composition-feature", "composition-repair"}:
        expected = (
            {"inspect": ("workspace.inspect", ()), "implement": ("project.file.patch", ("inspect",)), "test": ("local.python-test", ("implement",))}
            if case_id == "composition-feature"
            else {"inspect": ("workspace.inspect", ()), "repair": ("project.file.patch", ("inspect",)), "verify": ("local.python-test", ("repair",))}
        )
        rows = value.get("nodes")
        if not isinstance(rows, list):
            return BenchmarkValidation(False)
        actual = {
            str(row.get("id")): (str(row.get("capability")), tuple(row.get("depends_on", ())))
            for row in rows if isinstance(row, Mapping)
        }
        return BenchmarkValidation(actual == expected)
    definitions = {
        "codegen-normalize": ("normalize_identifier", ("text",)),
        "codegen-clamp": ("clamp_int", ("value", "lower", "upper")),
        "repair-average": ("average", ("values",)),
        "repair-unique": ("unique_ordered", ("values",)),
    }
    name, parameters = definitions[case_id]
    function, interface_valid, scope_valid = _load_function(value, name, parameters)
    functional = False
    if function is not None and interface_valid:
        try:
            if case_id == "codegen-normalize":
                functional = function("  Hello__World! ") == "hello-world" and function("---A---") == "a" and function("") == ""
            elif case_id == "codegen-clamp":
                functional = (function(5, 1, 3), function(-1, 0, 2), function(1, 0, 2)) == (3, 0, 1)
                try:
                    function(0, 2, 1)
                except ValueError:
                    functional = functional and True
                else:
                    functional = False
            elif case_id == "repair-average":
                functional = function([2, 4]) == 3 and function([3]) == 3
                try:
                    function([])
                except ValueError:
                    functional = functional and True
                else:
                    functional = False
            else:
                functional = function(["b", "a", "b", "c", "a"]) == ["b", "a", "c"] and function([]) == []
        except Exception:
            functional = False
    return BenchmarkValidation(
        functional_valid=functional,
        interface_valid=interface_valid,
        scope_valid=scope_valid,
        repair_required=case_id.startswith("repair-"),
    )
