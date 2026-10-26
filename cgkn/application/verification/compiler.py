from __future__ import annotations

from typing import Any

from cgkn.application.requirements.obligation import ObligationSet
from cgkn.application.requirements.policy import DependencyPolicy

from .contracts import OracleKind, OraclePlan, OracleSpec


CSV_OBLIGATION_IDS = frozenset({
    "OBL-CSV-INPUT-OUTPUT", "OBL-CSV-HEADER-PRESERVATION", "OBL-CSV-DEDUP-WHOLE-ROW",
    "OBL-CSV-DEDUP-COLUMN", "OBL-CSV-STABLE-ORDER", "OBL-CSV-FILL-EMPTY", "OBL-CSV-PREVIEW",
    "OBL-CSV-PREVIEW-WRITES-OUTPUT", "OBL-CSV-CLI-HELP", "OBL-CSV-ERR-UNKNOWN-COLUMN",
    "OBL-CSV-ERR-NONZERO", "OBL-CSV-README", "OBL-CSV-PUBLIC-TESTS", "OBL-CSV-RUNTIME-STDLIB",
    "OBL-CSV-TEST-PYTEST", "OBL-CSV-NETWORK-OFFLINE",
})

NOTES_OBLIGATION_IDS = frozenset({
    "OBL-NOTES-ADD", "OBL-NOTES-ADD-TAG", "OBL-NOTES-ID-MONOTONIC", "OBL-NOTES-PERSISTENCE",
    "OBL-NOTES-LIST", "OBL-NOTES-LIST-STABLE", "OBL-NOTES-LIST-TAG", "OBL-NOTES-SHOW",
    "OBL-NOTES-DELETE", "OBL-NOTES-DELETE-PERSISTS", "OBL-NOTES-ERR-MISSING-ID",
    "OBL-NOTES-ERR-INVALID-ID", "OBL-NOTES-CLI-HELP", "OBL-NOTES-README",
    "OBL-NOTES-RUNTIME-STDLIB", "OBL-NOTES-TEST-PYTEST", "OBL-NOTES-NETWORK-OFFLINE",
})


def _spec(
    oracle_id: str,
    obligation_ids: tuple[str, ...],
    kind: OracleKind,
    *,
    setup: dict[str, Any] | None = None,
    operation: dict[str, Any] | None = None,
    expected: dict[str, Any],
    forbidden: dict[str, Any] | None = None,
    side_effects: dict[str, Any] | None = None,
    policy_refs: tuple[str, ...] = (),
) -> OracleSpec:
    return OracleSpec(
        oracle_id=oracle_id,
        obligation_ids=obligation_ids,
        oracle_kind=kind,
        subject_ref="cli_csv_cleaner",
        setup=setup or {},
        operation=operation or {},
        expected=expected,
        forbidden=forbidden or {},
        side_effect_assertions=side_effects or {},
        dependency_policy_refs=policy_refs,
        timeout_seconds=10,
        scope=("cli_csv_cleaner",),
        provenance={"compiler": "csv_oracle_plan_compiler@1", "authority": "canonical_obligation"},
    )


class OraclePlanCompiler:
    """Compile the canonical CSV ObligationSet into bounded deterministic scenarios."""

    def compile_notes(self, obligations: ObligationSet, dependency_policy: DependencyPolicy) -> OraclePlan:
        ids = {item.obligation_id for item in obligations.obligations}
        if ids != NOTES_OBLIGATION_IDS:
            raise ValueError(f"canonical Notes obligation set mismatch; missing={sorted(NOTES_OBLIGATION_IDS - ids)}; extra={sorted(ids - NOTES_OBLIGATION_IDS)}")
        policy_ids = {item.dependency_policy.policy_id for item in obligations.obligations if item.dependency_policy is not None}
        if policy_ids != {dependency_policy.policy_id}:
            raise ValueError("DependencyPolicy does not match canonical Notes obligations")
        provenance = {"compiler": "notes_oracle_plan_compiler@1", "authority": "canonical_obligation"}
        def note_spec(oracle_id: str, obligation_ids: tuple[str, ...], kind: OracleKind, *, operation: dict[str, Any], expected: dict[str, Any], forbidden: dict[str, Any] | None = None, policy: bool = False):
            return OracleSpec(oracle_id, obligation_ids, kind, "local_json_notes", operation=operation, expected=expected,
                              forbidden=forbidden or {}, dependency_policy_refs=(dependency_policy.policy_id,) if policy else (),
                              timeout_seconds=10, scope=("local_json_notes",), provenance=provenance)
        cmd = ["python", "-m", "notes"]
        stateful_ids = ("OBL-NOTES-ADD", "OBL-NOTES-ADD-TAG", "OBL-NOTES-ID-MONOTONIC", "OBL-NOTES-PERSISTENCE",
                        "OBL-NOTES-LIST", "OBL-NOTES-LIST-STABLE", "OBL-NOTES-LIST-TAG", "OBL-NOTES-SHOW",
                        "OBL-NOTES-DELETE", "OBL-NOTES-DELETE-PERSISTS")
        specs = (
            note_spec("ORACLE-NOTES-STATEFUL", stateful_ids, OracleKind.JSON_STATE, operation={"storage_path": "notes.json", "commands": [
                {"argv": cmd + ["add", "hello world"], "expected": {"exit_code": 0, "stdout_exact": "1\n"}},
                {"argv": cmd + ["add", "tagged", "--tag", "work"], "expected": {"exit_code": 0, "stdout_exact": "2\n"}},
                {"argv": cmd + ["list"], "expected": {"exit_code": 0, "stdout_exact": "1\thello world\t\n2\ttagged\twork\n"}},
                {"argv": cmd + ["list", "--tag", "work"], "expected": {"exit_code": 0, "stdout_exact": "2\ttagged\twork\n"}},
                {"argv": cmd + ["show", "2"], "expected": {"exit_code": 0, "stdout_exact": "2\ttagged\twork\n"}},
                {"argv": cmd + ["delete", "1"], "expected": {"exit_code": 0, "stdout_exact": "deleted 1\n"}},
                {"argv": cmd + ["add", "third"], "expected": {"exit_code": 0, "stdout_exact": "3\n"}},
                {"argv": cmd + ["list"], "expected": {"exit_code": 0, "stdout_exact": "2\ttagged\twork\n3\tthird\t\n"}},
            ]}, expected={"state_file_exists": True, "state_excludes": ["hello world"]}),
            note_spec("ORACLE-NOTES-ERRORS", ("OBL-NOTES-ERR-MISSING-ID", "OBL-NOTES-ERR-INVALID-ID"), OracleKind.JSON_STATE,
                      operation={"commands": [
                          {"argv": cmd + ["show", "99"], "expected": {"exit_code": "nonzero", "stderr": "nonempty"}},
                          {"argv": cmd + ["delete", "99"], "expected": {"exit_code": "nonzero", "stderr": "nonempty"}},
                          {"argv": cmd + ["show", "bad"], "expected": {"exit_code": "nonzero", "stderr": "nonempty"}},
                      ]}, expected={"state_file_exists": False}),
            note_spec("ORACLE-NOTES-HELP", ("OBL-NOTES-CLI-HELP",), OracleKind.CLI,
                      operation={"commands": [{"argv": cmd + ["--help"]}]}, expected={"exit_code": 0, "stdout_contains": ["add", "list", "show", "delete"]}),
            note_spec("ORACLE-NOTES-README", ("OBL-NOTES-README",), OracleKind.DOCUMENTATION, operation={"path": "README.md"},
                      expected={"exists": True, "contains": ["python -m notes", "add", "list", "show", "delete", "--tag"]}),
            note_spec("ORACLE-NOTES-PUBLIC-TESTS", ("OBL-NOTES-TEST-PYTEST",), OracleKind.FILE, operation={"glob": "tests/test_*.py"},
                      expected={"minimum_files": 1, "pytest_exit_code": 0}, policy=True),
            note_spec("ORACLE-NOTES-RUNTIME", ("OBL-NOTES-RUNTIME-STDLIB",), OracleKind.DEPENDENCY,
                      operation={"domain": "runtime", "paths": ["notes/**/*.py"]}, expected={"stdlib_only": True}, policy=True),
            note_spec("ORACLE-NOTES-NETWORK", ("OBL-NOTES-NETWORK-OFFLINE",), OracleKind.STATIC_PYTHON,
                      operation={"paths": ["notes/**/*.py"], "checks": ["imports", "network_calls"]}, expected={"network_outbound": "FORBIDDEN"},
                      forbidden={"imports": ["requests", "httpx", "urllib.request", "socket"]}, policy=True),
        )
        covered = {identifier for item in specs for identifier in item.obligation_ids}
        if covered != ids:
            raise AssertionError("Notes Oracle compiler coverage drift")
        return OraclePlan("PLAN-NOTES-ORACLE-001", tuple(ids), obligations.as_dict()["obligation_set_hash"], specs)

    def compile_csv(
        self,
        obligations: ObligationSet,
        dependency_policy: DependencyPolicy,
        *,
        entrypoint: str = "csv_cleaner",
    ) -> OraclePlan:
        ids = {item.obligation_id for item in obligations.obligations}
        if ids != CSV_OBLIGATION_IDS:
            missing = sorted(CSV_OBLIGATION_IDS - ids)
            extra = sorted(ids - CSV_OBLIGATION_IDS)
            raise ValueError(f"canonical CSV obligation set mismatch; missing={missing}; extra={extra}")
        policy_ids = {
            item.dependency_policy.policy_id
            for item in obligations.obligations
            if item.dependency_policy is not None
        }
        if policy_ids != {dependency_policy.policy_id}:
            raise ValueError("DependencyPolicy does not match canonical CSV obligations")
        command = ["python", "-m", entrypoint]
        common_setup = {
            "input_path": "input.csv",
            "output_path": "output.csv",
            "delimiter": ",",
            "header": ["id", "name", "city"],
        }
        specs = (
            _spec(
                "ORACLE-CSV-WHOLE-ROW", (
                    "OBL-CSV-INPUT-OUTPUT", "OBL-CSV-HEADER-PRESERVATION",
                    "OBL-CSV-DEDUP-WHOLE-ROW", "OBL-CSV-STABLE-ORDER",
                ), OracleKind.CSV,
                setup=common_setup | {"rows": [["1", "Ada", ""], ["1", "Ada", ""], ["2", "Lin", "Paris"]]},
                operation={"argv": command + ["input.csv", "output.csv"]},
                expected={"exit_code": 0, "header": ["id", "name", "city"], "rows": [["1", "Ada", ""], ["2", "Lin", "Paris"]], "stable_order": True},
                side_effects={"output_created": True},
            ),
            _spec(
                "ORACLE-CSV-COLUMN-FILL", ("OBL-CSV-DEDUP-COLUMN", "OBL-CSV-FILL-EMPTY"), OracleKind.CSV,
                setup=common_setup | {"rows": [["1", "Ada", ""], ["1", "Changed", "Rome"], ["2", "Lin", ""]]},
                operation={"argv": command + ["input.csv", "output.csv", "--dedupe-column", "id", "--fill", "UNKNOWN"]},
                expected={"exit_code": 0, "header": ["id", "name", "city"], "rows": [["1", "Ada", "UNKNOWN"], ["2", "Lin", "UNKNOWN"]]},
                side_effects={"output_created": True},
            ),
            _spec(
                "ORACLE-CLI-PREVIEW", ("OBL-CSV-PREVIEW", "OBL-CSV-PREVIEW-WRITES-OUTPUT"), OracleKind.CLI,
                setup=common_setup | {"rows": [["1", "Ada", ""], ["2", "Lin", "Paris"]]},
                operation={"commands": [{"argv": command + ["input.csv", "output.csv", "--preview", "1"]}]},
                expected={"exit_code": 0, "stdout_csv": {"rows": [["1", "Ada", ""]]}, "output_created": True},
                side_effects={"output_created": True, "preview_does_not_suppress_output": True},
            ),
            _spec(
                "ORACLE-CLI-HELP", ("OBL-CSV-CLI-HELP",), OracleKind.CLI,
                operation={"commands": [{"argv": command + ["--help"]}]},
                expected={"exit_code": 0, "stdout_contains": ["usage", "--preview", "--dedupe-column", "--fill"]},
            ),
            _spec(
                "ORACLE-CLI-UNKNOWN-COLUMN", ("OBL-CSV-ERR-UNKNOWN-COLUMN", "OBL-CSV-ERR-NONZERO"), OracleKind.CLI,
                setup=common_setup | {"rows": [["1", "Ada", ""]]},
                operation={"commands": [{"argv": command + ["input.csv", "output.csv", "--dedupe-column", "missing"]}]},
                expected={"exit_code": "nonzero", "stderr": "nonempty"},
                forbidden={"successful_output_commit": True},
                side_effects={"output_created": False},
            ),
            _spec(
                "ORACLE-DOC-README", ("OBL-CSV-README",), OracleKind.DOCUMENTATION,
                operation={"path": "README.md"},
                expected={"exists": True, "contains": ["python -m csv_cleaner", "--dedupe-column", "--fill", "--preview"]},
                forbidden={"contains": ["hidden acceptance", "benchmarks/real_project_generation"]},
            ),
            _spec(
                "ORACLE-FILE-PUBLIC-TESTS", ("OBL-CSV-PUBLIC-TESTS",), OracleKind.FILE,
                operation={"glob": "tests/test_*.py"},
                expected={"minimum_files": 1, "pytest_exit_code": 0},
            ),
            _spec(
                "ORACLE-DEPS-RUNTIME", ("OBL-CSV-RUNTIME-STDLIB",), OracleKind.DEPENDENCY,
                operation={"domain": "runtime", "paths": ["csv_cleaner/**/*.py"]},
                expected={"stdlib_only": True},
                policy_refs=(dependency_policy.policy_id,),
            ),
            _spec(
                "ORACLE-DEPS-TEST", ("OBL-CSV-TEST-PYTEST",), OracleKind.DEPENDENCY,
                operation={"domain": "test", "paths": ["tests/**/*.py"]},
                expected={"allowed_packages": ["pytest"], "runtime_pytest_allowed": False},
                policy_refs=(dependency_policy.policy_id,),
            ),
            _spec(
                "ORACLE-STATIC-NETWORK", ("OBL-CSV-NETWORK-OFFLINE",), OracleKind.STATIC_PYTHON,
                operation={"paths": ["csv_cleaner/**/*.py"], "checks": ["imports", "network_calls"]},
                expected={"network_outbound": "FORBIDDEN"},
                forbidden={"imports": ["requests", "httpx", "urllib.request", "socket"]},
                policy_refs=(dependency_policy.policy_id,),
            ),
        )
        covered = {identifier for item in specs for identifier in item.obligation_ids}
        if covered != ids:
            raise AssertionError("Oracle compiler coverage drift")
        return OraclePlan(
            plan_id="PLAN-CSV-ORACLE-001",
            source_obligation_ids=tuple(ids),
            obligation_set_hash=obligations.as_dict()["obligation_set_hash"],
            specs=specs,
        )
