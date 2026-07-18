from __future__ import annotations

import json
import os
import pathlib
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

try:
    from . import browser_visual_evidence, canonical_evidence_hash, canonical_user_review, customer_runtime_runner, real_test_execution
except ImportError:
    import browser_visual_evidence
    import canonical_evidence_hash
    import canonical_user_review
    import customer_runtime_runner
    import real_test_execution


SCHEMA_VERSION = "1.0"
FINAL_PACKAGE_NAME = "final_project_bundle.zip"
MANIFEST_NAME = "delivery_manifest.json"
_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_ROOT_TOOL_DIRS = {".git", ".venv", "venv", "env", ".env", ".cgnk_test_env", ".cgkn_test_env", "node_modules", ".cgkn_review_history"}
_TEMP_SUFFIXES = {".tmp", ".pyc"}
_OLD_DELIVERY_RE = re.compile(r"^final_project_bundle(?:[._-].*)?\.zip$", re.I)
RESERVED_FIELDS = {
    "kind",
    "schema_version",
    "run_id",
    "candidate_id",
    "candidate_hash",
    "commit_sha",
    "producer",
    "created_at",
    "status",
    "artifact_hash",
    "source_tree_hash",
    "package_sha256",
    "package_entries_hash",
    "test_execution_ref",
    "test_execution_hash",
    "customer_runtime_ref",
    "customer_runtime_hash",
    "visual_evidence_ref",
    "visual_evidence_hash",
    "visual_required",
    "user_review_required",
    "user_review_request_ref",
    "user_review_request_hash",
    "user_review_ref",
    "user_review_hash",
    "project_dir",
    "package_path",
    "manifest_path",
    "inclusion_manifest",
    "failures",
    "known_limits",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: pathlib.Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_relative(path: pathlib.Path, root: pathlib.Path) -> str | None:
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    value = relative.as_posix()
    if not value or pathlib.PurePosixPath(value).is_absolute() or ".." in pathlib.PurePosixPath(value).parts:
        return None
    return value


def _is_excluded(relative: str) -> bool:
    pure = pathlib.PurePosixPath(relative)
    parts = pure.parts
    if set(parts) & _CACHE_DIRS:
        return True
    if parts and parts[0] in _ROOT_TOOL_DIRS:
        return True
    if pure.suffix.lower() in _TEMP_SUFFIXES:
        return True
    if relative in {
        MANIFEST_NAME, FINAL_PACKAGE_NAME, "packager_run_log.txt",
        canonical_user_review.REQUEST_FILE, canonical_user_review.REVIEW_FILE,
        canonical_user_review.REPLAY_LEDGER_FILE, "delivery_receipt.json",
    }:
        return True
    return False


def _is_old_delivery_bundle(relative: str) -> bool:
    pure = pathlib.PurePosixPath(relative)
    name = pure.name
    if name == FINAL_PACKAGE_NAME:
        return len(pure.parts) > 1
    return bool(_OLD_DELIVERY_RE.match(name))


def build_inclusion_manifest(project_dir: str | pathlib.Path) -> tuple[list[dict[str, Any]], list[str]]:
    project = pathlib.Path(project_dir).resolve()
    entries: list[dict[str, Any]] = []
    blockers: list[str] = []
    seen: set[str] = set()
    for path in sorted(project.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            relative = path.relative_to(project).as_posix()
            if _safe_relative(path, project) is None:
                blockers.append(f"outside_project_symlink:{relative}")
            continue
        if not path.is_file():
            continue
        relative = _safe_relative(path, project)
        if relative is None:
            blockers.append(f"outside_project:{path}")
            continue
        if _is_excluded(relative):
            continue
        if _is_old_delivery_bundle(relative):
            blockers.append(f"nested_delivery_bundle:{relative}")
            continue
        if relative in seen:
            blockers.append(f"duplicate_source_entry:{relative}")
            continue
        seen.add(relative)
        entries.append(
            {
                "relative_path": relative,
                "sha256": canonical_evidence_hash.sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    entries.sort(key=lambda item: item["relative_path"])
    return entries, sorted(set(blockers))


def package_entries_hash(entries: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "relative_path": str(item["relative_path"]),
            "sha256": str(item["sha256"]),
            "size_bytes": int(item["size_bytes"]),
        }
        for item in sorted(entries, key=lambda value: str(value["relative_path"]))
    ]
    return canonical_evidence_hash.sha256_bytes(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def inspect_zip_entries(package_path: str | pathlib.Path) -> dict[str, Any]:
    package = pathlib.Path(package_path)
    failures: list[str] = []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(package, "r") as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                pure = pathlib.PurePosixPath(name)
                if info.is_dir():
                    continue
                if pure.is_absolute() or name.startswith("/") or re.match(r"^[A-Za-z]:/", name):
                    failures.append(f"absolute_archive_member:{name}")
                    continue
                if ".." in pure.parts:
                    failures.append(f"archive_path_traversal:{name}")
                    continue
                if name in seen:
                    failures.append(f"duplicate_archive_member:{name}")
                    continue
                seen.add(name)
                data = archive.read(info)
                entries.append(
                    {
                        "relative_path": name,
                        "sha256": canonical_evidence_hash.sha256_bytes(data),
                        "size_bytes": len(data),
                    }
                )
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        failures.append(f"package_unreadable:{type(exc).__name__}")
    entries.sort(key=lambda item: item["relative_path"])
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "entries": entries,
        "package_entries_hash": package_entries_hash(entries) if not failures else "",
        "failures": sorted(set(failures)),
    }


def _evidence_record(project: pathlib.Path, kind: str, required: bool) -> tuple[dict[str, Any], list[str]]:
    if kind == "test":
        path = project / "test_execution.json"
        inspection = real_test_execution.inspect_test_report(project)
    elif kind == "runtime":
        path = project / "customer_runtime.json"
        inspection = customer_runtime_runner.inspect(project)
    else:
        path = project / "visual_evidence.json"
        inspection = browser_visual_evidence.inspect(project) if path.is_file() else {"status": "NOT_EVALUATED", "details": {}}
    failures: list[str] = []
    if required and (not path.is_file() or inspection.get("status") != "PASS"):
        failures.append(f"{kind}_evidence_not_pass")
    details = inspection.get("details", {}) if isinstance(inspection.get("details"), dict) else {}
    return {
        "path": path,
        "ref": str(path.resolve()) if path.is_file() else "",
        "hash": canonical_evidence_hash.sha256_file(path) if path.is_file() else "",
        "details": details,
        "inspection": inspection,
    }, failures


def _identity_failures(records: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    fields = ("run_id", "candidate_id", "candidate_hash", "commit_sha")
    failures: list[str] = []
    identity: dict[str, str] = {}
    for field in fields:
        values = {str(record["details"].get(field, "")).strip() for record in records}
        values.discard("")
        if len(values) != 1:
            failures.append(f"identity_mismatch:{field}")
        else:
            identity[field] = next(iter(values))
    return identity, failures


def build_canonical_package(
    project_dir: str | pathlib.Path,
    *,
    output_dir: str | pathlib.Path | None = None,
    startup_command: str = "",
    known_limits: list[str] | None = None,
    visual_required: bool = False,
    user_review_required: bool = False,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    target = pathlib.Path(output_dir).resolve() if output_dir else project
    target.mkdir(parents=True, exist_ok=True)
    package = target / FINAL_PACKAGE_NAME
    manifest_path = target / MANIFEST_NAME
    temp_package = target / f".{FINAL_PACKAGE_NAME}.{os.getpid()}.tmp"
    test_record, test_failures = _evidence_record(project, "test", True)
    runtime_record, runtime_failures = _evidence_record(project, "runtime", True)
    visual_record, visual_failures = _evidence_record(project, "visual", visual_required)
    required_records = [test_record, runtime_record] + ([visual_record] if visual_required else [])
    evidence_hashes_before = {
        str(record["path"].resolve()): record["hash"]
        for record in required_records
        if record["ref"]
    }
    identity, identity_failures = _identity_failures(required_records)
    before_source_manifest = canonical_evidence_hash.candidate_source_manifest(project)
    before_source_hash = canonical_evidence_hash.candidate_source_hash(project)
    inclusion, inclusion_blockers = build_inclusion_manifest(project)
    extra = dict(extra_fields or {})
    reserved_attempts = sorted(RESERVED_FIELDS & set(extra))
    failures = (
        test_failures
        + runtime_failures
        + visual_failures
        + identity_failures
        + inclusion_blockers
        + [f"reserved_extra_field:{field}" for field in reserved_attempts]
    )
    review_inspection = canonical_user_review.inspect_user_review_evidence(project) if user_review_required else {
        "status": "NOT_EVALUATED",
        "details": {},
    }
    if user_review_required and review_inspection.get("status") != "PASS":
        failures.extend(review_inspection.get("failures", ["user_review_not_pass"]))
    if user_review_required:
        review_details = review_inspection.get("details", {}) if isinstance(review_inspection.get("details"), dict) else {}
        request_details = canonical_user_review.inspect_user_review_request(project).get("details", {})
        if review_details.get("visual_required") is not bool(visual_required):
            failures.append("user_review_visual_requirement_mismatch")
        if not isinstance(request_details, dict) or request_details.get("visual_required") is not bool(visual_required):
            failures.append("user_review_request_visual_requirement_mismatch")
    review_path = project / canonical_user_review.REVIEW_FILE
    review_request_path = project / canonical_user_review.REQUEST_FILE
    if identity.get("candidate_hash") != before_source_hash:
        failures.append("source_tree_hash_candidate_hash_mismatch")
    limits = [str(item) for item in known_limits or [] if str(item).strip()]
    try:
        if failures or limits:
            if package.exists():
                package.unlink()
        else:
            with zipfile.ZipFile(temp_package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for entry in inclusion:
                    archive.write(project / entry["relative_path"], entry["relative_path"])
            actual = inspect_zip_entries(temp_package)
            if actual["status"] != "PASS" or actual["entries"] != inclusion:
                failures.extend(actual["failures"] or ["package_entries_mismatch"])
            after_source_manifest = canonical_evidence_hash.candidate_source_manifest(project)
            after_source_hash = canonical_evidence_hash.candidate_source_hash(project)
            if before_source_manifest != after_source_manifest or before_source_hash != after_source_hash:
                failures.append("source_changed_during_packaging")
            evidence_hashes_after = {
                value: canonical_evidence_hash.sha256_file(value)
                for value in evidence_hashes_before
                if pathlib.Path(value).is_file()
            }
            if evidence_hashes_before != evidence_hashes_after:
                failures.append("evidence_changed_during_packaging")
            if failures:
                temp_package.unlink(missing_ok=True)
                package.unlink(missing_ok=True)
            else:
                temp_package.replace(package)
    finally:
        temp_package.unlink(missing_ok=True)
    status = "PASS" if not failures and not limits and package.is_file() else ("PASS_WITH_LIMITS" if limits and not failures else "NEEDS_REWORK")
    package_hash = canonical_evidence_hash.sha256_file(package) if status == "PASS" else ""
    entries_hash = inspect_zip_entries(package).get("package_entries_hash", "") if status == "PASS" else ""
    manifest: dict[str, Any] = {
        "kind": "CGKNDeliveryManifest",
        "schema_version": SCHEMA_VERSION,
        "run_id": identity.get("run_id", ""),
        "candidate_id": identity.get("candidate_id", ""),
        "candidate_hash": identity.get("candidate_hash", ""),
        "commit_sha": identity.get("commit_sha", ""),
        "producer": "scripts/canonical_delivery_manifest.py",
        "created_at": _now(),
        "status": status,
        "artifact_hash": "",
        "source_tree_hash": before_source_hash,
        "package_sha256": package_hash,
        "package_entries_hash": entries_hash,
        "test_execution_ref": test_record["ref"],
        "test_execution_hash": test_record["hash"],
        "customer_runtime_ref": runtime_record["ref"],
        "customer_runtime_hash": runtime_record["hash"],
        "visual_evidence_ref": visual_record["ref"] if visual_required else "",
        "visual_evidence_hash": visual_record["hash"] if visual_required else "",
        "visual_required": bool(visual_required),
        "user_review_required": bool(user_review_required),
        "user_review_request_ref": str(review_request_path.resolve()) if user_review_required and review_request_path.is_file() else "",
        "user_review_request_hash": canonical_evidence_hash.sha256_file(review_request_path) if user_review_required and review_request_path.is_file() else "",
        "user_review_ref": str(review_path.resolve()) if user_review_required and review_path.is_file() else "",
        "user_review_hash": canonical_evidence_hash.sha256_file(review_path) if user_review_required and review_path.is_file() else "",
        "project_dir": str(project),
        "package_path": str(package),
        "manifest_path": str(manifest_path),
        "startup_command": startup_command,
        "known_limits": limits,
        "inclusion_manifest": inclusion,
        "failures": sorted(set(failures)),
    }
    manifest.update({key: value for key, value in extra.items() if key not in RESERVED_FIELDS})
    manifest["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(manifest, ("artifact_hash",))
    _write_json(manifest_path, manifest)
    if manifest["status"] == "PASS":
        self_inspection = inspect_canonical_delivery_manifest(project, manifest, visual_required=visual_required)
        if self_inspection.get("status") != "PASS":
            package.unlink(missing_ok=True)
            manifest["status"] = "NEEDS_REWORK"
            manifest["package_sha256"] = ""
            manifest["package_entries_hash"] = ""
            manifest["failures"] = sorted(
                set(manifest["failures"] + ["producer_self_inspection_failed"] + self_inspection.get("failures", []))
            )
            manifest["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(manifest, ("artifact_hash",))
            _write_json(manifest_path, manifest)
    return manifest


def inspect_canonical_delivery_manifest(
    project_dir: str | pathlib.Path,
    manifest: dict[str, Any] | str | pathlib.Path | None = None,
    *,
    visual_required: bool | None = None,
    user_review_required: bool | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    manifest_path = project / MANIFEST_NAME
    argument_mismatch = False
    if isinstance(manifest, (str, pathlib.Path)):
        manifest_path = pathlib.Path(manifest)
        document = _read_json(manifest_path)
    elif isinstance(manifest, dict):
        document = dict(manifest)
        declared_path = str(document.get("manifest_path", "")).strip()
        if declared_path:
            manifest_path = pathlib.Path(declared_path)
        disk_document = _read_json(manifest_path)
        if disk_document and disk_document != document:
            argument_mismatch = True
            document = disk_document
    else:
        document = _read_json(manifest_path)
    failures: list[str] = []
    if not manifest_path.is_file() or manifest_path.is_symlink():
        failures.append("manifest_path_invalid")
    if argument_mismatch:
        failures.append("manifest_argument_mismatch")
    declared_manifest_path = pathlib.Path(str(document.get("manifest_path", "")))
    try:
        if (
            not declared_manifest_path.is_absolute()
            or declared_manifest_path.is_symlink()
            or declared_manifest_path.resolve(strict=True) != manifest_path.resolve(strict=True)
        ):
            failures.append("manifest_path_mismatch")
    except (OSError, ValueError):
        failures.append("manifest_path_mismatch")
    required_fields = (
        "kind", "schema_version", "run_id", "candidate_id", "candidate_hash", "commit_sha", "producer",
        "created_at", "status", "artifact_hash", "source_tree_hash", "package_sha256", "package_entries_hash",
        "test_execution_ref", "test_execution_hash", "customer_runtime_ref", "customer_runtime_hash",
    )
    if any(not str(document.get(field, "")).strip() for field in required_fields):
        failures.append("canonical_fields_missing")
    if document.get("kind") != "CGKNDeliveryManifest" or document.get("schema_version") != SCHEMA_VERSION:
        failures.append("manifest_contract")
    if document.get("status") != "PASS":
        failures.append(f"manifest_status:{document.get('status', '')}")
    if document.get("known_limits"):
        failures.append("known_limits_nonempty")
    expected_artifact_hash = canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)) if document else ""
    if document.get("artifact_hash") != expected_artifact_hash:
        failures.append("artifact_hash_mismatch")
    current_source_hash = canonical_evidence_hash.candidate_source_hash(project)
    if document.get("source_tree_hash") != current_source_hash or document.get("candidate_hash") != current_source_hash:
        failures.append("source_tree_hash_mismatch")
    package = pathlib.Path(str(document.get("package_path", "")))
    package_path_valid = True
    try:
        package_resolved = package.resolve(strict=True)
        manifest_parent = manifest_path.resolve(strict=True).parent
        if (
            not package.is_absolute()
            or package.is_symlink()
            or package_resolved.name != FINAL_PACKAGE_NAME
            or package_resolved.parent != manifest_parent
        ):
            package_path_valid = False
    except (OSError, ValueError):
        package_path_valid = False
    if not package_path_valid:
        failures.append("package_manifest_directory_mismatch")
    if not package_path_valid or not package.is_file() or package.name != FINAL_PACKAGE_NAME:
        failures.append("package_missing")
        actual_package_hash = ""
        zip_result = {"status": "NEEDS_REWORK", "entries": [], "package_entries_hash": "", "failures": ["package_missing"]}
    else:
        actual_package_hash = canonical_evidence_hash.sha256_file(package)
        zip_result = inspect_zip_entries(package)
    if document.get("package_sha256") != actual_package_hash:
        failures.append("package_sha256_mismatch")
    if zip_result.get("status") != "PASS":
        failures.extend(zip_result.get("failures", []))
    if document.get("package_entries_hash") != zip_result.get("package_entries_hash"):
        failures.append("package_entries_hash_mismatch")
    declared_entries = document.get("inclusion_manifest", [])
    if not isinstance(declared_entries, list) or declared_entries != zip_result.get("entries"):
        failures.append("package_entry_manifest_mismatch")
    if visual_required is None:
        visual_required = bool(document.get("visual_required"))
    if document.get("visual_required") is not bool(visual_required):
        failures.append("visual_requirement_mismatch")
    if user_review_required is None:
        user_review_required = bool(document.get("user_review_required"))
    if bool(document.get("user_review_required")) != bool(user_review_required):
        failures.append("user_review_requirement_mismatch")
    evidence_specs = [
        ("test", "test_execution_ref", "test_execution_hash", True),
        ("runtime", "customer_runtime_ref", "customer_runtime_hash", True),
        ("visual", "visual_evidence_ref", "visual_evidence_hash", bool(visual_required)),
    ]
    records: list[dict[str, Any]] = []
    for kind, ref_field, hash_field, required in evidence_specs:
        ref = str(document.get(ref_field, "")).strip()
        if not required and not ref:
            continue
        path = pathlib.Path(ref)
        record, record_failures = _evidence_record(project, kind, required)
        records.append(record)
        failures.extend(record_failures)
        if not path.is_file() or path.resolve() != record["path"].resolve():
            failures.append(f"{kind}_evidence_ref")
        elif document.get(hash_field) != canonical_evidence_hash.sha256_file(path):
            failures.append(f"{kind}_evidence_hash")
    identity, identity_failures = _identity_failures(records)
    failures.extend(identity_failures)
    for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
        if document.get(field) != identity.get(field):
            failures.append(f"manifest_identity:{field}")
    if user_review_required:
        request_inspection = canonical_user_review.inspect_user_review_request(project)
        review_inspection = canonical_user_review.inspect_user_review_evidence(project)
        request_path = project / canonical_user_review.REQUEST_FILE
        review_path = project / canonical_user_review.REVIEW_FILE
        review_details = review_inspection.get("details", {}) if isinstance(review_inspection.get("details"), dict) else {}
        request_details = request_inspection.get("details", {}) if isinstance(request_inspection.get("details"), dict) else {}
        if request_inspection.get("status") != "PASS":
            failures.extend(request_inspection.get("failures", ["user_review_request_not_pass"]))
        if document.get("user_review_request_ref") != str(request_path.resolve()):
            failures.append("user_review_request_ref")
        if not request_path.is_file() or document.get("user_review_request_hash") != canonical_evidence_hash.sha256_file(request_path):
            failures.append("user_review_request_hash")
        if review_inspection.get("status") != "PASS":
            failures.extend(review_inspection.get("failures", ["user_review_not_pass"]))
        if document.get("user_review_ref") != str(review_path.resolve()):
            failures.append("user_review_ref")
        if not review_path.is_file() or document.get("user_review_hash") != canonical_evidence_hash.sha256_file(review_path):
            failures.append("user_review_hash")
        if review_details.get("reviewed_candidate_hash") != document.get("candidate_hash"):
            failures.append("user_review_candidate_hash")
        if request_details.get("visual_required") is not bool(visual_required):
            failures.append("user_review_request_visual_requirement_mismatch")
        if review_details.get("visual_required") is not bool(visual_required):
            failures.append("user_review_visual_requirement_mismatch")
        for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
            if review_details.get(field) != document.get(field):
                failures.append(f"user_review_identity:{field}")
    elif any(document.get(field) for field in (
        "user_review_request_ref", "user_review_request_hash", "user_review_ref", "user_review_hash"
    )):
        failures.append("unexpected_user_review")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "failures": sorted(set(failures)),
        "manifest": document,
        "manifest_path": str(manifest_path),
        "package_path": str(package),
        "package_sha256": actual_package_hash,
        "package_entries_hash": zip_result.get("package_entries_hash", ""),
        "source_tree_hash": current_source_hash,
        "zip_inspection": zip_result,
    }
