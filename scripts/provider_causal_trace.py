from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone
from typing import Any

from contracts.provider_causal_trace import (
    APPLICATION_FILE,
    DECISION_FILE,
    FILE_NAME,
    KIND,
    PATCH_FILE,
    PRODUCER,
    REQUEST_FILE,
    RESPONSE_FILE,
    SCHEMA_VERSION,
)
from scripts import canonical_evidence_hash
from scripts import production_candidate_provenance


ROOT = pathlib.Path(__file__).resolve().parents[1]
CAUSAL_DIR_NAME = "provider_causal_artifacts"
PRODUCTION_ENTRYPOINT = "scripts.codex_conversation.start_generation_from_income"
GENERATION_FUNCTION = "scripts.codex_conversation.run_provider_generation_job"
INTERFACE_RESULT_FILE = "provider_interface_result.json"
HASH_FIELDS = ("artifact_hash",)
FORBIDDEN_REQUEST_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


def now() -> str:
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
        document, HASH_FIELDS
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


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


def _has_reparse_point(path: pathlib.Path, *, stop: pathlib.Path) -> bool:
    current = path
    boundary = stop.resolve()
    while True:
        if current.is_symlink() or (
            hasattr(current, "is_junction") and current.is_junction()
        ):
            return True
        if current == boundary or current.parent == current:
            return False
        current = current.parent


def _safe_relative_path(value: Any) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    pure = pathlib.PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or ".." in pure.parts
        or normalized.startswith("/")
    ):
        raise ValueError(f"unsafe provider patch path: {normalized!r}")
    return pure.as_posix()


def _manifest_hash(manifest: dict[str, str]) -> str:
    return canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": manifest}, ()
    )


def _content_map_hash(contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    # Mirror canonical_evidence_hash.iter_candidate_source_files ordering on
    # the active platform (notably Windows' case-insensitive Path ordering).
    for path in sorted(contents, key=pathlib.Path):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(contents[path])
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _snapshot(project: pathlib.Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for path in canonical_evidence_hash.iter_candidate_source_files(project):
        content = path.read_bytes()
        result.append(
            {
                "path": path.relative_to(project).as_posix(),
                "content_b64": base64.b64encode(content).decode("ascii"),
                "content_hash": canonical_evidence_hash.sha256_bytes(content),
            }
        )
    return result


def _snapshot_map(snapshot: list[dict[str, Any]]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for item in snapshot:
        if not isinstance(item, dict):
            raise ValueError("source snapshot contains a non-object item")
        path = _safe_relative_path(item.get("path"))
        encoded = item.get("content_b64")
        if not isinstance(encoded, str):
            raise ValueError(f"source snapshot content is not encoded: {path}")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError(f"source snapshot content is invalid: {path}") from exc
        expected_hash = canonical_evidence_hash.sha256_bytes(content)
        if item.get("content_hash") != expected_hash or path in result:
            raise ValueError(f"source snapshot hash or duplicate path: {path}")
        result[path] = content
    return result


def _manifest_from_contents(contents: dict[str, bytes]) -> dict[str, str]:
    return {
        path: canonical_evidence_hash.sha256_bytes(content)
        for path, content in sorted(contents.items())
    }


def _source_delta(
    before: dict[str, bytes], after: dict[str, bytes]
) -> list[dict[str, Any]]:
    delta: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        before_exists = path in before
        after_exists = path in after
        before_content = before.get(path, b"")
        after_content = after.get(path, b"")
        if before_exists == after_exists and before_content == after_content:
            continue
        core = {
            "path": path,
            "operation": (
                "create"
                if not before_exists
                else "delete"
                if not after_exists
                else "replace"
            ),
            "before_exists": before_exists,
            "after_exists": after_exists,
            "before_hash": canonical_evidence_hash.sha256_bytes(before_content),
            "after_hash": canonical_evidence_hash.sha256_bytes(after_content),
        }
        delta.append(
            {
                **core,
                "transition_hash": canonical_evidence_hash.canonical_json_hash(
                    core, ()
                ),
            }
        )
    return delta


def response_content_hash(files: list[dict[str, str]]) -> str:
    normalized = [
        {
            "path": _safe_relative_path(item.get("path")),
            "content": str(item.get("content", "")),
        }
        for item in files
        if isinstance(item, dict)
    ]
    return canonical_evidence_hash.canonical_json_hash({"files": normalized}, ())


def extract_decisions(response_document: dict[str, Any]) -> list[dict[str, str]]:
    files = response_document.get("response_content", {}).get("files", [])
    if not isinstance(files, list) or not files:
        raise ValueError("provider response content has no files")
    decisions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ValueError("provider response file is not an object")
        path = _safe_relative_path(item.get("path"))
        content = item.get("content")
        if path in seen or not isinstance(content, str):
            raise ValueError(f"invalid or duplicate provider response file: {path}")
        seen.add(path)
        content_hash = canonical_evidence_hash.sha256_bytes(
            content.encode("utf-8")
        )
        seed = {
            "response_identity": str(
                response_document.get("response_identity", "")
            ),
            "response_content_hash": str(
                response_document.get("response_content_hash", "")
            ),
            "ordinal": index,
            "path": path,
            "content_hash": content_hash,
        }
        decisions.append(
            {
                "decision_id": canonical_evidence_hash.canonical_json_hash(
                    seed, ()
                ),
                "path": path,
                "operation": "materialize_provider_response_file",
                "response_file_hash": content_hash,
                "implementation_result": f"write:{path}",
            }
        )
    return decisions


def build_patch_hunks(
    response_document: dict[str, Any],
    decisions: list[dict[str, str]],
    before_contents: dict[str, bytes],
) -> list[dict[str, Any]]:
    response_files = {
        _safe_relative_path(item.get("path")): str(item.get("content", ""))
        for item in response_document.get("response_content", {}).get("files", [])
        if isinstance(item, dict)
    }
    hunks: list[dict[str, Any]] = []
    for decision in decisions:
        path = _safe_relative_path(decision.get("path"))
        if path not in response_files:
            raise ValueError(f"decision has no response file: {path}")
        before_content = before_contents.get(path, b"")
        after_content = response_files[path]
        after_bytes = after_content.encode("utf-8")
        before_exists = path in before_contents
        before_hash = canonical_evidence_hash.sha256_bytes(before_content)
        after_hash = canonical_evidence_hash.sha256_bytes(after_bytes)
        if before_exists:
            try:
                before_text = before_content.decode("utf-8")
            except UnicodeDecodeError:
                before_text = None
            if before_content == after_bytes or (
                before_text is not None
                and before_text.replace("\r\n", "\n").replace("\r", "\n")
                == after_content.replace("\r\n", "\n").replace("\r", "\n")
            ):
                raise ValueError(
                    "provider patch would be a no-op instead of a causal write: "
                    f"{path}"
                )
        core = {
            "decision_id": str(decision.get("decision_id", "")),
            "path": path,
            "operation": "replace" if before_exists else "create",
            "before_exists": before_exists,
            "before_content_b64": base64.b64encode(before_content).decode("ascii"),
            "before_hash": before_hash,
            "after_content": after_content,
            "after_hash": after_hash,
            "before_line_count": len(before_content.splitlines()),
            "after_line_count": len(after_content.splitlines()),
        }
        hunks.append(
            {
                "hunk_id": canonical_evidence_hash.canonical_json_hash(core, ()),
                **core,
                "hunk_hash": canonical_evidence_hash.canonical_json_hash(
                    core, ()
                ),
            }
        )
    return hunks


def _identity_fields(identity: dict[str, str]) -> dict[str, str]:
    return {
        field: str(identity.get(field, ""))
        for field in ("run_id", "candidate_id", "commit_sha")
    }


def begin_provider_request(
    *,
    candidate_dir: str | pathlib.Path,
    production_run_dir: str | pathlib.Path,
    identity: dict[str, str],
    goal: str,
    model: str,
    request_started_at: str,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    run_root = pathlib.Path(production_run_dir).resolve()
    if not candidate.is_dir():
        raise ValueError("provider request requires a production candidate")
    if (
        not _is_relative_to(
            candidate, production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
        )
        or _has_reparse_point(
            candidate,
            stop=production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT,
        )
    ):
        raise ValueError("production candidate path is outside the formal root")
    before_manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    before_manifest_hash = _manifest_hash(before_manifest)
    before_candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    request_content = {
        **_identity_fields(identity),
        "goal": str(goal),
        "model": str(model),
        "provider_interface": "scripts.run_local_pipeline.execute",
        "allow_network": True,
        "allow_provider": True,
        "use_api": True,
        "candidate_before_provider_manifest": before_manifest,
        "candidate_before_provider_manifest_hash": before_manifest_hash,
        "candidate_before_provider_hash": before_candidate_hash,
    }
    request_content_hash = canonical_evidence_hash.canonical_json_hash(
        request_content, ()
    )
    request_identity = (
        f"{identity['run_id']}:provider-request:"
        f"{request_content_hash.split(':', 1)[-1][:16]}"
    )
    request_doc: dict[str, Any] = {
        "kind": "CGKNProviderRequestEvidence",
        "schema_version": SCHEMA_VERSION,
        **_identity_fields(identity),
        "candidate_hash": "",
        "producer": PRODUCER,
        "created_at": request_started_at,
        "status": "PASS",
        "artifact_hash": "",
        "request_identity": request_identity,
        "request_content": request_content,
        "request_content_hash": request_content_hash,
        "authentication_material_recorded": False,
    }
    request_path = _write_hashed(
        run_root / CAUSAL_DIR_NAME / REQUEST_FILE, request_doc
    )
    return {
        "request_ref": request_path,
        "request_hash": canonical_evidence_hash.sha256_file(request_path),
        "request_identity": request_identity,
        "request_content_hash": request_content_hash,
        "before_source_manifest": before_manifest,
        "before_source_manifest_hash": before_manifest_hash,
        "before_candidate_hash": before_candidate_hash,
    }


def consume_provider_response(
    *,
    candidate_dir: str | pathlib.Path,
    provider_staging_dir: str | pathlib.Path,
    production_run_dir: str | pathlib.Path,
    provider_result_path: str | pathlib.Path,
    identity: dict[str, str],
    provider_request_capture: dict[str, Any],
    response_received_at: str,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    staging = pathlib.Path(provider_staging_dir).resolve()
    run_root = pathlib.Path(production_run_dir).resolve()
    result_path = pathlib.Path(provider_result_path).resolve()
    causal_dir = run_root / CAUSAL_DIR_NAME
    if not candidate.is_dir() or not staging.is_dir() or not result_path.is_file():
        raise ValueError("provider causal capture requires candidate, staging and result")
    if _has_reparse_point(candidate, stop=production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT):
        raise ValueError("production candidate path contains a reparse point")
    request_path = pathlib.Path(
        provider_request_capture.get("request_ref", "")
    ).resolve()
    request_doc = _read(request_path)
    current_before_manifest = canonical_evidence_hash.candidate_source_manifest(
        candidate
    )
    current_before_manifest_hash = _manifest_hash(current_before_manifest)
    current_before_candidate_hash = canonical_evidence_hash.candidate_source_hash(
        candidate
    )
    if (
        request_path != causal_dir / REQUEST_FILE
        or not request_path.is_file()
        or request_path.is_symlink()
        or provider_request_capture.get("request_hash")
        != canonical_evidence_hash.sha256_file(request_path)
        or request_doc.get("artifact_hash")
        != canonical_evidence_hash.canonical_json_hash(request_doc, HASH_FIELDS)
        or any(
            str(request_doc.get(field, "")) != str(identity.get(field, ""))
            for field in ("run_id", "candidate_id", "commit_sha")
        )
        or request_doc.get("request_identity")
        != provider_request_capture.get("request_identity")
        or current_before_manifest
        != provider_request_capture.get("before_source_manifest")
        or current_before_manifest_hash
        != provider_request_capture.get("before_source_manifest_hash")
        or current_before_candidate_hash
        != provider_request_capture.get("before_candidate_hash")
    ):
        raise ValueError(
            "provider modified production candidate outside causal patch application"
        )
    provider_result = _read(result_path)
    generated_files = provider_result.get("generated_files", [])
    if not isinstance(generated_files, list) or not generated_files:
        raise ValueError("provider result has no generated_files response content")
    response_files: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_path in generated_files:
        rel = _safe_relative_path(raw_path)
        source = staging / pathlib.PurePosixPath(rel)
        resolved = source.resolve()
        if (
            rel in seen
            or not source.is_file()
            or source.is_symlink()
            or not _is_relative_to(resolved, staging)
            or _has_reparse_point(source, stop=staging)
        ):
            raise ValueError(f"provider response file is missing or unsafe: {rel}")
        seen.add(rel)
        with source.open("r", encoding="utf-8", newline="") as stream:
            response_files.append({"path": rel, "content": stream.read()})
    response_files.sort(key=lambda item: item["path"])
    causal_dir.mkdir(parents=True, exist_ok=True)
    interface_result = causal_dir / INTERFACE_RESULT_FILE
    shutil.copyfile(result_path, interface_result)
    request_identity = str(request_doc.get("request_identity", ""))
    content_hash = response_content_hash(response_files)
    supplied_response_id = str(
        provider_result.get("provider_response_id")
        or provider_result.get("response_id")
        or ""
    ).strip()
    response_identity = supplied_response_id or (
        f"{identity['run_id']}:provider-response:{content_hash.split(':', 1)[-1][:16]}"
    )
    response_doc: dict[str, Any] = {
        "kind": "CGKNProviderResponseEvidence",
        "schema_version": SCHEMA_VERSION,
        **_identity_fields(identity),
        "candidate_hash": "",
        "producer": PRODUCER,
        "created_at": response_received_at,
        "status": "PASS",
        "artifact_hash": "",
        "request_identity": request_identity,
        "provider_request_ref": str(request_path.resolve()),
        "provider_request_hash": canonical_evidence_hash.sha256_file(
            request_path
        ),
        "response_identity": response_identity,
        "response_content": {"files": response_files},
        "response_content_hash": content_hash,
        "provider_interface_result_ref": str(interface_result.resolve()),
        "provider_interface_result_hash": canonical_evidence_hash.sha256_file(
            interface_result
        ),
    }
    response_path = _write_hashed(causal_dir / RESPONSE_FILE, response_doc)
    decision_created_at = now()
    decisions = extract_decisions(response_doc)
    decision_content_hash = canonical_evidence_hash.canonical_json_hash(
        {"decisions": decisions}, ()
    )
    decision_doc: dict[str, Any] = {
        "kind": "CGKNProviderImplementationDecision",
        "schema_version": SCHEMA_VERSION,
        **_identity_fields(identity),
        "candidate_hash": "",
        "producer": PRODUCER,
        "created_at": decision_created_at,
        "status": "PASS",
        "artifact_hash": "",
        "provider_response_ref": str(response_path.resolve()),
        "provider_response_hash": canonical_evidence_hash.sha256_file(
            response_path
        ),
        "response_identity": response_identity,
        "response_content_hash": content_hash,
        "decision_extractor": "scripts.provider_causal_trace.extract_decisions",
        "decisions": decisions,
        "decision_content_hash": decision_content_hash,
    }
    decision_path = _write_hashed(causal_dir / DECISION_FILE, decision_doc)
    before_snapshot = _snapshot(candidate)
    before_contents = _snapshot_map(before_snapshot)
    before_manifest = _manifest_from_contents(before_contents)
    before_manifest_hash = _manifest_hash(before_manifest)
    before_candidate_hash = _content_map_hash(before_contents)
    hunks = build_patch_hunks(response_doc, decisions, before_contents)
    patch_content_hash = canonical_evidence_hash.canonical_json_hash(
        {"hunks": hunks}, ()
    )
    patch_doc: dict[str, Any] = {
        "kind": "CGKNProviderImplementationPatch",
        "schema_version": SCHEMA_VERSION,
        **_identity_fields(identity),
        "candidate_hash": "",
        "producer": PRODUCER,
        "created_at": now(),
        "status": "PASS",
        "artifact_hash": "",
        "decision_ref": str(decision_path.resolve()),
        "decision_hash": canonical_evidence_hash.sha256_file(decision_path),
        "decision_content_hash": decision_content_hash,
        "patch_builder": "scripts.provider_causal_trace.build_patch_hunks",
        "before_source_snapshot": before_snapshot,
        "before_source_manifest": before_manifest,
        "before_source_manifest_hash": before_manifest_hash,
        "before_candidate_hash": before_candidate_hash,
        "hunks": hunks,
        "patch_hunk_count": len(hunks),
        "patch_content_hash": patch_content_hash,
    }
    patch_path = _write_hashed(causal_dir / PATCH_FILE, patch_doc)
    application_started_at = now()
    applied_hunks: list[dict[str, str]] = []
    for hunk in hunks:
        rel = _safe_relative_path(hunk["path"])
        target = candidate / pathlib.PurePosixPath(rel)
        if target.is_symlink() or _has_reparse_point(target, stop=candidate):
            raise ValueError(f"provider patch target is a reparse point: {rel}")
        resolved_target = target.resolve()
        if not _is_relative_to(resolved_target, candidate):
            raise ValueError(f"provider patch target escaped candidate: {rel}")
        before_exists = target.is_file()
        before_content = target.read_bytes() if before_exists else b""
        if (
            before_exists is not hunk["before_exists"]
            or base64.b64encode(before_content).decode("ascii")
            != hunk["before_content_b64"]
            or canonical_evidence_hash.sha256_bytes(before_content)
            != hunk["before_hash"]
        ):
            raise ValueError(f"provider patch before content mismatch: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(hunk["after_content"].encode("utf-8"))
        if (
            target.read_bytes() != hunk["after_content"].encode("utf-8")
            or canonical_evidence_hash.sha256_file(target) != hunk["after_hash"]
        ):
            raise ValueError(f"provider patch application failed: {rel}")
        applied_hunks.append(
            {
                "hunk_id": hunk["hunk_id"],
                "hunk_hash": hunk["hunk_hash"],
                "decision_id": hunk["decision_id"],
                "path": rel,
                "before_hash": hunk["before_hash"],
                "after_hash": hunk["after_hash"],
                "applied_at": now(),
            }
        )
    after_snapshot = _snapshot(candidate)
    after_contents = _snapshot_map(after_snapshot)
    after_manifest = _manifest_from_contents(after_contents)
    after_manifest_hash = _manifest_hash(after_manifest)
    after_candidate_hash = _content_map_hash(after_contents)
    application_doc: dict[str, Any] = {
        "kind": "CGKNProviderPatchApplication",
        "schema_version": SCHEMA_VERSION,
        **_identity_fields(identity),
        "candidate_hash": "",
        "producer": PRODUCER,
        "created_at": now(),
        "status": "PASS",
        "artifact_hash": "",
        "candidate_root": str(candidate),
        "production_run_root": str(run_root),
        "patch_ref": str(patch_path.resolve()),
        "patch_hash": canonical_evidence_hash.sha256_file(patch_path),
        "patch_content_hash": patch_content_hash,
        "application_started_at": application_started_at,
        "application_finished_at": now(),
        "applied_hunks": applied_hunks,
        "before_source_manifest": before_manifest,
        "before_source_manifest_hash": before_manifest_hash,
        "before_candidate_hash": before_candidate_hash,
        "after_source_manifest": after_manifest,
        "after_source_manifest_hash": after_manifest_hash,
        "after_candidate_hash": after_candidate_hash,
        "patch_applied": True,
    }
    application_path = _write_hashed(
        causal_dir / APPLICATION_FILE, application_doc
    )
    return {
        "request_ref": request_path,
        "response_ref": response_path,
        "decision_ref": decision_path,
        "patch_ref": patch_path,
        "application_ref": application_path,
        "response_identity": response_identity,
        "response_content_hash": content_hash,
        "decision_content_hash": decision_content_hash,
        "patch_content_hash": patch_content_hash,
        "patch_hunk_count": len(hunks),
        "before_source_manifest_hash": before_manifest_hash,
        "before_candidate_hash": before_candidate_hash,
        "after_source_manifest_hash": after_manifest_hash,
        "after_candidate_hash": after_candidate_hash,
    }


def finalize(
    *,
    candidate_dir: str | pathlib.Path,
    production_run_dir: str | pathlib.Path,
    identity: dict[str, str],
    causal_capture: dict[str, Any],
    production_provenance_ref: str | pathlib.Path,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    run_root = pathlib.Path(production_run_dir).resolve()
    provenance_ref = pathlib.Path(production_provenance_ref).resolve()
    provenance = production_candidate_provenance.inspect(
        provenance_ref,
        expected_candidate_dir=candidate,
        expected_production_run_dir=run_root,
        expected_run_id=identity["run_id"],
        expected_candidate_id=identity["candidate_id"],
        expected_commit_sha=identity["commit_sha"],
    )
    if provenance.get("status") != "PASS":
        raise ValueError("provider causal trace requires valid production provenance")
    application_path = pathlib.Path(causal_capture["application_ref"]).resolve()
    application = _read(application_path)
    patch = _read(pathlib.Path(causal_capture["patch_ref"]).resolve())
    patch_after_contents = _snapshot_map(patch.get("before_source_snapshot", []))
    for hunk in patch.get("hunks", []):
        if not isinstance(hunk, dict):
            raise ValueError("provider patch contains an invalid hunk")
        patch_after_contents[_safe_relative_path(hunk.get("path"))] = str(
            hunk.get("after_content", "")
        ).encode("utf-8")
    if (
        _manifest_from_contents(patch_after_contents)
        != application.get("after_source_manifest")
        or _content_map_hash(patch_after_contents)
        != application.get("after_candidate_hash")
    ):
        raise ValueError("provider patch application content cannot be reconstructed")
    final_manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    final_manifest_hash = _manifest_hash(final_manifest)
    final_candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    final_contents = _snapshot_map(_snapshot(candidate))
    post_build_delta = _source_delta(patch_after_contents, final_contents)
    post_build_delta_hash = canonical_evidence_hash.canonical_json_hash(
        {"post_build_delta": post_build_delta}, ()
    )
    for hunk in patch.get("hunks", []):
        rel = _safe_relative_path(hunk.get("path"))
        final_content = final_contents.get(rel)
        before_content = base64.b64decode(
            str(hunk.get("before_content_b64", "")).encode("ascii"),
            validate=True,
        )
        if final_content is None or (
            hunk.get("before_exists") is True and final_content == before_content
        ):
            raise ValueError(
                f"post-build candidate removed or reverted provider hunk: {rel}"
            )
    if (
        application.get("after_source_manifest_hash")
        != causal_capture["after_source_manifest_hash"]
        or application.get("after_candidate_hash")
        != causal_capture["after_candidate_hash"]
        or provenance.get("candidate_hash_recomputed") != final_candidate_hash
    ):
        raise ValueError("provider patch application or production provenance changed")
    trace: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": identity["run_id"],
        "candidate_id": identity["candidate_id"],
        "candidate_hash": final_candidate_hash,
        "commit_sha": identity["commit_sha"],
        "producer": PRODUCER,
        "created_at": now(),
        "status": "PASS",
        "artifact_hash": "",
        "production_entrypoint": PRODUCTION_ENTRYPOINT,
        "generation_function": GENERATION_FUNCTION,
        "candidate_root": str(candidate),
        "production_run_root": str(run_root),
        "provider_request_ref": str(
            pathlib.Path(causal_capture["request_ref"]).resolve()
        ),
        "provider_request_hash": canonical_evidence_hash.sha256_file(
            causal_capture["request_ref"]
        ),
        "provider_response_ref": str(
            pathlib.Path(causal_capture["response_ref"]).resolve()
        ),
        "provider_response_hash": canonical_evidence_hash.sha256_file(
            causal_capture["response_ref"]
        ),
        "response_identity": causal_capture["response_identity"],
        "response_content_hash": causal_capture["response_content_hash"],
        "decision_ref": str(
            pathlib.Path(causal_capture["decision_ref"]).resolve()
        ),
        "decision_hash": canonical_evidence_hash.sha256_file(
            causal_capture["decision_ref"]
        ),
        "patch_ref": str(pathlib.Path(causal_capture["patch_ref"]).resolve()),
        "patch_hash": canonical_evidence_hash.sha256_file(
            causal_capture["patch_ref"]
        ),
        "patch_application_ref": str(application_path),
        "patch_application_hash": canonical_evidence_hash.sha256_file(
            application_path
        ),
        "patch_hunk_count": causal_capture["patch_hunk_count"],
        "before_source_manifest_hash": causal_capture[
            "before_source_manifest_hash"
        ],
        "before_candidate_hash": causal_capture["before_candidate_hash"],
        "patch_after_source_manifest_hash": causal_capture[
            "after_source_manifest_hash"
        ],
        "patch_after_candidate_hash": causal_capture["after_candidate_hash"],
        "post_build_delta": post_build_delta,
        "post_build_delta_hash": post_build_delta_hash,
        "post_build_change_count": len(post_build_delta),
        "after_source_manifest_hash": final_manifest_hash,
        "after_candidate_hash": final_candidate_hash,
        "production_provenance_ref": str(provenance_ref),
        "production_provenance_hash": provenance["provenance_hash"],
    }
    trace_path = _write_hashed(run_root / FILE_NAME, trace)
    result = dict(trace)
    result["trace_ref"] = str(trace_path)
    result["trace_hash"] = canonical_evidence_hash.sha256_file(trace_path)
    return result


def _inspect_artifact(
    path: pathlib.Path,
    *,
    expected_path: pathlib.Path,
    kind: str,
    run_root: pathlib.Path,
    identity: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if (
        path != expected_path
        or not path.is_file()
        or path.is_symlink()
        or not _is_relative_to(path, run_root)
    ):
        return {}, [f"artifact_path:{expected_path.name}"]
    document = _read(path)
    if (
        document.get("kind") != kind
        or document.get("schema_version") != SCHEMA_VERSION
        or document.get("producer") != PRODUCER
        or document.get("status") != "PASS"
    ):
        failures.append(f"artifact_contract:{expected_path.name}")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(
        document, HASH_FIELDS
    ):
        failures.append(f"artifact_self_hash:{expected_path.name}")
    for field in ("run_id", "candidate_id", "commit_sha"):
        if str(document.get(field, "")) != identity[field]:
            failures.append(f"artifact_identity:{expected_path.name}:{field}")
    return document, failures


def _contains_forbidden_request_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(token in normalized for token in FORBIDDEN_REQUEST_KEYS):
                return True
            if _contains_forbidden_request_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_request_key(item) for item in value)
    return False


def inspect(
    trace_ref: str | pathlib.Path,
    *,
    expected_candidate_dir: str | pathlib.Path | None = None,
    expected_production_run_dir: str | pathlib.Path | None = None,
    expected_run_id: str | None = None,
    expected_candidate_id: str | None = None,
    expected_candidate_hash: str | None = None,
    expected_commit_sha: str | None = None,
) -> dict[str, Any]:
    path = pathlib.Path(trace_ref).resolve()
    failures: list[str] = []
    if path.name != FILE_NAME or not path.is_file() or path.is_symlink():
        return {
            "status": "NEEDS_REWORK",
            "failures": ["provider_causal_trace_path_invalid"],
            "trace_ref": str(path),
        }
    trace = _read(path)
    if (
        trace.get("kind") != KIND
        or trace.get("schema_version") != SCHEMA_VERSION
        or trace.get("producer") != PRODUCER
        or trace.get("status") != "PASS"
        or trace.get("production_entrypoint") != PRODUCTION_ENTRYPOINT
        or trace.get("generation_function") != GENERATION_FUNCTION
    ):
        failures.append("provider_causal_trace_contract")
    if trace.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(
        trace, HASH_FIELDS
    ):
        failures.append("provider_causal_trace_self_hash")
    run_value = str(trace.get("production_run_root", "")).strip()
    candidate_value = str(trace.get("candidate_root", "")).strip()
    run_root = pathlib.Path(run_value).resolve() if run_value else pathlib.Path()
    candidate = (
        pathlib.Path(candidate_value).resolve()
        if candidate_value
        else pathlib.Path()
    )
    if (
        not run_value
        or path.parent != run_root
        or (
            expected_production_run_dir is not None
            and run_root != pathlib.Path(expected_production_run_dir).resolve()
        )
    ):
        failures.append("production_run_root_mismatch")
    if (
        not candidate_value
        or not candidate.is_dir()
        or not _is_relative_to(
            candidate, production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
        )
        or _has_reparse_point(
            candidate,
            stop=production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT,
        )
        or (
            expected_candidate_dir is not None
            and candidate != pathlib.Path(expected_candidate_dir).resolve()
        )
    ):
        failures.append("candidate_root_invalid")
    identity = {
        field: str(trace.get(field, ""))
        for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha")
    }
    for field, expected in (
        ("run_id", expected_run_id),
        ("candidate_id", expected_candidate_id),
        ("candidate_hash", expected_candidate_hash),
        ("commit_sha", expected_commit_sha),
    ):
        if expected is not None and identity[field] != str(expected):
            failures.append(f"trace_identity_mismatch:{field}")
    causal_dir = run_root / CAUSAL_DIR_NAME
    artifacts: dict[str, dict[str, Any]] = {}
    definitions = (
        (
            "request",
            "provider_request_ref",
            "provider_request_hash",
            causal_dir / REQUEST_FILE,
            "CGKNProviderRequestEvidence",
        ),
        (
            "response",
            "provider_response_ref",
            "provider_response_hash",
            causal_dir / RESPONSE_FILE,
            "CGKNProviderResponseEvidence",
        ),
        (
            "decision",
            "decision_ref",
            "decision_hash",
            causal_dir / DECISION_FILE,
            "CGKNProviderImplementationDecision",
        ),
        (
            "patch",
            "patch_ref",
            "patch_hash",
            causal_dir / PATCH_FILE,
            "CGKNProviderImplementationPatch",
        ),
        (
            "application",
            "patch_application_ref",
            "patch_application_hash",
            causal_dir / APPLICATION_FILE,
            "CGKNProviderPatchApplication",
        ),
    )
    for role, ref_field, hash_field, expected_path, kind in definitions:
        ref_value = str(trace.get(ref_field, "")).strip()
        ref = pathlib.Path(ref_value).resolve() if ref_value else pathlib.Path()
        document, artifact_failures = _inspect_artifact(
            ref,
            expected_path=expected_path,
            kind=kind,
            run_root=run_root,
            identity=identity,
        )
        failures.extend(artifact_failures)
        if (
            not ref_value
            or not ref.is_file()
            or trace.get(hash_field) != canonical_evidence_hash.sha256_file(ref)
        ):
            failures.append(f"artifact_ref_hash:{role}")
        artifacts[role] = document
    request = artifacts["request"]
    response = artifacts["response"]
    decision = artifacts["decision"]
    patch = artifacts["patch"]
    application = artifacts["application"]
    request_content = (
        request.get("request_content", {})
        if isinstance(request.get("request_content"), dict)
        else {}
    )
    if (
        not request_content
        or request.get("request_content_hash")
        != canonical_evidence_hash.canonical_json_hash(request_content, ())
        or request.get("authentication_material_recorded") is not False
        or _contains_forbidden_request_key(request_content)
    ):
        failures.append("provider_request_content_invalid")
    if (
        response.get("provider_request_ref") != trace.get("provider_request_ref")
        or response.get("provider_request_hash")
        != trace.get("provider_request_hash")
        or response.get("request_identity") != request.get("request_identity")
    ):
        failures.append("response_request_binding")
    interface_ref_value = str(
        response.get("provider_interface_result_ref", "")
    ).strip()
    interface_ref = (
        pathlib.Path(interface_ref_value).resolve()
        if interface_ref_value
        else pathlib.Path()
    )
    if (
        interface_ref != causal_dir / INTERFACE_RESULT_FILE
        or not interface_ref.is_file()
        or interface_ref.is_symlink()
        or response.get("provider_interface_result_hash")
        != canonical_evidence_hash.sha256_file(interface_ref)
    ):
        failures.append("provider_interface_result_invalid")
    response_content = (
        response.get("response_content", {})
        if isinstance(response.get("response_content"), dict)
        else {}
    )
    response_files = response_content.get("files", [])
    try:
        recomputed_response_hash = response_content_hash(response_files)
        recomputed_decisions = extract_decisions(response)
    except (TypeError, ValueError) as exc:
        recomputed_response_hash = ""
        recomputed_decisions = []
        failures.append(f"provider_response_content_invalid:{exc}")
    if (
        not response.get("response_identity")
        or response.get("response_identity") != trace.get("response_identity")
        or response.get("response_content_hash") != recomputed_response_hash
        or trace.get("response_content_hash") != recomputed_response_hash
    ):
        failures.append("provider_response_identity_or_content_hash")
    if (
        decision.get("provider_response_ref")
        != trace.get("provider_response_ref")
        or decision.get("provider_response_hash")
        != trace.get("provider_response_hash")
        or decision.get("response_identity") != response.get("response_identity")
        or decision.get("response_content_hash") != recomputed_response_hash
        or decision.get("decision_extractor")
        != "scripts.provider_causal_trace.extract_decisions"
        or decision.get("decisions") != recomputed_decisions
    ):
        failures.append("response_decision_binding")
    recomputed_decision_content_hash = canonical_evidence_hash.canonical_json_hash(
        {"decisions": recomputed_decisions}, ()
    )
    if decision.get("decision_content_hash") != recomputed_decision_content_hash:
        failures.append("decision_content_hash")
    snapshot = (
        patch.get("before_source_snapshot", [])
        if isinstance(patch.get("before_source_snapshot"), list)
        else []
    )
    try:
        before_contents = _snapshot_map(snapshot)
        before_manifest = _manifest_from_contents(before_contents)
        before_manifest_hash = _manifest_hash(before_manifest)
        before_candidate_hash = _content_map_hash(before_contents)
        recomputed_hunks = build_patch_hunks(
            response, recomputed_decisions, before_contents
        )
    except (TypeError, ValueError) as exc:
        before_contents = {}
        before_manifest = {}
        before_manifest_hash = ""
        before_candidate_hash = ""
        recomputed_hunks = []
        failures.append(f"patch_before_snapshot_invalid:{exc}")
    if (
        request_content.get("candidate_before_provider_manifest")
        != before_manifest
        or request_content.get("candidate_before_provider_manifest_hash")
        != before_manifest_hash
        or request_content.get("candidate_before_provider_hash")
        != before_candidate_hash
    ):
        failures.append("request_candidate_before_binding")
    if (
        patch.get("decision_ref") != trace.get("decision_ref")
        or patch.get("decision_hash") != trace.get("decision_hash")
        or patch.get("decision_content_hash")
        != recomputed_decision_content_hash
        or patch.get("patch_builder")
        != "scripts.provider_causal_trace.build_patch_hunks"
        or patch.get("before_source_manifest") != before_manifest
        or patch.get("before_source_manifest_hash") != before_manifest_hash
        or patch.get("before_candidate_hash") != before_candidate_hash
        or patch.get("hunks") != recomputed_hunks
        or patch.get("patch_hunk_count") != len(recomputed_hunks)
        or trace.get("patch_hunk_count") != len(recomputed_hunks)
    ):
        failures.append("decision_patch_binding")
    recomputed_patch_content_hash = canonical_evidence_hash.canonical_json_hash(
        {"hunks": recomputed_hunks}, ()
    )
    if patch.get("patch_content_hash") != recomputed_patch_content_hash:
        failures.append("patch_content_hash")
    after_contents = dict(before_contents)
    for hunk in recomputed_hunks:
        path_value = _safe_relative_path(hunk["path"])
        if (path_value in before_contents) is not hunk["before_exists"]:
            failures.append(f"patch_before_presence:{path_value}")
        if (
            base64.b64encode(before_contents.get(path_value, b"")).decode("ascii")
            != hunk["before_content_b64"]
        ):
            failures.append(f"patch_before_content:{path_value}")
        after_contents[path_value] = hunk["after_content"].encode("utf-8")
    after_manifest = _manifest_from_contents(after_contents)
    after_manifest_hash = _manifest_hash(after_manifest)
    after_candidate_hash = _content_map_hash(after_contents)
    expected_applied = [
        {
            "hunk_id": hunk["hunk_id"],
            "hunk_hash": hunk["hunk_hash"],
            "decision_id": hunk["decision_id"],
            "path": hunk["path"],
            "before_hash": hunk["before_hash"],
            "after_hash": hunk["after_hash"],
        }
        for hunk in recomputed_hunks
    ]
    actual_applied = [
        {
            key: item.get(key)
            for key in (
                "hunk_id",
                "hunk_hash",
                "decision_id",
                "path",
                "before_hash",
                "after_hash",
            )
        }
        for item in (
            application.get("applied_hunks", [])
            if isinstance(application.get("applied_hunks"), list)
            else []
        )
        if isinstance(item, dict)
    ]
    if (
        application.get("patch_ref") != trace.get("patch_ref")
        or application.get("patch_hash") != trace.get("patch_hash")
        or application.get("patch_content_hash") != recomputed_patch_content_hash
        or application.get("patch_applied") is not True
        or actual_applied != expected_applied
        or application.get("before_source_manifest") != before_manifest
        or application.get("before_source_manifest_hash") != before_manifest_hash
        or application.get("before_candidate_hash") != before_candidate_hash
        or application.get("after_source_manifest") != after_manifest
        or application.get("after_source_manifest_hash") != after_manifest_hash
        or application.get("after_candidate_hash") != after_candidate_hash
    ):
        failures.append("patch_application_binding")
    application_hunks = (
        application.get("applied_hunks", [])
        if isinstance(application.get("applied_hunks"), list)
        else []
    )
    for item in application_hunks:
        applied_at = _parse_time(item.get("applied_at")) if isinstance(item, dict) else None
        if applied_at is None:
            failures.append("patch_application_timestamp")
    current_manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    current_manifest_hash = _manifest_hash(current_manifest)
    current_candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    current_snapshot_contents = (
        _snapshot_map(_snapshot(candidate)) if candidate.is_dir() else {}
    )
    recomputed_post_build_delta = _source_delta(
        after_contents, current_snapshot_contents
    )
    recomputed_post_build_delta_hash = canonical_evidence_hash.canonical_json_hash(
        {"post_build_delta": recomputed_post_build_delta}, ()
    )
    for hunk in recomputed_hunks:
        rel = hunk["path"]
        final_content = current_snapshot_contents.get(rel)
        before_content = base64.b64decode(
            hunk["before_content_b64"].encode("ascii"), validate=True
        )
        if final_content is None or (
            hunk.get("before_exists") is True and final_content == before_content
        ):
            failures.append(f"provider_hunk_removed_or_reverted:{rel}")
    if (
        trace.get("before_source_manifest_hash") != before_manifest_hash
        or trace.get("before_candidate_hash") != before_candidate_hash
        or trace.get("patch_after_source_manifest_hash") != after_manifest_hash
        or trace.get("patch_after_candidate_hash") != after_candidate_hash
        or trace.get("post_build_delta") != recomputed_post_build_delta
        or trace.get("post_build_delta_hash") != recomputed_post_build_delta_hash
        or trace.get("post_build_change_count")
        != len(recomputed_post_build_delta)
        or trace.get("after_source_manifest_hash") != current_manifest_hash
        or trace.get("after_candidate_hash") != current_candidate_hash
        or identity["candidate_hash"] != current_candidate_hash
    ):
        failures.append("patch_candidate_binding")
    provenance_value = str(trace.get("production_provenance_ref", "")).strip()
    provenance_ref = (
        pathlib.Path(provenance_value).resolve()
        if provenance_value
        else pathlib.Path()
    )
    provenance = production_candidate_provenance.inspect(
        provenance_ref,
        expected_candidate_dir=candidate,
        expected_production_run_dir=run_root,
        expected_run_id=identity["run_id"],
        expected_candidate_id=identity["candidate_id"],
        expected_candidate_hash=identity["candidate_hash"],
        expected_commit_sha=identity["commit_sha"],
    )
    if (
        not provenance_value
        or provenance.get("status") != "PASS"
        or trace.get("production_provenance_hash")
        != provenance.get("provenance_hash")
    ):
        failures.append("production_provenance_binding")
    provenance_document = (
        provenance.get("document", {})
        if isinstance(provenance.get("document"), dict)
        else {}
    )
    provider_entries = [
        item
        for item in provenance_document.get("artifact_refs", [])
        if isinstance(item, dict)
        and item.get("role") == "provider_generation_result"
    ]
    provider_result: dict[str, Any] = {}
    if len(provider_entries) != 1:
        failures.append("provenance_provider_result_binding")
    else:
        provider_result_ref = pathlib.Path(
            str(provider_entries[0].get("ref", ""))
        ).resolve()
        if (
            not provider_result_ref.is_file()
            or provider_result_ref.is_symlink()
            or provider_entries[0].get("hash")
            != canonical_evidence_hash.sha256_file(provider_result_ref)
        ):
            failures.append("provenance_provider_result_binding")
        else:
            provider_result = _read(provider_result_ref)
    try:
        response_paths = [
            _safe_relative_path(item.get("path"))
            for item in response_files
            if isinstance(item, dict)
        ]
        provider_generated = (
            [
                _safe_relative_path(item)
                for item in provider_result.get("generated_files", [])
            ]
            if isinstance(provider_result.get("generated_files"), list)
            else []
        )
    except (TypeError, ValueError) as exc:
        response_paths = []
        provider_generated = []
        failures.append(f"provider_result_paths_invalid:{exc}")
    causal_refs = (
        provider_result.get("provider_causal_artifacts", {})
        if isinstance(provider_result.get("provider_causal_artifacts"), dict)
        else {}
    )
    if (
        sorted(provider_generated) != sorted(response_paths)
        or any(
            str(pathlib.Path(str(causal_refs.get(key, ""))).resolve())
            != str(pathlib.Path(str(trace.get(trace_field, ""))).resolve())
            for key, trace_field in (
                ("request_ref", "provider_request_ref"),
                ("response_ref", "provider_response_ref"),
                ("decision_ref", "decision_ref"),
                ("patch_ref", "patch_ref"),
                ("application_ref", "patch_application_ref"),
            )
        )
    ):
        failures.append("provider_result_causal_binding")
    receipt_entries = {
        str(item.get("stage", "")): pathlib.Path(str(item.get("ref", ""))).resolve()
        for item in provenance_document.get("stage_receipts", [])
        if isinstance(item, dict)
    }
    required_causal_refs = {
        "provider_request": (
            pathlib.Path(str(trace.get("provider_request_ref", ""))).resolve(),
            str(trace.get("provider_request_hash", "")),
        ),
        "provider_response": (
            pathlib.Path(str(trace.get("provider_response_ref", ""))).resolve(),
            str(trace.get("provider_response_hash", "")),
        ),
        "implementation_decision": (
            pathlib.Path(str(trace.get("decision_ref", ""))).resolve(),
            str(trace.get("decision_hash", "")),
        ),
        "implementation_patch": (
            pathlib.Path(str(trace.get("patch_ref", ""))).resolve(),
            str(trace.get("patch_hash", "")),
        ),
        "patch_application": (
            pathlib.Path(str(trace.get("patch_application_ref", ""))).resolve(),
            str(trace.get("patch_application_hash", "")),
        ),
    }
    receipts: dict[str, dict[str, Any]] = {}
    for stage in ("provider_generation", "provider_validation", "post_build"):
        receipt_path = receipt_entries.get(stage, pathlib.Path())
        receipt = _read(receipt_path) if receipt_path.is_file() else {}
        receipts[stage] = receipt
        if not receipt:
            failures.append(f"causal_stage_receipt_missing:{stage}")
    for stage in ("provider_generation", "provider_validation"):
        artifact_refs = (
            receipts.get(stage, {}).get("artifact_refs", [])
            if isinstance(receipts.get(stage, {}).get("artifact_refs"), list)
            else []
        )
        for role, (expected_ref, expected_hash) in required_causal_refs.items():
            if not any(
                isinstance(item, dict)
                and item.get("role") == role
                and pathlib.Path(str(item.get("ref", ""))).resolve()
                == expected_ref
                and item.get("hash") == expected_hash
                for item in artifact_refs
            ):
                failures.append(f"causal_stage_artifact_binding:{stage}:{role}")
    timeline = [
        _parse_time(request.get("created_at")),
        _parse_time(response.get("created_at")),
        _parse_time(decision.get("created_at")),
        _parse_time(patch.get("created_at")),
        _parse_time(application.get("application_started_at")),
        _parse_time(application.get("application_finished_at")),
        _parse_time(
            provenance.get("document", {}).get("created_at")
            if isinstance(provenance.get("document"), dict)
            else None
        ),
        _parse_time(trace.get("created_at")),
    ]
    if any(item is None for item in timeline) or any(
        timeline[index] > timeline[index + 1]  # type: ignore[operator]
        for index in range(len(timeline) - 1)
        if timeline[index] is not None and timeline[index + 1] is not None
    ):
        failures.append("provider_causal_timeline")
    generation_started = _parse_time(
        receipts.get("provider_generation", {}).get("started_at")
    )
    generation_finished = _parse_time(
        receipts.get("provider_generation", {}).get("finished_at")
    )
    validation_started = _parse_time(
        receipts.get("provider_validation", {}).get("started_at")
    )
    validation_finished = _parse_time(
        receipts.get("provider_validation", {}).get("finished_at")
    )
    post_build_started = _parse_time(
        receipts.get("post_build", {}).get("started_at")
    )
    if (
        generation_started is None
        or generation_finished is None
        or validation_started is None
        or validation_finished is None
        or post_build_started is None
        or timeline[0] is None
        or timeline[5] is None
        or not (
            generation_started
            <= timeline[0]
            <= timeline[5]
            <= generation_finished
            <= validation_started
            <= validation_finished
            <= post_build_started
        )
    ):
        failures.append("provider_stage_causal_timeline")
    return {
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "failures": sorted(set(failures)),
        "trace_ref": str(path),
        "trace_hash": canonical_evidence_hash.sha256_file(path),
        "identity": identity,
        "candidate_root": str(candidate),
        "production_run_root": str(run_root),
        "response_identity": str(response.get("response_identity", "")),
        "response_content_hash_recomputed": recomputed_response_hash,
        "decision_content_hash_recomputed": recomputed_decision_content_hash,
        "patch_content_hash_recomputed": recomputed_patch_content_hash,
        "patch_hunk_count": len(recomputed_hunks),
        "before_source_manifest_hash_recomputed": before_manifest_hash,
        "before_candidate_hash_recomputed": before_candidate_hash,
        "patch_after_source_manifest_hash_recomputed": after_manifest_hash,
        "patch_after_candidate_hash_recomputed": after_candidate_hash,
        "post_build_delta_hash_recomputed": recomputed_post_build_delta_hash,
        "post_build_change_count": len(recomputed_post_build_delta),
        "after_source_manifest_hash_recomputed": current_manifest_hash,
        "after_candidate_hash_recomputed": current_candidate_hash,
        "provenance_inspection": provenance,
        "document": trace,
    }
