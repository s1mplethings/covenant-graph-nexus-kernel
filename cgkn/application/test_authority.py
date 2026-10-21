from __future__ import annotations

import ast
import csv
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_public_contract
from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw
from cgkn.application.software_project.catalog import get_case
from cgkn.application.verification import OraclePlanCompiler


_NON_PUBLIC_MARKERS = ("hidden", "benchmarks/real_project_generation", "traceback", "assertion source")


def _public_safe_value(value: Any) -> Any:
    """Drop evaluator-internal references before any Provider-visible projection."""

    if isinstance(value, Mapping):
        return {
            str(key): safe
            for key, item in value.items()
            if (safe := _public_safe_value(item)) not in (None, [], {})
        }
    if isinstance(value, (list, tuple)):
        return [safe for item in value if (safe := _public_safe_value(item)) is not None]
    if isinstance(value, str) and any(marker in value.casefold() for marker in _NON_PUBLIC_MARKERS):
        return None
    return value


class AssertionAuthority(str, Enum):
    TEST_CONTRACT_VALID = "TEST_CONTRACT_VALID"
    TEST_CONTRACT_CONFLICT = "TEST_CONTRACT_CONFLICT"
    TEST_CONTRACT_UNMAPPED_ASSERTION = "TEST_CONTRACT_UNMAPPED_ASSERTION"
    TEST_CONTRACT_UNPROVEN = "TEST_CONTRACT_UNPROVEN"
    TEST_INTERNAL_ASSERTION = "TEST_INTERNAL_ASSERTION"
    TEST_NON_NORMATIVE_ASSERTION = "TEST_NON_NORMATIVE_ASSERTION"
    PUBLIC_REQUIREMENT_UNCOVERED = "PUBLIC_REQUIREMENT_UNCOVERED"


@dataclass(frozen=True)
class ContractSemantic:
    requirement_ids: tuple[str, ...]
    subject: str
    operation: FrozenMapping
    observable: str
    normative_constraint: str
    expected_semantics: FrozenMapping
    normalization_rule: str = "NONE"
    error_semantics: FrozenMapping = field(default_factory=FrozenMapping)
    related_public_interfaces: tuple[str, ...] = ()
    verification_paths: tuple[str, ...] = ()
    authority: str = "NORMATIVE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_ids", tuple(sorted(set(self.requirement_ids))))
        object.__setattr__(self, "operation", self.operation if isinstance(self.operation, FrozenMapping) else FrozenMapping(self.operation))
        object.__setattr__(self, "expected_semantics", self.expected_semantics if isinstance(self.expected_semantics, FrozenMapping) else FrozenMapping(self.expected_semantics))
        object.__setattr__(self, "error_semantics", self.error_semantics if isinstance(self.error_semantics, FrozenMapping) else FrozenMapping(self.error_semantics))

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_ids": list(self.requirement_ids),
            "subject": self.subject,
            "operation": thaw(self.operation),
            "observable": self.observable,
            "normative_constraint": self.normative_constraint,
            "expected_semantics": thaw(self.expected_semantics),
            "normalization_rule": self.normalization_rule,
            "error_semantics": thaw(self.error_semantics),
            "related_public_interfaces": list(self.related_public_interfaces),
            "verification_paths": list(self.verification_paths),
            "authority": self.authority,
        }


@dataclass(frozen=True)
class PublicContractProjection:
    case_id: str
    semantics: tuple[ContractSemantic, ...]
    source_requirement_hash: str
    oracle_plan_hash: str | None = None
    schema_version: str = "1.0"

    @classmethod
    def for_case(cls, case_id: str) -> "PublicContractProjection":
        if case_id == "cli_csv_cleaner":
            public = compile_csv_public_contract()
            oracle = OraclePlanCompiler().compile_csv(public.obligations, CSV_DEPENDENCY_POLICY)
            obligation_by_id = {item.obligation_id: item for item in public.obligations.obligations}
            case = get_case(case_id)
            public_aliases = {
                f"REQ-CSV-ACCEPT-{index:02d}": f"REQ-{index:03d}"
                for index, _ in enumerate(case.public_acceptance, 1)
            }
            semantics: list[ContractSemantic] = []
            for spec in oracle.specs:
                obligations = tuple(obligation_by_id[item] for item in spec.obligation_ids)
                expected = thaw(spec.expected)
                if "stdout_csv" in expected:
                    observable, normalization = "stdout.csv_rows", "CSV_ROWS_WITH_HEADER_EXCLUDED"
                elif spec.oracle_id == "ORACLE-CSV-WHOLE-ROW":
                    observable, normalization = "output.csv", "CSV_HEADER_AND_DATA_ROWS"
                elif spec.oracle_id == "ORACLE-CSV-COLUMN-FILL":
                    observable, normalization = "output.csv", "CSV_HEADER_AND_DATA_ROWS"
                elif "stderr" in expected:
                    observable, normalization = "stderr", "NONEMPTY_TEXT"
                elif "stdout_contains" in expected:
                    observable, normalization = "stdout.contains", "CASE_SENSITIVE_CONTAINS"
                elif spec.oracle_id == "ORACLE-DOC-README":
                    observable, normalization = "documentation", "CONTAINS_PUBLIC_USAGE"
                elif spec.oracle_kind.value == "DEPENDENCY":
                    observable, normalization = "dependencies", "POLICY"
                elif spec.oracle_kind.value == "STATIC_PYTHON":
                    observable, normalization = "network", "POLICY"
                else:
                    observable, normalization = "public_check", "DETERMINISTIC_ORACLE"
                source_refs = tuple(sorted({ref for obligation in obligations for ref in obligation.source_requirement_refs}))
                aliases = tuple(sorted({public_aliases[ref] for ref in source_refs if ref in public_aliases}))
                semantics.append(ContractSemantic(
                    requirement_ids=tuple(spec.obligation_ids) + source_refs + aliases,
                    subject="; ".join(item.subject for item in obligations),
                    operation={"setup": thaw(spec.setup), "invoke": thaw(spec.operation)},
                    observable=observable,
                    normative_constraint="; ".join(item.subject for item in obligations),
                    expected_semantics=spec.expected,
                    normalization_rule=normalization,
                    error_semantics=_public_safe_value(thaw(spec.forbidden)),
                    related_public_interfaces=("python -m csv_cleaner",),
                    verification_paths=(spec.oracle_id,),
                ))
            return cls(
                case_id,
                tuple(semantics),
                public.obligations.as_dict()["obligation_set_hash"],
                oracle.plan_hash,
            )
        case = get_case(case_id)
        semantics = tuple(
            ContractSemantic(
                requirement_ids=(f"REQ-{index:03d}",),
                subject=text,
                operation={},
                observable="public_acceptance",
                normative_constraint=text,
                expected_semantics={"status": "SATISFIED", "details": "UNSPECIFIED"},
                normalization_rule="UNSPECIFIED",
                verification_paths=("external_acceptance",),
            )
            for index, text in enumerate(case.public_acceptance, 1)
        )
        source_hash = canonical_hash({"case_id": case_id, "public_goal": case.public_goal, "public_acceptance": list(case.public_acceptance)})
        return cls(case_id, semantics, source_hash)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicContractProjection":
        result = cls(
            case_id=str(value["case_id"]),
            semantics=tuple(ContractSemantic(
                requirement_ids=tuple(item.get("requirement_ids", ())),
                subject=str(item.get("subject", "")),
                operation=item.get("operation", {}),
                observable=str(item.get("observable", "")),
                normative_constraint=str(item.get("normative_constraint", "")),
                expected_semantics=item.get("expected_semantics", {}),
                normalization_rule=str(item.get("normalization_rule", "NONE")),
                error_semantics=item.get("error_semantics", {}),
                related_public_interfaces=tuple(item.get("related_public_interfaces", ())),
                verification_paths=tuple(item.get("verification_paths", ())),
                authority=str(item.get("authority", "NORMATIVE")),
            ) for item in value.get("semantics", ())),
            source_requirement_hash=str(value["source_requirement_hash"]),
            oracle_plan_hash=value.get("oracle_plan_hash"),
            schema_version=str(value.get("schema_version", "1.0")),
        )
        supplied = value.get("projection_hash")
        if supplied is not None and supplied != result.projection_hash:
            raise ValueError("public contract projection hash mismatch")
        return result

    def as_dict(self) -> dict[str, Any]:
        value = {
            "case_id": self.case_id,
            "semantics": [item.as_dict() for item in self.semantics],
            "source_requirement_hash": self.source_requirement_hash,
            "oracle_plan_hash": self.oracle_plan_hash,
            "schema_version": self.schema_version,
            "public_safe": True,
        }
        return value | {"projection_hash": canonical_hash(value)}

    @property
    def projection_hash(self) -> str:
        return self.as_dict()["projection_hash"]

    @property
    def known_requirement_ids(self) -> frozenset[str]:
        return frozenset(item for semantic in self.semantics for item in semantic.requirement_ids)


@dataclass(frozen=True)
class TestAssertionFinding:
    file: str
    line: int
    test_id: str
    expression: str
    observable: str
    expected: Any
    authority: AssertionAuthority
    requirement_ids: tuple[str, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file, "line": self.line, "test_id": self.test_id,
            "expression": self.expression, "observable": self.observable,
            "expected": self.expected, "authority": self.authority.value,
            "requirement_ids": list(self.requirement_ids), "reason": self.reason,
        }


@dataclass(frozen=True)
class TestAuthorityReceipt:
    status: str
    projection_hash: str
    findings: tuple[TestAssertionFinding, ...]
    covered_requirement_ids: tuple[str, ...]
    uncovered_requirement_ids: tuple[str, ...]
    schema_version: str = "1.0"

    @property
    def classifications(self) -> tuple[str, ...]:
        return tuple(sorted({item.authority.value for item in self.findings}))

    def as_dict(self) -> dict[str, Any]:
        value = {
            "status": self.status,
            "projection_hash": self.projection_hash,
            "findings": [item.as_dict() for item in self.findings],
            "classifications": list(self.classifications),
            "covered_requirement_ids": list(self.covered_requirement_ids),
            "uncovered_requirement_ids": list(self.uncovered_requirement_ids),
            "schema_version": self.schema_version,
        }
        return value | {"receipt_hash": canonical_hash(value)}

    @property
    def receipt_hash(self) -> str:
        return self.as_dict()["receipt_hash"]


@dataclass(frozen=True)
class _RawAssertion:
    file: str
    line: int
    test_id: str
    expression: str
    node: ast.AST
    bindings: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class _ExpressionBinding:
    expression: str


class _AssertionExtractor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.function = "<module>"
        self.items: list[_RawAssertion] = []
        self.bindings: dict[str, Any] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous, self.function = self.function, node.name
        previous_bindings, self.bindings = self.bindings, dict(self.bindings)
        self.generic_visit(node)
        self.bindings = previous_bindings
        self.function = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assert(self, node: ast.Assert) -> None:
        self.items.append(_RawAssertion(
            self.path, node.lineno, self.function, ast.unparse(node.test), node.test,
            tuple(sorted(self.bindings.items())),
        ))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _literal(node.value)
        bound: Any = value if value is not None else _ExpressionBinding(ast.unparse(node.value))
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.bindings[target.id] = bound
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        previous = dict(self.bindings)
        values = _literal(node.iter)
        if isinstance(node.target, ast.Name) and isinstance(values, (list, tuple)):
            self.bindings[node.target.id] = tuple(values)
        for item in node.body:
            self.visit(item)
        self.bindings = dict(previous)
        for item in node.orelse:
            self.visit(item)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            expression = ast.unparse(item.context_expr)
            if "pytest.raises" in expression:
                self.items.append(_RawAssertion(self.path, node.lineno, self.function, expression, item.context_expr))
        self.generic_visit(node)


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _resolved_literal(node: ast.AST, bindings: Mapping[str, Any]) -> Any:
    value = _literal(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name):
        value = bindings.get(node.id)
        return None if isinstance(value, _ExpressionBinding) else value
    if isinstance(node, (ast.List, ast.Tuple)):
        values = []
        for item in node.elts:
            resolved = _resolved_literal(item, bindings)
            if resolved is None and not (isinstance(item, ast.Constant) and item.value is None):
                return None
            values.append(resolved)
        return values if isinstance(node, ast.List) else tuple(values)
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                return None
            key = _resolved_literal(key_node, bindings)
            item = _resolved_literal(value_node, bindings)
            if key is None or (item is None and not (isinstance(value_node, ast.Constant) and value_node.value is None)):
                return None
            result[key] = item
        return result
    return None


def _comparison(node: ast.AST, bindings: Mapping[str, Any] | None = None) -> tuple[str, Any, str]:
    bindings = bindings or {}
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        left, right = node.left, node.comparators[0]
        left_literal, right_literal = _resolved_literal(left, bindings), _resolved_literal(right, bindings)
        operator = type(node.ops[0]).__name__
        if operator in {"In", "NotIn"} and left_literal is not None:
            return ast.unparse(right), left_literal, operator
        if right_literal is not None:
            return ast.unparse(left), right_literal, operator
        if left_literal is not None:
            return ast.unparse(right), left_literal, operator
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"endswith", "startswith"}:
        return ast.unparse(node.func.value), _literal(node.args[0]) if node.args else None, node.func.attr
    return ast.unparse(node), None, "UNKNOWN"


def _csv_rows(text: str) -> list[list[str]] | None:
    try:
        return list(csv.reader(io.StringIO(text)))
    except (csv.Error, TypeError):
        return None


class TestAuthorityFirewall:
    """Conservative, deterministic gate for externally observable test assertions."""

    _FAILURES = {
        AssertionAuthority.TEST_CONTRACT_CONFLICT,
        AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION,
        AssertionAuthority.TEST_CONTRACT_UNPROVEN,
        AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION,
        AssertionAuthority.PUBLIC_REQUIREMENT_UNCOVERED,
    }

    def validate(
        self,
        sources: Mapping[str, str],
        projection: PublicContractProjection,
        *,
        required_requirement_ids: tuple[str, ...] = (),
        declared_manifest: tuple[Mapping[str, Any], ...] = (),
    ) -> TestAuthorityReceipt:
        findings: list[TestAssertionFinding] = []
        for declaration in declared_manifest:
            unknown = tuple(sorted(set(map(str, declaration.get("requirement_ids", ()))) - projection.known_requirement_ids))
            if unknown:
                findings.append(TestAssertionFinding(
                    str(declaration.get("file", "<manifest>")), int(declaration.get("line", 0)),
                    str(declaration.get("test_id", "<manifest>")), "manifest requirement_ids",
                    "manifest", list(unknown), AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION,
                    unknown, "manifest references unknown public requirement IDs",
                ))
        for path, source in sorted(sources.items()):
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError as exc:
                findings.append(TestAssertionFinding(path, exc.lineno or 0, "<parse>", "syntax error", "test_source", None, AssertionAuthority.TEST_CONTRACT_UNPROVEN, (), str(exc)))
                continue
            extractor = _AssertionExtractor(path)
            extractor.visit(tree)
            findings.extend(self._classify(item, projection) for item in extractor.items)

        covered = {
            requirement_id
            for item in findings
            if item.authority is AssertionAuthority.TEST_CONTRACT_VALID
            for requirement_id in item.requirement_ids
        }
        covered.update(
            requirement_id
            for semantic in projection.semantics
            if semantic.verification_paths
            for requirement_id in semantic.requirement_ids
        )
        required = set(required_requirement_ids)
        unknown_required = required - projection.known_requirement_ids
        uncovered = tuple(sorted((required - covered) | unknown_required))
        findings.extend(
            TestAssertionFinding("<coverage>", 0, "<coverage>", requirement_id, "coverage", None, AssertionAuthority.PUBLIC_REQUIREMENT_UNCOVERED, (requirement_id,), "no valid generated or deterministic verification path")
            for requirement_id in uncovered
        )
        status = "FAIL" if any(item.authority in self._FAILURES for item in findings) else "PASS"
        return TestAuthorityReceipt(status, projection.projection_hash, tuple(findings), tuple(sorted(covered)), uncovered)

    def _classify(self, raw: _RawAssertion, projection: PublicContractProjection) -> TestAssertionFinding:
        bindings = dict(raw.bindings)
        actual, expected, operator = _comparison(raw.node, bindings)
        origin = ""
        match = re.match(r"([A-Za-z_]\w*)", actual)
        if match and isinstance(bindings.get(match.group(1)), _ExpressionBinding):
            origin = bindings[match.group(1)].expression
        expression_lower = (raw.expression + " " + origin).lower()
        lowered = (raw.expression + " " + raw.test_id).lower()
        external_markers = ("stdout", "stderr", "returncode", "subprocess", "read_text", "preview", "output", "csv.reader", "header", "fieldnames")
        if "pytest.raises" in lowered and not any(marker in lowered for marker in external_markers):
            return self._finding(raw, "internal.exception", expected, AssertionAuthority.TEST_INTERNAL_ASSERTION, (), "implementation-local robustness assertion")
        if not any(marker in lowered for marker in external_markers):
            return self._finding(raw, "internal", expected, AssertionAuthority.TEST_INTERNAL_ASSERTION, (), "does not constrain an external observable")

        if "stdout" in expression_lower:
            stdout_semantics = [item for item in projection.semantics if item.observable.startswith("stdout")]
            exact = [item for item in stdout_semantics if "stdout_exact" in thaw(item.expected_semantics)]
            if exact:
                values = {thaw(item.expected_semantics)["stdout_exact"] for item in exact}
                requirement_ids = tuple(sorted({identifier for item in exact for identifier in item.requirement_ids}))
                authority = AssertionAuthority.TEST_CONTRACT_VALID if expected in values else AssertionAuthority.TEST_CONTRACT_CONFLICT
                return self._finding(raw, "stdout.raw_text", expected, authority, requirement_ids, "exact stdout is explicitly specified by the canonical contract")
            unspecified = [
                item for item in stdout_semantics
                if item.normalization_rule == "UNSPECIFIED"
                or "UNSPECIFIED" in thaw(item.expected_semantics).values()
            ]
            if unspecified:
                requirement_ids = tuple(sorted({identifier for item in unspecified for identifier in item.requirement_ids}))
                return self._finding(raw, "stdout", expected, AssertionAuthority.TEST_CONTRACT_UNPROVEN, requirement_ids, "canonical contract leaves this stdout detail unspecified")

        preview = next((item for item in projection.semantics if "OBL-CSV-PREVIEW" in item.requirement_ids), None)
        if "preview" in lowered and ("stdout" in expression_lower or "preview_rows" in expression_lower) and operator not in {"In", "NotIn"} and preview is not None:
            requirement_ids = tuple(item for item in preview.requirement_ids if item.startswith("OBL-"))
            preview_expected = thaw(preview.expected_semantics)
            expected_rows = preview_expected.get("stdout_csv", {}).get("rows", [])
            header = thaw(preview.operation).get("setup", {}).get("header")
            if origin:
                try:
                    origin_node = ast.parse(origin, mode="eval").body
                except SyntaxError:
                    origin_node = None
                if isinstance(origin_node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)) and any(
                    generator.ifs for generator in origin_node.generators
                ):
                    return self._finding(
                        raw,
                        "stdout.csv_rows",
                        expected,
                        AssertionAuthority.TEST_CONTRACT_UNPROVEN,
                        requirement_ids,
                        "parsed preview assertion filters observed CSV rows before comparison",
                    )
            if isinstance(expected, str):
                rows = _csv_rows(expected)
                if rows and header and rows[0] == header:
                    return self._finding(raw, "stdout.csv_rows", expected, AssertionAuthority.TEST_CONTRACT_CONFLICT, requirement_ids, "preview contract excludes the CSV header")
                if "stdout_exact" in preview_expected:
                    authority = AssertionAuthority.TEST_CONTRACT_VALID if expected == preview_expected["stdout_exact"] else AssertionAuthority.TEST_CONTRACT_CONFLICT
                    return self._finding(raw, "stdout.raw_text", expected, authority, requirement_ids, "exact text is explicitly specified by the canonical contract")
                if rows != expected_rows:
                    return self._finding(raw, "stdout.csv_rows", expected, AssertionAuthority.TEST_CONTRACT_CONFLICT, requirement_ids, "preview rows contradict the canonical oracle")
                return self._finding(raw, "stdout.raw_text", expected, AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION, requirement_ids, "raw newline/spacing is unspecified; compare parsed CSV rows")
            if isinstance(expected, list):
                rows = expected
                if rows and all(isinstance(item, str) for item in rows):
                    parsed: list[list[str]] = []
                    for line in rows:
                        parsed.extend(_csv_rows(line) or [])
                    rows = parsed
                if rows and header and rows[0] == header:
                    return self._finding(raw, "stdout.csv_rows", expected, AssertionAuthority.TEST_CONTRACT_CONFLICT, requirement_ids, "preview contract excludes the CSV header")
                authority = AssertionAuthority.TEST_CONTRACT_VALID if rows == expected_rows else AssertionAuthority.TEST_CONTRACT_CONFLICT
                return self._finding(raw, "stdout.csv_rows", expected, authority, requirement_ids, "parsed preview rows checked against canonical oracle")
            if operator in {"endswith", "startswith"} and expected in {"\n", "\r\n"}:
                return self._finding(raw, "stdout.newline", expected, AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION, requirement_ids, "newline style is unspecified")
            return self._finding(raw, "stdout", expected, AssertionAuthority.TEST_CONTRACT_UNPROVEN, requirement_ids, "external preview assertion could not be proven from canonical semantics")

        if ".exists" in expression_lower:
            candidates = [
                item for item in projection.semantics
                if thaw(item.expected_semantics).get("output_created") is True
            ]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            if candidates:
                return self._finding(raw, "output.exists", True, AssertionAuthority.TEST_CONTRACT_VALID, requirement_ids, "output creation is required by the canonical oracle")

        if "stdout" in expression_lower and operator in {"In", "NotIn"} and isinstance(expected, (str, list, tuple)):
            candidates = [item for item in projection.semantics if "stdout_contains" in thaw(item.expected_semantics)]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            allowed = {text for item in candidates for text in thaw(item.expected_semantics).get("stdout_contains", [])}
            checked = set(expected) if isinstance(expected, (list, tuple)) else {expected}
            authority = AssertionAuthority.TEST_CONTRACT_VALID if operator == "In" and checked <= allowed else AssertionAuthority.TEST_CONTRACT_CONFLICT
            return self._finding(raw, "stdout.contains", expected, authority, requirement_ids, "stdout token checked against canonical contains semantics")

        if "read_text" in expression_lower and isinstance(expected, str):
            candidates = [item for item in projection.semantics if item.observable == "output.csv"]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            return self._finding(raw, "file.raw_text", expected, AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION, requirement_ids, "CSV file bytes and newline style are not exact-text public semantics")

        if ("csv.reader" in expression_lower or "read_csv" in expression_lower) and actual.endswith("[0]") and isinstance(expected, list):
            candidates = [item for item in projection.semantics if item.observable == "output.csv"]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            headers = {tuple(thaw(item.expected_semantics).get("header", [])) for item in candidates}
            authority = AssertionAuthority.TEST_CONTRACT_VALID if tuple(expected) in headers else AssertionAuthority.TEST_CONTRACT_UNPROVEN
            return self._finding(raw, "csv.header", expected, authority, requirement_ids, "parsed CSV header checked against a canonical public example")

        if ("csv.reader" in expression_lower or "read_csv" in expression_lower) and isinstance(expected, list):
            candidates = [item for item in projection.semantics if item.observable == "output.csv"]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            expected_documents = []
            expected_rows = []
            for item in candidates:
                semantic = thaw(item.expected_semantics)
                expected_documents.append([semantic.get("header"), *semantic.get("rows", [])])
                expected_rows.append(semantic.get("rows", []))
            matches_document = expected in expected_documents
            matches_data_slice = "[1:]" in actual and expected in expected_rows
            authority = AssertionAuthority.TEST_CONTRACT_VALID if matches_document or matches_data_slice else AssertionAuthority.TEST_CONTRACT_UNPROVEN
            return self._finding(raw, "output.csv", expected, authority, requirement_ids, "parsed CSV document checked against a canonical public example")

        if "returncode" in expression_lower:
            candidates = [item for item in projection.semantics if "exit_code" in thaw(item.expected_semantics)]
            if not candidates:
                return self._finding(raw, "returncode", expected, AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION, (), "no public return-code requirement")
            expected_values = {thaw(item.expected_semantics).get("exit_code") for item in candidates}
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            valid = expected in expected_values or (expected != 0 and "nonzero" in expected_values)
            return self._finding(raw, "returncode", expected, AssertionAuthority.TEST_CONTRACT_VALID if valid else AssertionAuthority.TEST_CONTRACT_CONFLICT, requirement_ids, "return code checked against canonical oracle")

        if "header" in expression_lower or "fieldnames" in expression_lower:
            candidates = [item for item in projection.semantics if "OBL-CSV-HEADER-PRESERVATION" in item.requirement_ids]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            headers = [thaw(item.operation).get("setup", {}).get("header") for item in candidates]
            headers = [item for item in headers if item]
            if not candidates or not headers:
                return self._finding(raw, "csv.header", expected, AssertionAuthority.TEST_CONTRACT_UNPROVEN, requirement_ids, "canonical header value is unavailable")
            authority = AssertionAuthority.TEST_CONTRACT_VALID if expected in headers else AssertionAuthority.TEST_CONTRACT_CONFLICT
            return self._finding(raw, "csv.header", expected, authority, requirement_ids, "header checked against canonical oracle setup")

        if "stderr" in expression_lower:
            candidates = [item for item in projection.semantics if "stderr" in thaw(item.expected_semantics)]
            requirement_ids = tuple(sorted({identifier for item in candidates for identifier in item.requirement_ids if identifier.startswith("OBL-")}))
            if not candidates:
                return self._finding(raw, "stderr", expected, AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION, (), "no public stderr requirement")
            if operator in {"Eq", "NotEq"} and isinstance(expected, str) and expected:
                return self._finding(raw, "stderr.raw_text", expected, AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION, requirement_ids, "contract requires non-empty error text, not exact wording")
            return self._finding(raw, "stderr", expected, AssertionAuthority.TEST_CONTRACT_VALID, requirement_ids, "bounded by canonical error semantics")

        return self._finding(raw, "external", expected, AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION, (), "externally observable assertion has no deterministic public-contract mapping")

    @staticmethod
    def _finding(raw: _RawAssertion, observable: str, expected: Any, authority: AssertionAuthority, requirement_ids: tuple[str, ...], reason: str) -> TestAssertionFinding:
        return TestAssertionFinding(raw.file, raw.line, raw.test_id, raw.expression, observable, expected, authority, requirement_ids, reason)


class RepairMonotonicityGuard:
    """Prevent a stable conformant implementation hash from being re-owned by tests."""

    def __init__(self) -> None:
        self._statuses: dict[tuple[str, str], str] = {}

    def record(self, requirement_id: str, implementation_hash: str, status: str) -> None:
        if status not in {"CONFORMANT", "NONCONFORMANT", "UNKNOWN"}:
            raise ValueError("invalid canonical conformance status")
        key = (requirement_id, implementation_hash)
        before = self._statuses.get(key)
        if before == "CONFORMANT" and status == "NONCONFORMANT":
            raise ValueError("canonical conformance cannot regress without new canonical evidence")
        self._statuses[key] = status

    def route(self, requirement_id: str, implementation_hash: str, test_authority: AssertionAuthority) -> str:
        if self._statuses.get((requirement_id, implementation_hash)) == "CONFORMANT" and test_authority in {
            AssertionAuthority.TEST_CONTRACT_CONFLICT,
            AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION,
            AssertionAuthority.TEST_CONTRACT_UNPROVEN,
            AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION,
        }:
            return "TESTS"
        return "AMBIGUOUS"


class ContractAwareFailureRouter:
    """Adjudicate ownership only from canonical status plus firewall evidence."""

    @staticmethod
    def route(
        implementation_status: str,
        receipt: TestAuthorityReceipt,
        *,
        implementation_unit_id: str,
        tests_unit_id: str,
    ) -> str:
        if implementation_status == "NONCONFORMANT" and receipt.status == "PASS":
            return implementation_unit_id
        decisive_test_failure = {
            AssertionAuthority.TEST_CONTRACT_CONFLICT,
            AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION,
            AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION,
            AssertionAuthority.PUBLIC_REQUIREMENT_UNCOVERED,
        }
        if receipt.status == "FAIL" and any(item.authority in decisive_test_failure for item in receipt.findings):
            return tests_unit_id
        return "CONTRACT_ATTRIBUTION_AMBIGUOUS"
