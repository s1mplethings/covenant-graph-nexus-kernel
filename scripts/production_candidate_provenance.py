from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

from contracts.production_candidate_provenance import (
    FILE_NAME,
    KIND,
    PRODUCER,
    SCHEMA_VERSION,
    STAGE_KIND,
)
from scripts import canonical_evidence_hash


ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTION_CANDIDATE_ROOT = (ROOT / "generated" / "codex_provider_projects").resolve()
PRODUCTION_ENTRYPOINT = "scripts.codex_conversation.start_generation_from_income"
GENERATION_FUNCTION = "scripts.codex_conversation.run_provider_generation_job"
STAGE_ORDER = (
    "production_entry",
    "provider_generation",
    "provider_validation",
    "post_build",
)
STAGE_FUNCTIONS = {
    "production_entry": PRODUCTION_ENTRYPOINT,
    "provider_generation": GENERATION_FUNCTION,
    "provider_validation": "scripts.codex_conversation.validate_provider_generation_output",
    "post_build": "scripts.codex_conversation.post_build_finalize_provider_project",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _write_hashed(path: pathlib.Path, document: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _manifest_hash(manifest: dict[str, str]) -> str:
    return canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": manifest}, ()
    )


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_relative_to(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_has_symlink(path: pathlib.Path, *, stop: pathlib.Path | None = None) -> bool:
    current = path
    boundary = stop.resolve() if stop else None
    while True:
        if current.is_symlink() or (
            hasattr(current, "is_junction") and current.is_junction()
        ):
            return True
        if boundary is not None and current == boundary:
            return False
        if current.parent == current:
            return False
        current = current.parent


def _candidate_symlinks(candidate: pathlib.Path) -> list[str]:
    if not candidate.exists():
        return []
    return sorted(
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_symlink()
        or (hasattr(path, "is_junction") and path.is_junction())
    )


def write_stage_receipt(
    production_run_dir: str | pathlib.Path,
    *,
    stage: str,
    run_id: str,
    candidate_id: str,
    commit_sha: str,
    candidate_root: str | pathlib.Path,
    started_at: str,
    finished_at: str | None = None,
    candidate_hash: str = "",
    candidate_source_manifest_hash: str = "",
    artifact_refs: list[dict[str, str]] | None = None,
) -> pathlib.Path:
    if stage not in STAGE_ORDER:
        raise ValueError(f"unsupported production stage: {stage}")
    run_root = pathlib.Path(production_run_dir).resolve()
    document: dict[str, Any] = {
        "kind": STAGE_KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "producer_function": STAGE_FUNCTIONS[stage],
        "created_at": finished_at or _now(),
        "status": "PASS",
        "artifact_hash": "",
        "stage": stage,
        "candidate_root": str(pathlib.Path(candidate_root).resolve()),
        "production_run_root": str(run_root),
        "started_at": started_at,
        "finished_at": finished_at or _now(),
        "candidate_source_manifest_hash": candidate_source_manifest_hash,
        "artifact_refs": artifact_refs or [],
    }
    return _write_hashed(run_root / f"{stage}_receipt.json", document)


def _inspect_stage_receipt(
    path: pathlib.Path,
    *,
    stage: str,
    run_root: pathlib.Path,
    candidate: pathlib.Path,
    run_id: str,
    candidate_id: str,
    commit_sha: str,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    expected_path = run_root / f"{stage}_receipt.json"
    if path != expected_path or not path.is_file() or path.is_symlink():
        return {}, [f"stage_receipt_path:{stage}"]
    document = _read(path)
    if (
        document.get("kind") != STAGE_KIND
        or document.get("schema_version") != SCHEMA_VERSION
        or document.get("producer") != PRODUCER
        or document.get("producer_function") != STAGE_FUNCTIONS[stage]
        or document.get("stage") != stage
        or document.get("status") != "PASS"
    ):
        failures.append(f"stage_receipt_contract:{stage}")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    ):
        failures.append(f"stage_receipt_hash:{stage}")
    for field, expected in (
        ("run_id", run_id),
        ("candidate_id", candidate_id),
        ("commit_sha", commit_sha),
        ("candidate_root", str(candidate)),
        ("production_run_root", str(run_root)),
    ):
        if str(document.get(field, "")) != str(expected):
            failures.append(f"stage_identity_mismatch:{stage}:{field}")
    if _parse_time(document.get("started_at")) is None or _parse_time(
        document.get("finished_at")
    ) is None:
        failures.append(f"stage_timestamp:{stage}")
    for artifact in (
        document.get("artifact_refs", [])
        if isinstance(document.get("artifact_refs"), list)
        else []
    ):
        if not isinstance(artifact, dict):
            failures.append(f"stage_artifact_contract:{stage}")
            continue
        ref_value = str(artifact.get("ref", "")).strip()
        ref = pathlib.Path(ref_value).resolve() if ref_value else pathlib.Path()
        if (
            not ref_value
            or not ref.is_file()
            or ref.is_symlink()
            or not _is_relative_to(ref, run_root)
            or artifact.get("hash") != canonical_evidence_hash.sha256_file(ref)
        ):
            failures.append(
                f"stage_artifact_invalid:{stage}:{artifact.get('role', 'unknown')}"
            )
    return document, failures


def produce(
    candidate_dir: str | pathlib.Path,
    production_run_dir: str | pathlib.Path,
    *,
    run_id: str,
    candidate_id: str,
    commit_sha: str,
    stage_receipts: dict[str, str | pathlib.Path],
    provider_result_ref: str | pathlib.Path,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    run_root = pathlib.Path(production_run_dir).resolve()
    allowed_root = PRODUCTION_CANDIDATE_ROOT.resolve()
    failures: list[str] = []
    if (
        not candidate.is_dir()
        or _path_has_symlink(candidate, stop=allowed_root)
        or not _is_relative_to(candidate, allowed_root)
    ):
        failures.append("candidate_path_invalid")
    if _candidate_symlinks(candidate):
        failures.append("candidate_symlink")
    manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    manifest_hash = _manifest_hash(manifest)
    if not manifest:
        failures.append("candidate_source_manifest_empty")
    inspected_receipts: dict[str, dict[str, Any]] = {}
    receipt_entries: list[dict[str, str]] = []
    previous_finished: datetime | None = None
    for stage in STAGE_ORDER:
        raw_ref = stage_receipts.get(stage)
        ref = pathlib.Path(raw_ref).resolve() if raw_ref else pathlib.Path()
        receipt, receipt_failures = _inspect_stage_receipt(
            ref,
            stage=stage,
            run_root=run_root,
            candidate=candidate,
            run_id=run_id,
            candidate_id=candidate_id,
            commit_sha=commit_sha,
        )
        failures.extend(receipt_failures)
        inspected_receipts[stage] = receipt
        if ref.is_file() and not ref.is_symlink():
            receipt_entries.append(
                {
                    "stage": stage,
                    "ref": str(ref),
                    "hash": canonical_evidence_hash.sha256_file(ref),
                }
            )
        started = _parse_time(receipt.get("started_at"))
        finished = _parse_time(receipt.get("finished_at"))
        if started and finished and started > finished:
            failures.append(f"stage_timestamp_order:{stage}")
        if previous_finished and started and started < previous_finished:
            failures.append(f"stage_sequence:{stage}")
        if finished:
            previous_finished = finished
    post_build = inspected_receipts.get("post_build", {})
    if post_build.get("candidate_hash") != candidate_hash:
        failures.append("post_build_candidate_hash_mismatch")
    if post_build.get("candidate_source_manifest_hash") != manifest_hash:
        failures.append("post_build_manifest_hash_mismatch")
    provider_result = pathlib.Path(provider_result_ref).resolve()
    if (
        not provider_result.is_file()
        or provider_result.is_symlink()
        or not _is_relative_to(provider_result, run_root)
    ):
        failures.append("provider_generation_artifact_invalid")
    provider_result_hash = (
        canonical_evidence_hash.sha256_file(provider_result)
        if provider_result.is_file() and not provider_result.is_symlink()
        else ""
    )
    generation_refs = inspected_receipts.get("provider_generation", {}).get(
        "artifact_refs", []
    )
    validation_refs = inspected_receipts.get("provider_validation", {}).get(
        "artifact_refs", []
    )
    for stage, refs in (
        ("provider_generation", generation_refs),
        ("provider_validation", validation_refs),
    ):
        if not any(
            isinstance(item, dict)
            and item.get("role") == "provider_generation_result"
            and pathlib.Path(str(item.get("ref", ""))).resolve() == provider_result
            and item.get("hash") == provider_result_hash
            for item in (refs if isinstance(refs, list) else [])
        ):
            failures.append(f"{stage}_provider_result_binding")
    if failures:
        raise ValueError("production provenance refused: " + ", ".join(sorted(set(failures))))
    document: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "created_at": _now(),
        "status": "PASS",
        "artifact_hash": "",
        "production_entrypoint": PRODUCTION_ENTRYPOINT,
        "generation_function": GENERATION_FUNCTION,
        "candidate_root": str(candidate),
        "production_run_root": str(run_root),
        "candidate_source_manifest": manifest,
        "candidate_source_manifest_hash": manifest_hash,
        "candidate_hash_method": "scripts.canonical_evidence_hash.candidate_source_hash",
        "stage_receipts": receipt_entries,
        "artifact_refs": [
            {
                "role": "provider_generation_result",
                "ref": str(provider_result),
                "hash": provider_result_hash,
            }
        ],
    }
    path = _write_hashed(run_root / FILE_NAME, document)
    result = dict(document)
    result["provenance_ref"] = str(path)
    result["provenance_hash"] = canonical_evidence_hash.sha256_file(path)
    return result


def inspect(
    provenance_ref: str | pathlib.Path,
    *,
    expected_candidate_dir: str | pathlib.Path | None = None,
    expected_production_run_dir: str | pathlib.Path | None = None,
    expected_run_id: str | None = None,
    expected_candidate_id: str | None = None,
    expected_candidate_hash: str | None = None,
    expected_commit_sha: str | None = None,
) -> dict[str, Any]:
    path = pathlib.Path(provenance_ref).resolve()
    failures: list[str] = []
    if path.name != FILE_NAME or not path.is_file() or path.is_symlink():
        return {
            "status": "NEEDS_REWORK",
            "failures": ["production_provenance_path_invalid"],
            "provenance_ref": str(path),
        }
    document = _read(path)
    if (
        document.get("kind") != KIND
        or document.get("schema_version") != SCHEMA_VERSION
        or document.get("producer") != PRODUCER
        or document.get("status") != "PASS"
        or document.get("production_entrypoint") != PRODUCTION_ENTRYPOINT
        or document.get("generation_function") != GENERATION_FUNCTION
        or document.get("candidate_hash_method")
        != "scripts.canonical_evidence_hash.candidate_source_hash"
    ):
        failures.append("production_provenance_contract")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    ):
        failures.append("production_provenance_artifact_hash")
    run_root_value = str(document.get("production_run_root", "")).strip()
    candidate_value = str(document.get("candidate_root", "")).strip()
    run_root = pathlib.Path(run_root_value).resolve() if run_root_value else pathlib.Path()
    candidate = pathlib.Path(candidate_value).resolve() if candidate_value else pathlib.Path()
    allowed_root = PRODUCTION_CANDIDATE_ROOT.resolve()
    if (
        not run_root_value
        or path.parent != run_root
        or (
            expected_production_run_dir is not None
            and run_root != pathlib.Path(expected_production_run_dir).resolve()
        )
    ):
        failures.append("production_run_path_mismatch")
    if (
        not candidate_value
        or not candidate.is_dir()
        or not _is_relative_to(candidate, allowed_root)
        or _path_has_symlink(candidate, stop=allowed_root)
        or (
            expected_candidate_dir is not None
            and candidate != pathlib.Path(expected_candidate_dir).resolve()
        )
    ):
        failures.append("candidate_path_invalid")
    symlinks = _candidate_symlinks(candidate)
    if symlinks:
        failures.append("candidate_symlink")
    for field, expected in (
        ("run_id", expected_run_id),
        ("candidate_id", expected_candidate_id),
        ("candidate_hash", expected_candidate_hash),
        ("commit_sha", expected_commit_sha),
    ):
        if expected is not None and str(document.get(field, "")) != str(expected):
            failures.append(f"provenance_identity_mismatch:{field}")
    run_id = str(document.get("run_id", ""))
    candidate_id = str(document.get("candidate_id", ""))
    commit_sha = str(document.get("commit_sha", ""))
    receipts = (
        document.get("stage_receipts", [])
        if isinstance(document.get("stage_receipts"), list)
        else []
    )
    if [item.get("stage") for item in receipts if isinstance(item, dict)] != list(
        STAGE_ORDER
    ):
        failures.append("stage_receipt_order")
    previous_finished: datetime | None = None
    inspected_receipts: dict[str, dict[str, Any]] = {}
    for stage in STAGE_ORDER:
        matches = [
            item
            for item in receipts
            if isinstance(item, dict) and item.get("stage") == stage
        ]
        if len(matches) != 1:
            failures.append(f"stage_receipt_missing:{stage}")
            continue
        entry = matches[0]
        ref = pathlib.Path(str(entry.get("ref", ""))).resolve()
        if (
            not ref.is_file()
            or ref.is_symlink()
            or entry.get("hash") != canonical_evidence_hash.sha256_file(ref)
        ):
            failures.append(f"stage_receipt_ref_hash:{stage}")
        receipt, receipt_failures = _inspect_stage_receipt(
            ref,
            stage=stage,
            run_root=run_root,
            candidate=candidate,
            run_id=run_id,
            candidate_id=candidate_id,
            commit_sha=commit_sha,
        )
        failures.extend(receipt_failures)
        inspected_receipts[stage] = receipt
        started = _parse_time(receipt.get("started_at"))
        finished = _parse_time(receipt.get("finished_at"))
        if started and finished and started > finished:
            failures.append(f"stage_timestamp_order:{stage}")
        if previous_finished and started and started < previous_finished:
            failures.append(f"stage_sequence:{stage}")
        if finished:
            previous_finished = finished
    created_at = _parse_time(document.get("created_at"))
    if created_at is None or (previous_finished and created_at < previous_finished):
        failures.append("provenance_timestamp_order")
    manifest = (
        document.get("candidate_source_manifest", {})
        if isinstance(document.get("candidate_source_manifest"), dict)
        else {}
    )
    recomputed_manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    recomputed_manifest_hash = _manifest_hash(recomputed_manifest)
    recomputed_candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    if not recomputed_manifest:
        failures.append("candidate_source_manifest_empty")
    if manifest != recomputed_manifest:
        failures.append("candidate_source_manifest_mismatch")
    if document.get("candidate_source_manifest_hash") != recomputed_manifest_hash:
        failures.append("candidate_source_manifest_hash_mismatch")
    if document.get("candidate_hash") != recomputed_candidate_hash:
        failures.append("candidate_hash_mismatch")
    if document.get("candidate_hash") == commit_sha:
        failures.append("commit_hash_used_as_candidate_hash")
    commit_digest = "sha256:" + hashlib.sha256(commit_sha.encode("utf-8")).hexdigest()
    if document.get("candidate_hash") == commit_digest:
        failures.append("commit_digest_used_as_candidate_hash")
    post_build = inspected_receipts.get("post_build", {})
    if post_build.get("candidate_hash") != recomputed_candidate_hash:
        failures.append("post_build_candidate_hash_mismatch")
    if post_build.get("candidate_source_manifest_hash") != recomputed_manifest_hash:
        failures.append("post_build_manifest_hash_mismatch")
    artifact_refs = (
        document.get("artifact_refs", [])
        if isinstance(document.get("artifact_refs"), list)
        else []
    )
    provider_refs = [
        item
        for item in artifact_refs
        if isinstance(item, dict) and item.get("role") == "provider_generation_result"
    ]
    if len(provider_refs) != 1:
        failures.append("provider_generation_artifact_missing")
    else:
        provider_entry = provider_refs[0]
        provider_ref = pathlib.Path(str(provider_entry.get("ref", ""))).resolve()
        if (
            not provider_ref.is_file()
            or provider_ref.is_symlink()
            or not _is_relative_to(provider_ref, run_root)
            or provider_entry.get("hash")
            != canonical_evidence_hash.sha256_file(provider_ref)
        ):
            failures.append("provider_generation_artifact_invalid")
        for stage in ("provider_generation", "provider_validation"):
            refs = inspected_receipts.get(stage, {}).get("artifact_refs", [])
            if not any(
                isinstance(item, dict)
                and item.get("role") == "provider_generation_result"
                and pathlib.Path(str(item.get("ref", ""))).resolve() == provider_ref
                and item.get("hash") == provider_entry.get("hash")
                for item in (refs if isinstance(refs, list) else [])
            ):
                failures.append(f"{stage}_provider_result_binding")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "failures": sorted(set(failures)),
        "provenance_ref": str(path),
        "provenance_hash": canonical_evidence_hash.sha256_file(path),
        "identity": {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_hash": str(document.get("candidate_hash", "")),
            "commit_sha": commit_sha,
        },
        "candidate_root": str(candidate),
        "production_run_root": str(run_root),
        "candidate_source_manifest": recomputed_manifest,
        "candidate_source_manifest_hash": recomputed_manifest_hash,
        "candidate_hash_recomputed": recomputed_candidate_hash,
        "document": document,
    }
