from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tempfile
from typing import Any, Iterable, Mapping

from cgkn.application.requirements.obligation import thaw
from cgkn.application.requirements.policy import DependencyPolicy

from .contracts import OracleEvidence, OracleKind, OraclePlan, OracleSpec, OracleStatus


_SYSTEM_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP", "PYTHONPATH")
_NETWORK_IMPORTS = {"requests", "httpx", "aiohttp", "socket", "urllib"}
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp)/)")


class HarnessError(ValueError):
    pass


def _inside(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise HarnessError("absolute candidate path is forbidden")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HarnessError("candidate path escapes workspace") from exc
    return resolved


def _summary(value: str, limit: int = 2000) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[-limit:]


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class OracleExecutor:
    def __init__(self, policies: Iterable[DependencyPolicy] = ()):
        self._policies = {item.policy_id: item for item in policies}

    def execute_plan(self, plan: OraclePlan, workspace: str | Path) -> tuple[OracleEvidence, ...]:
        return tuple(self.execute(spec, workspace) for spec in plan.specs)

    def execute(self, spec: OracleSpec, workspace: str | Path) -> OracleEvidence:
        root = Path(workspace).resolve()
        started = time.perf_counter()
        observed: dict[str, Any] = {}
        return_code: int | None = None
        stdout = ""
        stderr = ""
        artifacts: tuple[dict[str, Any], ...] = ()
        status = OracleStatus.HARNESS_FAILURE
        failure_class: str | None = "HARNESS_FAILURE"
        try:
            if not root.is_dir():
                raise HarnessError("workspace does not exist")
            handler = {
                OracleKind.COMMAND: self._command,
                OracleKind.FILE: self._file,
                OracleKind.CSV: self._csv,
                OracleKind.CLI: self._cli,
                OracleKind.DEPENDENCY: self._dependency,
                OracleKind.STATIC_PYTHON: self._static_python,
                OracleKind.DOCUMENTATION: self._documentation,
                OracleKind.JSON_STATE: self._json_state,
            }[spec.oracle_kind]
            result = handler(spec, root)
            observed = result[0]
            return_code = result[1]
            stdout = result[2]
            stderr = result[3]
            artifacts = tuple(result[4])
            passed = bool(observed.pop("_passed"))
            status = OracleStatus.PASS if passed else OracleStatus.FAIL
            failure_class = None if passed else str(observed.pop("_failure_class", "ASSERTION_MISMATCH"))
        except subprocess.TimeoutExpired as exc:
            status = OracleStatus.FAIL
            failure_class = "TIMEOUT"
            observed = {"timeout": True, "timeout_seconds": spec.timeout_seconds}
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "")
        except FileNotFoundError as exc:
            status = OracleStatus.BLOCKED_ENVIRONMENT
            failure_class = "COMMAND_UNAVAILABLE"
            observed = {"error": str(exc)}
        except (HarnessError, KeyError, TypeError, ValueError, csv.Error, SyntaxError) as exc:
            status = OracleStatus.HARNESS_FAILURE
            failure_class = "HARNESS_FAILURE"
            observed = {"error": str(exc)}
        return OracleEvidence(
            evidence_id=f"EVIDENCE-{spec.oracle_id}",
            oracle_id=spec.oracle_id,
            obligation_ids=spec.obligation_ids,
            status=status,
            expected=spec.expected,
            observed=observed,
            return_code=return_code,
            stdout_summary=_summary(stdout),
            stderr_summary=_summary(stderr),
            artifacts=artifacts,
            duration_ms=int((time.perf_counter() - started) * 1000),
            failure_class=failure_class,
        )

    def _environment(self, operation: Mapping[str, Any]) -> dict[str, str]:
        allowed = set(str(item) for item in operation.get("env_allowlist", ())) | set(_SYSTEM_ENV)
        supplied = {str(key): str(value) for key, value in dict(operation.get("env", {})).items()}
        unexpected = sorted(set(supplied) - allowed)
        if unexpected:
            raise HarnessError("environment key is not allowlisted: " + ",".join(unexpected))
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(supplied)
        return environment

    def _run(self, operation: Mapping[str, Any], root: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        if operation.get("shell"):
            raise HarnessError("shell execution is forbidden")
        argv = operation.get("argv")
        if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise HarnessError("command argv must be a non-empty string list")
        command = list(argv)
        if command[0].lower() in {"python", "python.exe", "python3"}:
            command[0] = sys.executable
        cwd = _inside(root, str(operation.get("cwd", ".")))
        if not cwd.is_dir():
            raise HarnessError("command cwd does not exist")
        return subprocess.run(
            command,
            cwd=cwd,
            input=str(operation.get("stdin", "")),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=self._environment(operation),
            check=False,
        )

    @staticmethod
    def _command_assertions(expected: Mapping[str, Any], completed: subprocess.CompletedProcess[str]) -> tuple[bool, list[str]]:
        errors: list[str] = []
        exit_expected = expected.get("exit_code")
        if exit_expected == "nonzero" and completed.returncode == 0:
            errors.append("expected nonzero exit code")
        elif isinstance(exit_expected, int) and completed.returncode != exit_expected:
            errors.append(f"expected exit {exit_expected}, observed {completed.returncode}")
        contains = expected.get("stdout_contains", ())
        if isinstance(contains, str):
            contains = (contains,)
        for item in contains:
            if str(item).lower() not in completed.stdout.lower():
                errors.append(f"stdout missing {item}")
        if "stdout_exact" in expected:
            actual = _summary(completed.stdout).strip()
            wanted = _summary(str(expected["stdout_exact"])).strip()
            if actual != wanted:
                errors.append("stdout exact mismatch")
        if expected.get("stderr") == "nonempty" and not completed.stderr.strip():
            errors.append("stderr is empty")
        if expected.get("stderr") == "empty" and completed.stderr.strip():
            errors.append("stderr is not empty")
        return not errors, errors

    def _command(self, spec: OracleSpec, root: Path):
        completed = self._run(spec.operation, root, spec.timeout_seconds)
        passed, errors = self._command_assertions(spec.expected, completed)
        return ({"_passed": passed, "return_code": completed.returncode, "assertion_errors": errors}, completed.returncode, completed.stdout, completed.stderr, ())

    @staticmethod
    def _matching(root: Path, operation: Mapping[str, Any]) -> list[Path]:
        if operation.get("path"):
            return [_inside(root, str(operation["path"]))]
        pattern = str(operation.get("glob", ""))
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise HarnessError("file glob must be a safe relative pattern")
        return sorted(path for path in root.glob(pattern) if path.is_file())

    def _file(self, spec: OracleSpec, root: Path):
        paths = self._matching(root, spec.operation)
        expected = spec.expected
        errors: list[str] = []
        exists = bool(paths and all(path.is_file() for path in paths))
        if expected.get("exists") is True and not exists:
            errors.append("file missing")
        if expected.get("absent") is True and exists:
            errors.append("file unexpectedly exists")
        if expected.get("nonempty") is True and any(path.stat().st_size == 0 for path in paths):
            errors.append("file is empty")
        if int(expected.get("minimum_files", 0)) > len(paths):
            errors.append("minimum file count not met")
        contains = expected.get("contains", ())
        excludes = expected.get("does_not_contain", ())
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            errors.extend(f"{path.name} missing {item}" for item in contains if str(item) not in text)
            errors.extend(f"{path.name} contains forbidden {item}" for item in excludes if str(item) in text)
            if expected.get("sha256") and _sha(path) != str(expected["sha256"]):
                errors.append(f"{path.name} sha256 mismatch")
        return_code = None
        stdout = stderr = ""
        if "pytest_exit_code" in expected and paths:
            completed = self._run({
                "argv": [sys.executable, "-m", "pytest", "-q", *[str(path.relative_to(root)) for path in paths]],
                "env": {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                "env_allowlist": ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"],
            }, root, spec.timeout_seconds)
            return_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
            if completed.returncode != int(expected["pytest_exit_code"]):
                errors.append("pytest exit mismatch")
        artifacts = tuple({"path": path.relative_to(root).as_posix(), "sha256": _sha(path)} for path in paths if path.is_file())
        return ({"_passed": not errors, "paths": [item["path"] for item in artifacts], "assertion_errors": errors}, return_code, stdout, stderr, artifacts)

    @staticmethod
    def _write_csv_fixture(spec: OracleSpec, root: Path) -> Path | None:
        setup = spec.setup
        if "input_path" not in setup:
            return None
        path = _inside(root, str(setup["input_path"]))
        if "output_path" in setup:
            output = _inside(root, str(setup["output_path"]))
            if output.is_file():
                output.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=str(setup.get("delimiter", ",")))
            writer.writerow(tuple(setup.get("header", ())))
            writer.writerows(tuple(setup.get("rows", ())))
        return path

    @staticmethod
    def _read_csv(path: Path, delimiter: str = ",") -> tuple[list[str], list[list[str]]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=delimiter))
        if not rows:
            raise csv.Error("CSV output is empty")
        return rows[0], rows[1:]

    def _csv(self, spec: OracleSpec, root: Path):
        self._write_csv_fixture(spec, root)
        completed = self._run(spec.operation, root, spec.timeout_seconds)
        errors: list[str] = []
        command_passed, command_errors = self._command_assertions(spec.expected, completed)
        errors.extend(command_errors)
        output_path = _inside(root, str(spec.setup.get("output_path", "output.csv")))
        if not output_path.is_file():
            errors.append("output CSV missing")
            observed_header: list[str] = []
            observed_rows: list[list[str]] = []
            artifacts = ()
        else:
            observed_header, observed_rows = self._read_csv(output_path, str(spec.setup.get("delimiter", ",")))
            artifacts = ({"path": output_path.relative_to(root).as_posix(), "sha256": _sha(output_path)},)
            if "header" in spec.expected and observed_header != list(spec.expected["header"]):
                errors.append("CSV header mismatch")
            if "rows" in spec.expected and observed_rows != [list(row) for row in spec.expected["rows"]]:
                errors.append("CSV rows or order mismatch")
            if "row_count" in spec.expected and len(observed_rows) != int(spec.expected["row_count"]):
                errors.append("CSV row count mismatch")
        observed = {"_passed": command_passed and not errors, "return_code": completed.returncode, "header": observed_header, "rows": observed_rows, "row_count": len(observed_rows), "assertion_errors": errors}
        return observed, completed.returncode, completed.stdout, completed.stderr, artifacts

    def _cli(self, spec: OracleSpec, root: Path):
        self._write_csv_fixture(spec, root)
        commands = spec.operation.get("commands")
        if not isinstance(commands, (list, tuple)) or not commands:
            raise HarnessError("CLI Oracle requires commands")
        errors: list[str] = []
        last: subprocess.CompletedProcess[str] | None = None
        for operation in commands:
            last = self._run(operation, root, spec.timeout_seconds)
            passed, command_errors = self._command_assertions(spec.expected, last)
            if not passed:
                errors.extend(command_errors)
        assert last is not None
        if "stdout_csv" in spec.expected:
            rows = [row for row in csv.reader(io.StringIO(last.stdout)) if row]
            csv_expected = spec.expected["stdout_csv"]
            expected_rows = [list(row) for row in csv_expected["rows"]]
            if "header" in csv_expected:
                expected_rows.insert(0, list(csv_expected["header"]))
            if rows != expected_rows:
                errors.append("preview stdout CSV mismatch")
        output_declared = (
            "output_path" in spec.setup
            or "output_created" in spec.expected
            or "output_created" in spec.side_effect_assertions
            or spec.forbidden.get("successful_output_commit") is True
        )
        output_path = _inside(root, str(spec.setup.get("output_path", "output.csv"))) if output_declared else None
        should_exist = spec.expected.get("output_created") is True
        must_not_exist = spec.side_effect_assertions.get("output_created") is False or spec.forbidden.get("successful_output_commit") is True
        if should_exist and (output_path is None or not output_path.is_file()):
            errors.append("expected output side effect missing")
        if must_not_exist and output_path is not None and output_path.exists():
            errors.append("forbidden output side effect observed")
        artifacts = ({"path": output_path.relative_to(root).as_posix(), "sha256": _sha(output_path)},) if output_path is not None and output_path.is_file() else ()
        return ({"_passed": not errors, "return_code": last.returncode, "output_created": bool(output_path and output_path.is_file()), "assertion_errors": errors}, last.returncode, last.stdout, last.stderr, artifacts)

    def _json_state(self, spec: OracleSpec, root: Path):
        commands = spec.operation.get("commands")
        if not isinstance(commands, (list, tuple)) or not commands:
            raise HarnessError("JSON_STATE Oracle requires commands")
        errors: list[str] = []
        observations: list[dict[str, Any]] = []
        last: subprocess.CompletedProcess[str] | None = None
        storage_name = str(spec.operation.get("storage_path", "notes.json"))
        if Path(storage_name).is_absolute() or ".." in Path(storage_name).parts:
            raise HarnessError("JSON state path must be relative")
        with tempfile.TemporaryDirectory(prefix="cgkn-oracle-") as directory:
            cwd = Path(directory)
            env = self._environment({})
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(root) + (os.pathsep + existing if existing else "")
            for index, command_spec in enumerate(commands):
                if not isinstance(command_spec, Mapping):
                    raise HarnessError("JSON_STATE command must be a mapping")
                argv = command_spec.get("argv")
                if not isinstance(argv, (list, tuple)) or not argv:
                    raise HarnessError("JSON_STATE command argv is required")
                command = list(argv)
                if str(command[0]).lower() in {"python", "python.exe", "python3"}:
                    command[0] = sys.executable
                last = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=spec.timeout_seconds, check=False)
                wanted = command_spec.get("expected", {})
                step_errors: list[str] = []
                exit_code = wanted.get("exit_code")
                if exit_code == "nonzero" and last.returncode == 0:
                    step_errors.append("expected nonzero exit code")
                elif isinstance(exit_code, int) and last.returncode != exit_code:
                    step_errors.append(f"expected exit {exit_code}, observed {last.returncode}")
                if "stdout_exact" in wanted and last.stdout != str(wanted["stdout_exact"]):
                    step_errors.append("stdout exact mismatch")
                if wanted.get("stderr") == "nonempty" and not last.stderr.strip():
                    step_errors.append("stderr is empty")
                errors.extend(f"step {index}: {message}" for message in step_errors)
                observations.append({"argv": command[1:], "return_code": last.returncode, "stdout": _summary(last.stdout), "stderr": _summary(last.stderr)})
            state_path = cwd / storage_name
            state: Any = None
            if spec.expected.get("state_file_exists") and not state_path.is_file():
                errors.append("state file missing")
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
            serialized = json.dumps(state, ensure_ascii=False, sort_keys=True)
            for key, value in dict(spec.expected.get("state_contains", {})).items():
                if json.dumps(value, ensure_ascii=False) not in serialized:
                    errors.append(f"state missing {key}")
            for value in spec.expected.get("state_excludes", ()):
                if str(value) in serialized:
                    errors.append(f"state contains excluded value {value}")
            artifact = ({"path": storage_name, "sha256": _sha(state_path)},) if state_path.is_file() else ()
        assert last is not None
        return ({"_passed": not errors, "commands": observations, "state": state, "assertion_errors": errors}, last.returncode, last.stdout, last.stderr, artifact)

    def _policy(self, spec: OracleSpec) -> DependencyPolicy:
        if len(spec.dependency_policy_refs) != 1:
            raise HarnessError("dependency Oracle requires exactly one policy reference")
        try:
            return self._policies[spec.dependency_policy_refs[0]]
        except KeyError as exc:
            raise HarnessError("dependency policy is unavailable") from exc

    @staticmethod
    def _python_paths(root: Path, patterns: Iterable[str]) -> list[Path]:
        paths: set[Path] = set()
        for pattern in patterns:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise HarnessError("source glob must be relative")
            paths.update(path for path in root.glob(pattern) if path.is_file())
        return sorted(paths)

    @staticmethod
    def _imports(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
        return found

    def _dependency(self, spec: OracleSpec, root: Path):
        policy = self._policy(spec)
        domain = str(spec.operation.get("domain", ""))
        domain_policy = getattr(policy, domain, None)
        if domain_policy is None:
            raise HarnessError("unknown dependency domain")
        paths = self._python_paths(root, spec.operation.get("paths", ()))
        if not paths:
            raise HarnessError("dependency source selection is empty")
        imports = sorted({item for path in paths for item in self._imports(path)})
        local_roots = {
            path.parent.relative_to(root).parts[0]
            for path in root.glob("**/__init__.py")
            if path.parent.relative_to(root).parts
        }
        violations: list[str] = []
        for package in imports:
            if package in sys.stdlib_module_names or package in local_roots:
                continue
            if package in domain_policy.forbidden_packages or domain_policy.stdlib_only or package not in domain_policy.allowed_packages:
                violations.append(package)
        return ({"_passed": not violations, "domain": domain, "imports": imports, "violations": violations}, None, "", "", ())

    def _static_python(self, spec: OracleSpec, root: Path):
        paths = self._python_paths(root, spec.operation.get("paths", ()))
        if not paths:
            raise HarnessError("static source selection is empty")
        errors: list[str] = []
        forbidden_imports = {str(item).split(".")[0] for item in spec.forbidden.get("imports", ())}
        all_imports: set[str] = set()
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                compile(text, str(path), "exec")
                all_imports.update(self._imports(path))
            except SyntaxError as exc:
                errors.append(f"syntax:{path.name}:{exc.lineno}")
            lowered = text.lower()
            if spec.operation.get("placeholder_scan") and any(token in lowered for token in ("placeholder", "notimplementederror", "...")):
                errors.append(f"placeholder:{path.name}")
            if spec.operation.get("todo_scan") and "todo" in lowered:
                errors.append(f"todo:{path.name}")
            if spec.operation.get("absolute_path_scan") and _ABSOLUTE_PATH.search(text):
                errors.append(f"absolute_path:{path.name}")
        violations = sorted(all_imports & forbidden_imports)
        errors.extend(f"forbidden_import:{item}" for item in violations)
        if spec.expected.get("network_outbound") == "FORBIDDEN":
            errors.extend(f"network_import:{item}" for item in sorted(all_imports & _NETWORK_IMPORTS))
        entrypoint = spec.operation.get("entrypoint")
        if entrypoint and not _inside(root, str(entrypoint)).is_file():
            errors.append("entrypoint missing")
        public_module = spec.operation.get("public_module")
        if public_module:
            module_path = _inside(root, str(public_module).replace(".", "/") + ".py")
            package_init = _inside(root, str(public_module).replace(".", "/") + "/__init__.py")
            if not module_path.is_file() and not package_init.is_file():
                errors.append("public module missing")
        manifest = spec.operation.get("interface_manifest", {})
        if manifest:
            module_file = _inside(root, str(manifest["module"]).replace(".", "/") + ".py")
            if not module_file.is_file():
                errors.append("interface module missing")
            else:
                tree = ast.parse(module_file.read_text(encoding="utf-8"))
                functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
                errors.extend(f"function missing:{item}" for item in manifest.get("functions", ()) if item not in functions)
                errors.extend(f"class missing:{item}" for item in manifest.get("classes", ()) if item not in classes)
        return ({"_passed": not errors, "imports": sorted(all_imports), "assertion_errors": errors}, None, "", "", ())

    def _documentation(self, spec: OracleSpec, root: Path):
        path = _inside(root, str(spec.operation.get("path", "README.md")))
        errors: list[str] = []
        if spec.expected.get("exists") is True and not path.is_file():
            errors.append("documentation missing")
            text = ""
        else:
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        errors.extend(f"documentation missing {item}" for item in spec.expected.get("contains", ()) if str(item) not in text)
        errors.extend(f"documentation exposes {item}" for item in spec.forbidden.get("contains", ()) if str(item).lower() in text.lower())
        artifacts = ({"path": path.relative_to(root).as_posix(), "sha256": _sha(path)},) if path.is_file() else ()
        return ({"_passed": not errors, "exists": path.is_file(), "assertion_errors": errors}, None, "", "", artifacts)
