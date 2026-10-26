"""Best-effort application hook for observing software-project generation."""

from __future__ import annotations

import os
import pathlib
import re
from typing import Any, Mapping

from .store import CaptureResult, best_effort_capture


def _safe_id(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")[:96]
    return normalized or fallback


def _workspace_files(root: pathlib.Path) -> dict[str, bytes]:
    excluded = {".git", ".cgkn", ".venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}
    files: dict[str, bytes] = {}
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


class ProjectCorpusCaptureHook:
    """Collect bounded lifecycle snapshots and finalize one corpus attempt.

    The hook is dormant unless ``CGNK_PROJECT_CORPUS_ROOT`` is configured.  All
    methods are fail-soft so corpus I/O can never change the project result.
    """

    def __init__(
        self,
        *,
        workspace: pathlib.Path,
        project_id: str,
        run_id: str,
        source_version: str,
        generator_version: str,
        public_packet: Mapping[str, Any],
        metadata: Mapping[str, Any],
        private_evaluator_packet: Mapping[str, Any] | None = None,
        split: str | None = None,
    ):
        self.root = os.environ.get("CGNK_PROJECT_CORPUS_ROOT", "").strip()
        self.workspace = workspace
        self.family_id = _safe_id(project_id, "project")
        self.attempt_id = _safe_id(run_id, "attempt")
        self.run_id = _safe_id(run_id, "run")
        self.source_version = source_version
        self.generator_version = generator_version
        self.public_packet = dict(public_packet)
        self.metadata = dict(metadata)
        self.private_evaluator_packet = dict(private_evaluator_packet) if private_evaluator_packet is not None else None
        self.split = split
        self.snapshots: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.tests: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.repairs: list[dict[str, Any]] = []
        self.error_types: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.root)

    def observe(self, stage: str, *, metadata: Mapping[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        try:
            ordinal = len(self.snapshots) + 1
            parent = self.snapshots[-1]["snapshot_id"] if self.snapshots else ""
            self.snapshots.append(
                {
                    "snapshot_id": f"{self.attempt_id}-s{ordinal:03d}",
                    "stage": stage,
                    "parent_snapshot_id": parent,
                    "files": _workspace_files(self.workspace),
                    "metadata": dict(metadata or {}),
                }
            )
        except Exception as exc:  # capture is observational only
            self.error_types.append(type(exc).__name__)

    def record_failure(self, value: Mapping[str, Any]) -> None:
        if self.enabled:
            self.failures.append(dict(value))

    def record_test(self, value: Mapping[str, Any]) -> None:
        if self.enabled:
            self.tests.append(dict(value))

    def record_repair(self, value: Mapping[str, Any]) -> None:
        if self.enabled:
            self.repairs.append(dict(value))

    def record_event(self, value: Mapping[str, Any]) -> None:
        if self.enabled:
            self.events.append(dict(value))

    def finalize(self, status: str) -> CaptureResult:
        if not self.enabled:
            return CaptureResult("DISABLED")
        if not self.snapshots:
            self.observe("ABORTED")
        metadata = dict(self.metadata)
        metadata["capture_observer_errors"] = list(self.error_types)
        return best_effort_capture(
            self.root,
            family_id=self.family_id,
            attempt_id=self.attempt_id,
            run_id=self.run_id,
            source_version=self.source_version,
            generator_version=self.generator_version,
            status=status,
            provenance="generated_original",
            public_packet=self.public_packet,
            snapshots=self.snapshots,
            metadata=metadata,
            events=self.events,
            tests=self.tests,
            failures=self.failures,
            repairs=self.repairs,
            private_evaluator_packet=self.private_evaluator_packet,
            split=self.split,
        )
