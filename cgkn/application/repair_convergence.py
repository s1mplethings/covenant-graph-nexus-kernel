from __future__ import annotations

import ast
import csv
import difflib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from cgkn.application.materialization import materialize_json
from cgkn.application.requirements.obligation import canonical_hash


_PUBLIC_SAFE_FORBIDDEN = ("hidden acceptance", "hidden assertion", "hidden traceback")


def _canonical_json(value: Any) -> str:
    return json.dumps(materialize_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


class RepairProgress(str, Enum):
    FIXED = "FIXED"
    PROGRESSED = "PROGRESSED"
    NO_PROGRESS = "NO_PROGRESS"
    REGRESSED = "REGRESSED"
    INCOMPARABLE = "INCOMPARABLE"


class RepairCandidateStatus(str, Enum):
    CREATED = "CREATED"
    PATCH_VALID = "PATCH_VALID"
    STAGED = "STAGED"
    TARGET_VALIDATING = "TARGET_VALIDATING"
    TARGET_PASS = "TARGET_PASS"
    TARGET_FAIL = "TARGET_FAIL"
    REGRESSION_PASS = "REGRESSION_PASS"
    COMMITTED = "COMMITTED"
    DISCARDED = "DISCARDED"


@dataclass(frozen=True)
class RepairFailureFingerprint:
    requirement_ids: tuple[str, ...]
    owner_unit_id: str
    check_id: str
    observable: str
    normalized_input: str
    normalized_expected: str
    normalized_actual: str
    failure_kind: str
    relevant_interface_id: str
    relevant_source_locator: str
    baseline_hash: str
    fingerprint_hash: str = ""

    def __post_init__(self) -> None:
        value = self.as_dict(include_hash=False)
        expected = canonical_hash(value)
        if self.fingerprint_hash and self.fingerprint_hash != expected:
            raise ValueError("repair failure fingerprint hash mismatch")
        object.__setattr__(self, "fingerprint_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "requirement_ids": list(self.requirement_ids),
            "owner_unit_id": self.owner_unit_id,
            "check_id": self.check_id,
            "observable": self.observable,
            "normalized_input": self.normalized_input,
            "normalized_expected": self.normalized_expected,
            "normalized_actual": self.normalized_actual,
            "failure_kind": self.failure_kind,
            "relevant_interface_id": self.relevant_interface_id,
            "relevant_source_locator": self.relevant_source_locator,
            "baseline_hash": self.baseline_hash,
        }
        return value | ({"fingerprint_hash": self.fingerprint_hash} if include_hash else {})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepairFailureFingerprint":
        return cls(
            tuple(str(item) for item in value.get("requirement_ids", ())),
            str(value.get("owner_unit_id", "")),
            str(value.get("check_id", "")),
            str(value.get("observable", "")),
            str(value.get("normalized_input", "null")),
            str(value.get("normalized_expected", "null")),
            str(value.get("normalized_actual", "null")),
            str(value.get("failure_kind", "ASSERTION_MISMATCH")),
            str(value.get("relevant_interface_id", "")),
            str(value.get("relevant_source_locator", "")),
            str(value.get("baseline_hash", "")),
            str(value.get("fingerprint_hash", "")),
        )


@dataclass(frozen=True)
class RepairTargetSpec:
    fingerprint: RepairFailureFingerprint
    operation: str
    setup: str
    expected: str
    target_hash: str = ""

    def __post_init__(self) -> None:
        expected_hash = canonical_hash(self.as_dict(include_hash=False))
        if self.target_hash and self.target_hash != expected_hash:
            raise ValueError("repair target hash mismatch")
        object.__setattr__(self, "target_hash", expected_hash)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "fingerprint": self.fingerprint.as_dict(),
            "operation": self.operation,
            "setup": self.setup,
            "expected": self.expected,
        }
        return value | ({"target_hash": self.target_hash} if include_hash else {})


@dataclass(frozen=True)
class RepairValidationReceipt:
    status: str
    target_hash: str
    fingerprint: RepairFailureFingerprint | None
    return_code: int | None
    stdout: str
    stderr: str
    validation_hash: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "HARNESS_FAILURE"}:
            raise ValueError("invalid repair validation status")
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.validation_hash and self.validation_hash != expected:
            raise ValueError("repair validation hash mismatch")
        object.__setattr__(self, "validation_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "status": self.status,
            "target_hash": self.target_hash,
            "fingerprint": self.fingerprint.as_dict() if self.fingerprint else None,
            "return_code": self.return_code,
            "stdout": self.stdout[-2000:],
            "stderr": self.stderr[-2000:],
        }
        return value | ({"validation_hash": self.validation_hash} if include_hash else {})


@dataclass
class RepairCandidateState:
    unit_id: str
    baseline_hash: str
    status: str = RepairCandidateStatus.CREATED.value
    transitions: list[str] = field(default_factory=lambda: [RepairCandidateStatus.CREATED.value])

    def transition(self, status: RepairCandidateStatus) -> None:
        self.status = status.value
        self.transitions.append(status.value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "baseline_hash": self.baseline_hash,
            "status": self.status,
            "transitions": list(self.transitions),
        }


@dataclass(frozen=True)
class RepairAttemptEvidence:
    attempt: int
    progress: RepairProgress
    changed_paths: tuple[str, ...]
    diff: str
    validation: RepairValidationReceipt

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "progress": self.progress.value,
            "changed_paths": list(self.changed_paths),
            "diff": self.diff,
            "validation": self.validation.as_dict(),
        }


@dataclass(frozen=True)
class RepairEvidencePacket:
    project_goal: str
    unit_purpose: str
    canonical_public_requirement: str
    fingerprint: RepairFailureFingerprint
    exact_reproduction: dict[str, Any]
    relevant_files: dict[str, str]
    relevant_functions: tuple[str, ...]
    public_interfaces: tuple[str, ...]
    previous_attempt: RepairAttemptEvidence | None = None
    failure_execution_slice: Mapping[str, Any] | None = None
    contrastive_public_evidence: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "project_goal": self.project_goal,
            "unit_purpose": self.unit_purpose,
            "canonical_public_requirement": self.canonical_public_requirement,
            "requirement_ids": list(self.fingerprint.requirement_ids),
            "exact_observable": self.fingerprint.observable,
            "minimal_reproduction_input": _json_value(self.fingerprint.normalized_input),
            "expected_public_result": _json_value(self.fingerprint.normalized_expected),
            "actual_public_result": _json_value(self.fingerprint.normalized_actual),
            "failure_kind": self.fingerprint.failure_kind,
            "relevant_interface_id": self.fingerprint.relevant_interface_id,
            "relevant_source_locator": self.fingerprint.relevant_source_locator,
            "exact_reproduction": materialize_json(self.exact_reproduction),
            "relevant_implementation_files": self.relevant_files,
            "relevant_functions": list(self.relevant_functions),
            "public_interfaces": list(self.public_interfaces),
            "explicit_repair_objective": (
                "Change the canonical observable from actual_public_result to expected_public_result. "
                "Do not repeat a previous ineffective strategy."
            ),
            "previous_failed_attempt": self.previous_attempt.as_dict() if self.previous_attempt else None,
        }
        if self.failure_execution_slice is not None:
            value["failure_execution_slice"] = materialize_json(self.failure_execution_slice)
        if self.contrastive_public_evidence is not None:
            value["contrastive_public_evidence"] = materialize_json(self.contrastive_public_evidence)
        text = _canonical_json(value).casefold()
        if any(marker in text for marker in _PUBLIC_SAFE_FORBIDDEN):
            raise ValueError("repair evidence packet contains forbidden hidden material")
        return value


@dataclass(frozen=True)
class FailureExecutionSlice:
    """Public-reproduction execution path, limited to project-owned source."""

    operation_hash: str
    executed_files: tuple[str, ...]
    executed_functions: tuple[str, ...]
    relevant_line_ranges: tuple[tuple[str, str, int, int], ...]
    observable_call_path: tuple[str, ...]
    target_file: str
    target_symbol: str
    target_symbol_hit: bool
    return_code: int
    slice_hash: str = ""

    def __post_init__(self) -> None:
        expected = canonical_hash(self.as_dict(include_hash=False))
        if self.slice_hash and self.slice_hash != expected:
            raise ValueError("failure execution slice hash mismatch")
        object.__setattr__(self, "slice_hash", expected)

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "operation_hash": self.operation_hash,
            "executed_files": list(self.executed_files),
            "executed_functions": list(self.executed_functions),
            "relevant_line_ranges": [
                {"path": path, "symbol": symbol, "start_line": start, "end_line": end}
                for path, symbol, start, end in self.relevant_line_ranges
            ],
            "observable_call_path": list(self.observable_call_path),
            "target_file": self.target_file,
            "target_symbol": self.target_symbol,
            "target_symbol_hit": self.target_symbol_hit,
            "return_code": self.return_code,
            "public_safe": True,
        }
        text = _canonical_json(value).casefold()
        if any(marker in text for marker in _PUBLIC_SAFE_FORBIDDEN):
            raise ValueError("failure execution slice contains forbidden hidden material")
        return value | ({"slice_hash": self.slice_hash} if include_hash else {})


def _safe_relative_project_path(root: pathlib.Path, filename: str) -> str | None:
    try:
        return pathlib.Path(filename).resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _symbol_ranges(source: str, path: str) -> dict[str, tuple[str, str, int, int]]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {}
    ranges = {
        node.name: (path, node.name, int(node.lineno), int(getattr(node, "end_lineno", node.lineno)))
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    ranges["<module>"] = (path, "<module>", 1, max(1, len(source.splitlines())))
    return ranges


def capture_public_failure_context(
    target: RepairTargetSpec,
    workspace: str | pathlib.Path,
    visible_sources: Mapping[str, str],
) -> tuple[FailureExecutionSlice, dict[str, Any]]:
    """Run only the canonical public reproduction and capture project-code calls.

    The trace records filenames, symbols and line ranges only.  Arguments,
    locals, assertions and traceback text are intentionally excluded.
    """

    root = pathlib.Path(workspace).resolve()
    operation = _json_value(target.operation)
    setup = _json_value(target.setup)
    if not isinstance(operation, Mapping) or not isinstance(setup, Mapping):
        raise ValueError("repair target operation and setup must be objects")
    commands = operation.get("commands", ())
    if not commands:
        raise ValueError("repair target requires one public command")
    with tempfile.TemporaryDirectory(prefix="cgkn-public-failure-slice-") as temporary:
        temporary_root = pathlib.Path(temporary)
        staged_root = temporary_root / "workspace"
        shutil.copytree(
            root,
            staged_root,
            ignore=shutil.ignore_patterns(".git", ".cgkn", ".pytest_cache", "__pycache__", "*.pyc"),
        )
        input_relative = pathlib.PurePosixPath(str(setup.get("input_path", "input.csv")))
        output_relative = pathlib.PurePosixPath(str(setup.get("output_path", "output.csv")))
        if input_relative.is_absolute() or output_relative.is_absolute() or ".." in input_relative.parts or ".." in output_relative.parts:
            raise ValueError("unsafe public reproduction fixture path")
        input_path = staged_root / input_relative
        output_path = staged_root / output_relative
        input_path.parent.mkdir(parents=True, exist_ok=True)
        with input_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter=str(setup.get("delimiter", ",")))
            writer.writerow(setup.get("header", ()))
            writer.writerows(setup.get("rows", ()))
        trace_root = temporary_root / "trace"
        trace_root.mkdir()
        trace_path = trace_root / "events.json"
        tracer = textwrap.dedent(
            """
            import atexit, json, os, pathlib, sys, threading
            _root = pathlib.Path(os.environ["CGKN_PUBLIC_TRACE_ROOT"]).resolve()
            _target = pathlib.Path(os.environ["CGKN_PUBLIC_TRACE_PATH"])
            _events = []
            def _trace(frame, event, arg):
                if event == "call":
                    try:
                        path = pathlib.Path(frame.f_code.co_filename).resolve()
                        relative = path.relative_to(_root).as_posix()
                    except (OSError, ValueError):
                        return _trace
                    _events.append({"path": relative, "symbol": frame.f_code.co_name})
                return _trace
            def _write():
                _target.write_text(json.dumps(_events, ensure_ascii=False), encoding="utf-8")
            atexit.register(_write)
            sys.settrace(_trace)
            threading.settrace(_trace)
            """
        ).strip() + "\n"
        (trace_root / "sitecustomize.py").write_text(tracer, encoding="utf-8")
        command = [str(item) for item in commands[0]["argv"]]
        if command[0].casefold() in {"python", "python.exe", "python3"}:
            command[0] = sys.executable
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP"}
        }
        environment.update({
            "PYTHONPATH": os.pathsep.join((str(trace_root), str(staged_root))),
            "CGKN_PUBLIC_TRACE_ROOT": str(staged_root),
            "CGKN_PUBLIC_TRACE_PATH": str(trace_path),
        })
        completed = subprocess.run(
            command,
            cwd=staged_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        raw_events = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.is_file() else []
        visible = set(visible_sources)
        call_path: list[str] = []
        for item in raw_events:
            relative = _safe_relative_project_path(staged_root, str(staged_root / str(item.get("path", ""))))
            symbol = str(item.get("symbol", ""))
            if not relative or relative not in visible or not symbol:
                continue
            entry = f"{relative}:{symbol}"
            if entry not in call_path:
                call_path.append(entry)
        range_catalog = {
            f"{path}:{symbol}": record
            for path, source in visible_sources.items()
            for symbol, record in _symbol_ranges(source, path).items()
        }
        line_ranges = tuple(range_catalog[item] for item in call_path if item in range_catalog)
        target_file, _, target_symbol = target.fingerprint.relevant_source_locator.partition(":")
        slice_value = FailureExecutionSlice(
            operation_hash=canonical_hash(operation),
            executed_files=tuple(dict.fromkeys(item.split(":", 1)[0] for item in call_path)),
            executed_functions=tuple(call_path),
            relevant_line_ranges=line_ranges,
            observable_call_path=tuple(call_path),
            target_file=target_file,
            target_symbol=target_symbol,
            target_symbol_hit=f"{target_file}:{target_symbol}" in call_path,
            return_code=completed.returncode,
        )
        output_rows: list[list[str]] | None = None
        if output_path.is_file():
            with output_path.open("r", newline="", encoding="utf-8") as handle:
                output_rows = list(csv.reader(handle, delimiter=str(setup.get("delimiter", ","))))
        actual_rows = list(csv.reader(io.StringIO(completed.stdout)))
        expected_document = _json_value(target.expected)
        expected_output_created = (
            bool(expected_document.get("output_created"))
            if isinstance(expected_document, Mapping)
            else False
        )
        contrast = {
            "failing_example": {
                "observable": target.fingerprint.observable,
                "input": _json_value(target.fingerprint.normalized_input),
                "expected": _json_value(target.fingerprint.normalized_expected),
                "actual": actual_rows,
                "failure_kind": target.fingerprint.failure_kind,
            },
            "nearest_passing_example": {
                "observable": "output_file.created",
                "expected": expected_output_created,
                "actual": output_path.is_file(),
                "related_public_output_rows": output_rows,
                "status": "PASS" if output_path.is_file() else "FAIL",
            },
            "public_safe": True,
        }
        contrast["contrast_hash"] = canonical_hash(contrast)
        return slice_value, contrast


def repair_evidence_metrics(packet: Mapping[str, Any]) -> dict[str, Any]:
    components = {
        "source": packet.get("relevant_implementation_files"),
        "contract": {
            "canonical_public_requirement": packet.get("canonical_public_requirement"),
            "public_interfaces": packet.get("public_interfaces"),
            "requirement_ids": packet.get("requirement_ids"),
        },
        "failure": {
            "observable": packet.get("exact_observable"),
            "input": packet.get("minimal_reproduction_input"),
            "expected": packet.get("expected_public_result"),
            "actual": packet.get("actual_public_result"),
            "kind": packet.get("failure_kind"),
        },
        "trace": packet.get("failure_execution_slice"),
        "contrastive": packet.get("contrastive_public_evidence"),
    }
    char_counts = {key: len(_canonical_json(value)) if value is not None else 0 for key, value in components.items()}
    return {
        "chars": char_counts | {"total": len(_canonical_json(packet))},
        "estimated_tokens": {key: (count + 3) // 4 for key, count in char_counts.items()},
        "token_estimate_basis": "ceil(utf8_json_chars/4); provider-reported prompt_tokens remains authoritative",
    }


def patch_modified_symbols(
    sources: Mapping[str, str],
    patch_files: tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
) -> tuple[str, ...]:
    """Return deterministic source symbols overlapped by exact PatchBundle finds."""

    touched: list[str] = []
    for path, edits in patch_files:
        source = sources.get(path, "")
        ranges = tuple(_symbol_ranges(source, path).values())
        lines = source.splitlines(keepends=True)
        offsets: list[int] = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        for find, _ in edits:
            start = source.find(find)
            if start < 0:
                continue
            end = start + len(find)
            edit_symbols: list[str] = []
            for _, symbol, start_line, end_line in ranges:
                symbol_start = offsets[min(start_line - 1, len(offsets) - 1)]
                symbol_end = offsets[min(end_line, len(offsets) - 1)]
                if start < symbol_end and end > symbol_start:
                    entry = f"{path}:{symbol}"
                    if entry not in edit_symbols:
                        edit_symbols.append(entry)
            specific = [item for item in edit_symbols if not item.endswith(":<module>")]
            for entry in specific or edit_symbols:
                if entry not in touched:
                    touched.append(entry)
    return tuple(touched)


def _comparison_values(output: str, *, expected_hint: Any = None) -> tuple[Any, Any]:
    parsed: list[tuple[Any, Any]] = []
    for line in output.splitlines():
        match = re.search(r"assert\s+(.+?)\s+==\s+(.+)$", line.strip())
        if not match:
            continue
        try:
            parsed.append((ast.literal_eval(match.group(1)), ast.literal_eval(match.group(2))))
        except (SyntaxError, ValueError):
            continue
    if expected_hint is not None:
        return next((item for item in parsed if item[1] == expected_hint), (None, None))
    return parsed[0] if parsed else (None, None)


def _failure_kind(expected: Any, actual: Any) -> str:
    if isinstance(expected, list) and isinstance(actual, list) and len(actual) > len(expected):
        if actual[: len(expected)] == expected and all(item in ([], [""], "") for item in actual[len(expected) :]):
            return "EXTRA_EMPTY_ROW"
        return "EXTRA_ROWS"
    if isinstance(expected, list) and isinstance(actual, list) and len(actual) < len(expected):
        return "MISSING_ROWS"
    return "ASSERTION_MISMATCH"


def build_public_test_repair_target(
    *,
    findings: tuple[Any, ...],
    failed_test_ids: tuple[str, ...],
    projection: Any,
    public_failure_output: str,
    owner_unit_id: str,
    baseline_hash: str,
) -> RepairTargetSpec | None:
    # A single generated test commonly asserts several public observables (for
    # example return code, output creation, and parsed stdout).  The findings
    # preserve source order, but the first assertion is not necessarily one
    # for which the exact-target validator has a deterministic harness.  Walk
    # every failed-test finding and select a supported semantic pair instead
    # of failing closed on the first unmatched assertion.
    relevant = None
    semantic = None
    for candidate in findings:
        if (
            candidate.test_id not in failed_test_ids
            or getattr(candidate.authority, "value", str(candidate.authority)) != "TEST_CONTRACT_VALID"
            or not candidate.requirement_ids
            or candidate.observable != "stdout.csv_rows"
        ):
            continue
        matched = next(
            (
                item
                for item in projection.semantics
                if item.observable == candidate.observable
                and set(item.requirement_ids).intersection(candidate.requirement_ids)
            ),
            None,
        )
        if matched is not None:
            relevant = candidate
            semantic = matched
            break
    if relevant is None or semantic is None:
        return None
    actual, pytest_expected = _comparison_values(
        public_failure_output,
        expected_hint=relevant.expected,
    )
    expected = relevant.expected if relevant.expected is not None else pytest_expected
    setup = materialize_json(getattr(semantic, "operation"))["setup"]
    operation = materialize_json(getattr(semantic, "operation"))["invoke"]
    expected_semantics = materialize_json(getattr(semantic, "expected_semantics"))
    expected_target = expected_semantics.get("stdout_csv", {"rows": expected})
    interface = next(iter(semantic.related_public_interfaces), "")
    fingerprint = RepairFailureFingerprint(
        tuple(str(item) for item in relevant.requirement_ids),
        owner_unit_id,
        next(iter(failed_test_ids), "public_contract"),
        str(relevant.observable),
        _canonical_json(setup),
        _canonical_json(expected),
        _canonical_json(actual),
        _failure_kind(expected, actual),
        str(interface),
        "",
        baseline_hash,
    )
    return RepairTargetSpec(fingerprint, _canonical_json(operation), _canonical_json(setup), _canonical_json(expected_target))


def localize_repair_sources(
    sources: Mapping[str, str], fingerprint: RepairFailureFingerprint,
) -> tuple[dict[str, str], tuple[str, ...], str]:
    tokens = {
        item
        for item in re.split(r"[^a-z0-9]+", (fingerprint.observable + " " + fingerprint.failure_kind).casefold())
        if len(item) >= 4 and item not in {"rows", "empty", "extra"}
    }
    ranked: list[tuple[int, str, str, str]] = []
    for path, source in sources.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = "\n".join(lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)])
            lowered = (node.name + " " + body).casefold()
            score = sum(4 for token in tokens if token in node.name.casefold())
            score += sum(1 for token in tokens if token in lowered)
            if fingerprint.observable.startswith("stdout") and ("sys.stdout" in lowered or "print(" in lowered):
                score += 6
            if "csv.writer" in lowered:
                score += 3
            ranked.append((score, path, node.name, body))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = ranked[:1] if ranked and ranked[0][0] > 0 else []
    if selected:
        paths = {item[1] for item in selected}
        locator = f"{selected[0][1]}:{selected[0][2]}"
        # Keep the one deterministically localized implementation file intact.
        # PatchBundle exact matching and module-level newline/import semantics
        # require that bounded context; unrelated Unit files remain excluded.
        return {path: sources[path] for path in sorted(paths)}, tuple(item[2] for item in selected), locator
    fallback = next(iter(sorted(sources)), "")
    return ({fallback: sources[fallback]} if fallback else {}), (), fallback


def summarize_patch_diff(before: Mapping[str, str], after: Mapping[str, str], paths: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for path in paths:
        chunks.extend(difflib.unified_diff(
            before.get(path, "").splitlines(),
            after.get(path, "").splitlines(),
            fromfile=f"before/{path}",
            tofile=f"candidate/{path}",
            lineterm="",
        ))
    return "\n".join(chunks)[:5000]


def _distance(expected: Any, actual: Any) -> int | None:
    if isinstance(expected, list) and isinstance(actual, list):
        difference = abs(len(expected) - len(actual))
        for left, right in zip(expected, actual):
            nested = _distance(left, right)
            difference += nested if nested is not None else int(left != right)
        return difference
    if type(expected) is type(actual):
        return int(expected != actual)
    return None


def classify_repair_progress(
    before: RepairFailureFingerprint, after: RepairFailureFingerprint | None,
) -> RepairProgress:
    if after is None:
        return RepairProgress.FIXED
    if (
        before.observable == after.observable
        and before.normalized_input == after.normalized_input
        and before.normalized_expected == after.normalized_expected
        and before.normalized_actual == after.normalized_actual
        and before.failure_kind == after.failure_kind
    ):
        return RepairProgress.NO_PROGRESS
    expected = _json_value(before.normalized_expected)
    before_distance = _distance(expected, _json_value(before.normalized_actual))
    after_distance = _distance(expected, _json_value(after.normalized_actual))
    if before_distance is None or after_distance is None:
        return RepairProgress.INCOMPARABLE
    if after_distance < before_distance:
        return RepairProgress.PROGRESSED
    if after_distance > before_distance:
        return RepairProgress.REGRESSED
    return RepairProgress.INCOMPARABLE


class CanonicalRepairTargetValidator:
    def validate(self, target: RepairTargetSpec, workspace: str | pathlib.Path) -> RepairValidationReceipt:
        root = pathlib.Path(workspace).resolve()
        operation = _json_value(target.operation)
        setup = _json_value(target.setup)
        expected = _json_value(target.expected)
        if target.fingerprint.observable != "stdout.csv_rows":
            return RepairValidationReceipt("HARNESS_FAILURE", target.target_hash, None, None, "", "unsupported canonical observable")
        input_relative = pathlib.PurePosixPath(str(setup["input_path"]))
        output_relative = pathlib.PurePosixPath(str(setup.get("output_path", "output.csv")))
        if (
            input_relative.is_absolute() or output_relative.is_absolute()
            or ".." in input_relative.parts or ".." in output_relative.parts
        ):
            return RepairValidationReceipt("HARNESS_FAILURE", target.target_hash, None, None, "", "unsafe canonical fixture path")
        input_path = root / input_relative
        output_path = root / output_relative
        input_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        with input_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter=str(setup.get("delimiter", ",")))
            writer.writerow(setup.get("header", ()))
            writer.writerows(setup.get("rows", ()))
        commands = operation.get("commands", ())
        if not commands:
            return RepairValidationReceipt("HARNESS_FAILURE", target.target_hash, None, None, "", "missing canonical command")
        command = list(commands[0]["argv"])
        if command[0].casefold() in {"python", "python.exe", "python3"}:
            command[0] = sys.executable
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP"}
        }
        environment["PYTHONPATH"] = str(root)
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        actual_rows = list(csv.reader(io.StringIO(completed.stdout)))
        expected_rows = expected.get("rows", ())
        passed = completed.returncode == 0 and actual_rows == expected_rows and (
            not expected.get("output_created") or output_path.is_file()
        )
        if passed:
            return RepairValidationReceipt("PASS", target.target_hash, None, completed.returncode, completed.stdout, completed.stderr)
        failure_kind = _failure_kind(expected_rows, actual_rows)
        fingerprint = RepairFailureFingerprint(
            target.fingerprint.requirement_ids,
            target.fingerprint.owner_unit_id,
            target.fingerprint.check_id,
            target.fingerprint.observable,
            target.fingerprint.normalized_input,
            target.fingerprint.normalized_expected,
            _canonical_json(actual_rows),
            failure_kind,
            target.fingerprint.relevant_interface_id,
            target.fingerprint.relevant_source_locator,
            target.fingerprint.baseline_hash,
        )
        return RepairValidationReceipt("FAIL", target.target_hash, fingerprint, completed.returncode, completed.stdout, completed.stderr)


def run_targeted_regression(workspace: str | pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(workspace).resolve()
    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "."], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
    )
    if compile_result.returncode != 0:
        return {"status": "FAIL", "stage": "compile", "stdout": compile_result.stdout[-2000:], "stderr": compile_result.stderr[-2000:]}
    test_files = tuple(
        path for path in root.rglob("test_*.py")
        if ".git" not in path.parts and ".cgkn" not in path.parts
    )
    if test_files:
        environment = os.environ.copy()
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        pytest_result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
            env=environment,
        )
        if pytest_result.returncode != 0:
            return {"status": "FAIL", "stage": "pytest", "stdout": pytest_result.stdout[-4000:], "stderr": pytest_result.stderr[-2000:]}
    return {"status": "PASS", "stage": "targeted", "stdout": "", "stderr": ""}
