from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import uuid
from typing import Any, Mapping

from cgkn.execution.contracts import utc_now
from cgkn.state import EventRecord, FileRunStore

from .lifecycle_contracts import (
    BuildLifecycleState,
    CandidateRevision,
    CandidateRevisionStatus,
    LifecycleTransition,
    ProviderAttemptReceipt,
    ValidationReceipt,
)


_EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".git"}
_FORBIDDEN_NAMES = {".env", "credentials.json", "secrets.json", "token", "api_key"}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_hash(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def capability_slug(capability_ref: str) -> str:
    return capability_ref.replace("@", "-").replace(".", "-")


class BuildLifecycleTransitionPolicy:
    _ALLOWED = {
        BuildLifecycleState.SPEC_READY: {BuildLifecycleState.ROUTE_FROZEN},
        BuildLifecycleState.ROUTE_FROZEN: {BuildLifecycleState.GENERATION_REQUESTED, BuildLifecycleState.CANDIDATE_CREATED},
        BuildLifecycleState.GENERATION_REQUESTED: {BuildLifecycleState.CANDIDATE_CREATED, BuildLifecycleState.PROVIDER_BLOCKED},
        BuildLifecycleState.CANDIDATE_CREATED: {BuildLifecycleState.VALIDATION_PENDING},
        BuildLifecycleState.VALIDATION_PENDING: {BuildLifecycleState.VALIDATING},
        BuildLifecycleState.VALIDATING: {
            BuildLifecycleState.VALIDATION_FAILED, BuildLifecycleState.REVALIDATION_REQUIRED,
            BuildLifecycleState.REPAIR_REQUIRED, BuildLifecycleState.ADMISSION_PENDING,
            BuildLifecycleState.BLOCKED_FRAMEWORK, BuildLifecycleState.BLOCKED_ENVIRONMENT,
            BuildLifecycleState.BLOCKED_EXTERNAL, BuildLifecycleState.NEEDS_REVIEW, BuildLifecycleState.REJECTED,
        },
        BuildLifecycleState.VALIDATION_FAILED: {
            BuildLifecycleState.REVALIDATION_REQUIRED, BuildLifecycleState.REPAIR_REQUIRED,
            BuildLifecycleState.BLOCKED_FRAMEWORK, BuildLifecycleState.BLOCKED_ENVIRONMENT,
            BuildLifecycleState.BLOCKED_EXTERNAL, BuildLifecycleState.NEEDS_REVIEW, BuildLifecycleState.REJECTED,
        },
        BuildLifecycleState.BLOCKED_FRAMEWORK: {BuildLifecycleState.REVALIDATION_REQUIRED},
        BuildLifecycleState.REVALIDATION_REQUIRED: {BuildLifecycleState.VALIDATING},
        BuildLifecycleState.REPAIR_REQUIRED: {BuildLifecycleState.REPAIR_REQUESTED},
        BuildLifecycleState.REPAIR_REQUESTED: {BuildLifecycleState.CANDIDATE_CREATED, BuildLifecycleState.PROVIDER_BLOCKED},
        BuildLifecycleState.PROVIDER_BLOCKED: {
            BuildLifecycleState.GENERATION_REQUESTED, BuildLifecycleState.REPAIR_REQUESTED,
            BuildLifecycleState.VALIDATION_PENDING, BuildLifecycleState.NEEDS_REVIEW,
        },
        BuildLifecycleState.BLOCKED_EXTERNAL: {BuildLifecycleState.ADMISSION_PENDING, BuildLifecycleState.VALIDATION_PENDING},
        BuildLifecycleState.BLOCKED_ENVIRONMENT: {BuildLifecycleState.VALIDATION_PENDING, BuildLifecycleState.NEEDS_REVIEW},
        BuildLifecycleState.NEEDS_REVIEW: {BuildLifecycleState.REVALIDATION_REQUIRED, BuildLifecycleState.REJECTED},
        BuildLifecycleState.ADMISSION_PENDING: {BuildLifecycleState.ADMITTED, BuildLifecycleState.REJECTED},
        BuildLifecycleState.ADMITTED: {BuildLifecycleState.INSTALLED},
        BuildLifecycleState.INSTALLED: {BuildLifecycleState.RESUMED},
        BuildLifecycleState.RESUMED: set(),
        BuildLifecycleState.REJECTED: set(),
    }

    def validate(self, from_state: BuildLifecycleState, to_state: BuildLifecycleState) -> None:
        if to_state not in self._ALLOWED.get(from_state, set()):
            raise ValueError(f"ILLEGAL_LIFECYCLE_TRANSITION:{from_state.value}->{to_state.value}")


class CandidateRevisionStore:
    """Immutable candidate revisions backed by FileRunStore atomic state and event authority."""

    def __init__(self, artifact_root: pathlib.Path | str):
        self.root = pathlib.Path(artifact_root).resolve()
        self.file_store = FileRunStore(self.root / "candidate_runs")
        self.transition_policy = BuildLifecycleTransitionPolicy()
        self.index_path = self.file_store.root / "candidate_revision_index.json"

    def run_dir(self, capability_ref: str, build_run_id: str) -> pathlib.Path:
        return self.file_store.run_dir(capability_slug(capability_ref), build_run_id)

    def initialize_run(self, capability_ref: str, build_run_id: str, *, spec_hash: str, route_snapshot_hash: str) -> pathlib.Path:
        path = self.run_dir(capability_ref, build_run_id) / "build_state.json"
        if path.exists():
            return path
        value = {
            "kind": "CandidateBuildState", "schema_version": "1.0", "capability_ref": capability_ref,
            "build_run_id": build_run_id, "state": BuildLifecycleState.SPEC_READY.value,
            "spec_hash": spec_hash, "route_snapshot_hash": route_snapshot_hash,
            "current_revision_id": None, "last_action": None, "updated_at": utc_now(),
        }
        self.file_store.atomic_json(path, value)
        self.file_store.append_event(EventRecord(
            f"event.{uuid.uuid4().hex}", capability_slug(capability_ref), build_run_id,
            "LIFECYCLE_INITIALIZED", data={"state": BuildLifecycleState.SPEC_READY.value, "spec_hash": spec_hash},
        ))
        return path

    def load_state(self, capability_ref: str, build_run_id: str) -> dict[str, Any]:
        return json.loads((self.run_dir(capability_ref, build_run_id) / "build_state.json").read_text(encoding="utf-8"))

    def transition(
        self,
        capability_ref: str,
        build_run_id: str,
        to_state: BuildLifecycleState,
        *,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
        actor: str = "CapabilityBuildLifecycleService",
        current_revision_id: str | None = None,
        last_action: str | None = None,
    ) -> LifecycleTransition:
        state = self.load_state(capability_ref, build_run_id)
        from_state = BuildLifecycleState(str(state["state"]))
        self.transition_policy.validate(from_state, to_state)
        transition = LifecycleTransition(from_state, to_state, reason, evidence_refs, actor, utc_now())
        self.file_store.append_event(EventRecord(
            f"event.{uuid.uuid4().hex}", capability_slug(capability_ref), build_run_id,
            "LIFECYCLE_TRANSITION", data=transition.as_dict(),
        ))
        state.update({"state": to_state.value, "updated_at": transition.timestamp})
        if current_revision_id is not None:
            state["current_revision_id"] = current_revision_id
        if last_action is not None:
            state["last_action"] = last_action
        self.file_store.atomic_json(self.run_dir(capability_ref, build_run_id) / "build_state.json", state)
        return transition

    def create_revision(
        self,
        source: pathlib.Path | str,
        *,
        capability_ref: str,
        build_run_id: str,
        spec_hash: str,
        route_snapshot_hash: str,
        provider_id: str,
        provider_request_id: str = "",
        provider_response_id: str = "",
        provider_operation: str = "GENERATION",
        creation_reason: str = "PROVIDER_GENERATION",
        parent_revision_id: str | None = None,
    ) -> CandidateRevision:
        source_path = pathlib.Path(source).resolve()
        if not source_path.is_dir():
            raise ValueError("candidate source directory is required")
        parent = self.load_revision(parent_revision_id) if parent_revision_id else None
        if parent and (parent.capability_ref != capability_ref or parent.build_run_id != build_run_id):
            raise ValueError("candidate revision parent belongs to another build")
        number = parent.revision_number + 1 if parent else 1
        revision_id = f"{capability_slug(capability_ref)}.{build_run_id}.r{number:04d}"
        run_dir = self.run_dir(capability_ref, build_run_id)
        revisions = run_dir / "revisions"
        revisions.mkdir(parents=True, exist_ok=True)
        target = revisions / f"r{number:04d}"
        if target.exists() or revision_id in self._index():
            raise FileExistsError(f"candidate revision already exists: {revision_id}")
        staging = pathlib.Path(tempfile.mkdtemp(prefix=f".r{number:04d}.", dir=revisions))
        try:
            destination = staging / "source"
            destination.mkdir()
            rows: list[dict[str, Any]] = []
            for item in sorted(source_path.rglob("*")):
                if not item.is_file() or any(part in _EXCLUDED_PARTS for part in item.relative_to(source_path).parts):
                    continue
                relative = item.relative_to(source_path).as_posix()
                if item.name.lower() in _FORBIDDEN_NAMES or any(token in item.name.lower() for token in ("credential", "secret")):
                    raise ValueError(f"credential-like candidate file is forbidden: {relative}")
                output = destination / pathlib.PurePosixPath(relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, output)
                rows.append({"path": relative, "sha256": file_hash(output), "bytes": output.stat().st_size})
            if not rows:
                raise ValueError("candidate revision cannot be empty")
            source_hash = canonical_hash(rows)
            executor = next((row for row in rows if row["path"] == "executor.py"), None)
            package_hash = str(executor["sha256"] if executor else source_hash)
            revision = CandidateRevision(
                revision_id, capability_ref, build_run_id, number, parent_revision_id, spec_hash,
                route_snapshot_hash, provider_id, provider_request_id, provider_response_id,
                provider_operation, tuple(rows), source_hash, package_hash, utc_now(), creation_reason,
                CandidateRevisionStatus.CREATED,
            )
            self._durable_json(staging / "manifest.json", {"kind": "CandidateSourceManifest", "schema_version": "1.0", "files": rows, "source_hash": source_hash, "total_bytes": sum(row["bytes"] for row in rows), "contains_credentials": False})
            self._durable_json(staging / "revision.json", revision.as_dict())
            (staging / "validations").mkdir()
            self._fsync_directory(staging)
            os.replace(staging, target)
            self._fsync_directory(revisions)
            index = self._index()
            index[revision_id] = target.relative_to(self.root).as_posix()
            self.file_store.atomic_json(self.index_path, {"kind": "CandidateRevisionIndex", "schema_version": "1.0", "revisions": index, "contains_credentials": False})
            return revision
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def load_revision(self, revision_id: str | None) -> CandidateRevision:
        if not revision_id:
            raise ValueError("candidate revision id is required")
        relative = self._index().get(revision_id)
        if not relative:
            raise KeyError(f"candidate revision not found: {revision_id}")
        root = (self.root / relative).resolve()
        revision = CandidateRevision.from_dict(json.loads((root / "revision.json").read_text(encoding="utf-8")))
        rows = []
        for expected in revision.source_manifest:
            path = root / "source" / pathlib.PurePosixPath(str(expected["path"]))
            actual = {"path": str(expected["path"]), "sha256": file_hash(path), "bytes": path.stat().st_size}
            if actual != dict(expected):
                raise ValueError(f"CANDIDATE_REVISION_IMMUTABILITY_VIOLATION:{revision_id}:{actual['path']}")
            rows.append(actual)
        if canonical_hash(rows) != revision.source_hash:
            raise ValueError(f"CANDIDATE_REVISION_IMMUTABILITY_VIOLATION:{revision_id}")
        return revision

    def revision_path(self, revision_id: str) -> pathlib.Path:
        relative = self._index().get(revision_id)
        if not relative:
            raise KeyError(revision_id)
        return (self.root / relative).resolve()

    def source_path(self, revision_id: str) -> pathlib.Path:
        self.load_revision(revision_id)
        return self.revision_path(revision_id) / "source"

    def save_validation(self, receipt: ValidationReceipt) -> pathlib.Path:
        revision = self.load_revision(receipt.candidate_revision_id)
        if revision.source_hash != receipt.candidate_source_hash or revision.spec_hash != receipt.spec_hash:
            raise ValueError("validation receipt is not source-bound to the candidate revision")
        path = self.revision_path(revision.revision_id) / "validations" / f"{receipt.validation_id}.json"
        if path.exists():
            raise FileExistsError(f"validation receipt already exists: {receipt.validation_id}")
        self.file_store.atomic_json(path, receipt.as_dict())
        return path

    def save_provider_attempt(self, capability_ref: str, build_run_id: str, receipt: ProviderAttemptReceipt) -> pathlib.Path:
        path = self.run_dir(capability_ref, build_run_id) / "provider_attempts" / f"{receipt.attempt_id}.json"
        if path.exists():
            raise FileExistsError(f"provider attempt already exists: {receipt.attempt_id}")
        self.file_store.atomic_json(path, receipt.as_dict())
        return path

    def validation_receipts(self, revision_id: str) -> tuple[dict[str, Any], ...]:
        root = self.revision_path(revision_id) / "validations"
        return tuple(json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json")))

    def events(self, capability_ref: str, build_run_id: str):
        return self.file_store.load_events(capability_slug(capability_ref), build_run_id)

    def _index(self) -> dict[str, str]:
        if not self.index_path.is_file():
            return {}
        return {str(key): str(value) for key, value in json.loads(self.index_path.read_text(encoding="utf-8")).get("revisions", {}).items()}

    @staticmethod
    def _durable_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: pathlib.Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
