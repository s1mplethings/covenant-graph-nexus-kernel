from __future__ import annotations

import json
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

from .contracts import AcceptanceResult, FailureClass, ProjectResultStatus
from .catalog import get_case


class ExternalAcceptanceExecutor:
    descriptor = ExecutorDescriptor("project.acceptance@1", "external_acceptance", ("project.acceptance.external@1",), ("process.execute", "test.observe"))

    def __init__(self, project_root: pathlib.Path | str, acceptance_root: pathlib.Path | str):
        self.project_root = pathlib.Path(project_root).resolve()
        self.acceptance_root = pathlib.Path(acceptance_root).resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        case_id = str(request.task_context.node_config.get("case_id", ""))
        snapshot_hash = ""
        for value in request.task_context.dependency_results.values():
            if isinstance(value, Mapping) and value.get("snapshot_hash"):
                snapshot_hash = str(value["snapshot_hash"])
        test_path = self.acceptance_root / f"test_{case_id}.py"
        if not test_path.is_file():
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.HARNESS_FAILURE, "acceptance harness is unavailable", snapshot_hash=snapshot_hash)
            return self._block(request, result, started, clock)
        public_requirements = tuple(str(item) for item in (
            request.task_context.acceptance or request.task_context.node_config.get("acceptance", ())
        ))
        if not public_requirements:
            try:
                public_requirements = get_case(case_id).public_acceptance
            except ValueError:
                public_requirements = ()
        manifest_path = self.acceptance_root / f"test_{case_id}.requirements.json"
        manifest_hash, requirement_map, manifest_error = self._load_requirement_manifest(
            manifest_path, case_id, public_requirements,
        )
        if manifest_error:
            result = AcceptanceResult(
                ProjectResultStatus.FAIL,
                FailureClass.HARNESS_ATTRIBUTION_UNAVAILABLE,
                "external acceptance requirement mapping unavailable",
                requirement_manifest_hash=manifest_hash,
                mapping_complete=False,
                snapshot_hash=snapshot_hash,
            )
            return self._block(request, result, started, clock)
        env = os.environ.copy()
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CGKN_GENERATED_PROJECT": str(self.project_root), "PYTHONPATH": str(self.project_root)})
        dependency_policy = request.task_context.node_config.get("dependency_policy", {})
        if isinstance(dependency_policy, Mapping):
            test_policy = dependency_policy.get("test", {})
            if isinstance(test_policy, Mapping):
                env["CGKN_TEST_ALLOWED_PACKAGES"] = ",".join(str(item) for item in test_policy.get("allowed_packages", ()))
        try:
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(test_path)], cwd=self.project_root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=request.timeout_seconds, env=env)
            status = ProjectResultStatus.PASS if completed.returncode == 0 else ProjectResultStatus.FAIL
            failure = None if status is ProjectResultStatus.PASS else FailureClass.PROJECT_FAILURE
            summary = "all external requirements passed" if status is ProjectResultStatus.PASS else "one or more external requirements failed"
            failed_nodes = self._failed_node_identities(completed.stdout)
            failed, mapping_complete = ((), True) if status is ProjectResultStatus.PASS else self._map_failed_requirements(
                failed_nodes, requirement_map, public_requirements,
            )
            if status is ProjectResultStatus.FAIL and not mapping_complete:
                failure = FailureClass.HARNESS_ATTRIBUTION_UNAVAILABLE
                summary = "external acceptance requirement mapping unavailable"
                failed = ()
            stdout = self._sanitized_output(completed.stdout, status)
            stderr = self._sanitized_output(completed.stderr, status)
            summaries = {
                requirement_id: public_requirements[int(requirement_id.rsplit("-", 1)[1]) - 1]
                for requirement_id in failed
            }
            result = AcceptanceResult(
                status=status,
                failure_class=failure,
                sanitized_summary=summary,
                failed_requirement_ids=failed,
                public_requirement_summaries=summaries,
                requirement_manifest_hash=manifest_hash,
                mapping_complete=mapping_complete,
                return_codes=(completed.returncode,),
                stdout_tail=stdout,
                stderr_tail=stderr,
                runtime_observations={"real_subprocess": True, "isolated_harness": True},
                duration_ms=int((time.perf_counter() - clock) * 1000),
                snapshot_hash=snapshot_hash,
            )
        except subprocess.TimeoutExpired:
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.TIMEOUT, "external acceptance timed out", duration_ms=int((time.perf_counter() - clock) * 1000), snapshot_hash=snapshot_hash)
        return self._block(request, result, started, clock)

    @staticmethod
    def _load_requirement_manifest(
        path: pathlib.Path,
        case_id: str,
        public_requirements: tuple[str, ...],
    ) -> tuple[str, dict[str, tuple[str, ...]], str]:
        if not path.is_file():
            return "", {}, "manifest_missing"
        raw = path.read_bytes()
        manifest_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw.decode("utf-8"))
            if set(value) != {"schema_version", "case_id", "tests"}:
                raise ValueError("invalid keys")
            if value["schema_version"] != "1.0" or value["case_id"] != case_id or not isinstance(value["tests"], dict):
                raise ValueError("invalid identity")
            valid_ids = {f"public-requirement-{index}" for index in range(1, len(public_requirements) + 1)}
            mapped: dict[str, tuple[str, ...]] = {}
            for hidden_node, raw_ids in value["tests"].items():
                if not isinstance(hidden_node, str) or not hidden_node or not isinstance(raw_ids, list) or not raw_ids:
                    raise ValueError("invalid mapping")
                requirement_ids = tuple(str(item) for item in raw_ids)
                if len(set(requirement_ids)) != len(requirement_ids) or not set(requirement_ids) <= valid_ids:
                    raise ValueError("invalid public requirement")
                mapped[hidden_node.replace("\\", "/")] = requirement_ids
            if not mapped:
                raise ValueError("empty mapping")
            return manifest_hash, mapped, ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return manifest_hash, {}, "manifest_invalid"

    @staticmethod
    def _failed_node_identities(stdout: str) -> tuple[str, ...]:
        identities: list[str] = []
        for line in stdout.splitlines():
            match = re.match(r"^FAILED\s+(.+?)(?:\s+-\s+.*)?$", line.strip())
            if not match:
                continue
            raw = match.group(1).replace("\\", "/")
            parts = raw.split("::", 1)
            identity = pathlib.PurePosixPath(parts[0]).name
            if len(parts) == 2:
                identity += "::" + parts[1]
            identities.append(identity)
        return tuple(dict.fromkeys(identities))

    @staticmethod
    def _map_failed_requirements(
        failed_nodes: tuple[str, ...],
        requirement_map: Mapping[str, tuple[str, ...]],
        public_requirements: tuple[str, ...],
    ) -> tuple[tuple[str, ...], bool]:
        if not failed_nodes:
            return (), False
        collected: set[str] = set()
        for node in failed_nodes:
            requirement_ids = requirement_map.get(node)
            if not requirement_ids:
                return (), False
            collected.update(requirement_ids)
        ordered = tuple(
            requirement_id
            for index in range(1, len(public_requirements) + 1)
            if (requirement_id := f"public-requirement-{index}") in collected
        )
        return ordered, bool(ordered)

    @staticmethod
    def _sanitized_output(value: str, status: ProjectResultStatus) -> str:
        """Keep useful PASS evidence without leaking harness paths or assertions."""
        if not value:
            return ""
        if status is ProjectResultStatus.FAIL:
            return "external acceptance diagnostics withheld"
        lines = [line for line in value.splitlines() if "passed in" in line]
        return (lines[-1] + "\n") if lines else "external acceptance completed\n"

    @staticmethod
    def _block(request: BlockExecutionRequest, result: AcceptanceResult, started: str, clock: float) -> BlockExecutionResult:
        value = result.as_dict()
        status = BlockStatus.SUCCEEDED if result.status is ProjectResultStatus.PASS else BlockStatus.FAILED
        error = None if status is BlockStatus.SUCCEEDED else ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, result.sanitized_summary, {"failure_class": result.failure_class.value if result.failure_class else None, "failed_requirement_ids": list(result.failed_requirement_ids), "public_requirement_summaries": dict(result.public_requirement_summaries), "requirement_manifest_hash": result.requirement_manifest_hash, "mapping_complete": result.mapping_complete})
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=value, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), metadata={"hidden_source_exposed": False})


def write_acceptance_receipt(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
