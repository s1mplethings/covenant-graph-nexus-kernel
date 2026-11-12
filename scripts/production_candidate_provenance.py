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


_RELEASE_CONTEXT: dict[str, str] = {}


def configure_release_trust(release_trust_anchor=None, release_authorization=None) -> None:
    """Controller-only injection point for the protected Ed25519 trust anchor.

    The anchor path must be outside the agent-writable run store and workspace;
    the verifier enforces that.  This is a controller-only entry point: if
    agent-controlled code can call it, it can point at an anchor it controls,
    so the anchor path must come from a protected controller configuration.
    A signature cannot be forged, but a writable anchor is not a trust root.
    """
    _RELEASE_CONTEXT.clear()
    if release_trust_anchor is not None:
        _RELEASE_CONTEXT["release_trust_anchor"] = str(
            pathlib.Path(release_trust_anchor).resolve())
    if release_authorization is not None:
        _RELEASE_CONTEXT["release_authorization"] = str(
            pathlib.Path(release_authorization).resolve())


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
    release_trust_anchor: str | pathlib.Path | None = None,
    release_authorization: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    release_trust_anchor = release_trust_anchor or _RELEASE_CONTEXT.get("release_trust_anchor")
    release_authorization = release_authorization or _RELEASE_CONTEXT.get("release_authorization")
    path = pathlib.Path(provenance_ref).resolve()
    failures: list[str] = []
    if path.name != FILE_NAME or not path.is_file() or path.is_symlink():
        return {
            "status": "NEEDS_REWORK",
            "failures": ["production_provenance_path_invalid"],
            "provenance_ref": str(path),
        }
    document = _read(path)
    if document.get('schema_version')=='2.0' and document.get('generation_route')=='project_session':
        return _inspect_project_session(path,document,
            expected_candidate_dir=expected_candidate_dir,expected_production_run_dir=expected_production_run_dir,
            expected_run_id=expected_run_id,expected_candidate_id=expected_candidate_id,
            expected_candidate_hash=expected_candidate_hash,expected_commit_sha=expected_commit_sha,
            release_trust_anchor=release_trust_anchor,release_authorization=release_authorization)
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


def _project_session_projection(store, project_id, run_id, candidate, *,
                                release_trust_anchor=None, release_authorization=None):
    """Rebuild existing core facts; no legacy stage attribution is synthesized."""
    from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
    from cgkn.state.provenance import ProvenanceGate,reference
    root=store.run_dir(project_id,run_id)
    names=('project_profile.json','goal_acceptance.json','capability_tree.json',
           'execution_dag.json','provenance_contract.json')
    refs={name:reference(store.root,root/name) for name in names}
    profile=_read(root/'project_profile.json')
    if (profile.get('kind')!='CGKNProjectSessionProfile' or profile.get('project_id')!=project_id
            or profile.get('run_id')!=run_id or pathlib.Path(profile['workspace']).resolve()!=candidate):
        raise ValueError('project-session profile/candidate binding mismatch')
    data=_read(root/'goal_acceptance.json')
    acceptance=GoalAcceptance(store,project_id,run_id,profile['requirements'],data['checker_bindings'])
    manifest=canonical_evidence_hash.candidate_source_manifest(candidate)
    sources=ProvenanceGate(store,project_id,run_id,
        release_trust_anchor=release_trust_anchor,
        release_authorization=release_authorization).delivery_sources(acceptance,candidate,manifest)
    audit=[];failures=[];agent_bound=False
    for request_path in sorted((root/'provider_calls').glob('*/request.json')):
        request=_read(request_path);response_path=request_path.with_name('response.json');error_path=request_path.with_name('error.json')
        row={'request_ref':reference(store.root,request_path),'role':request['config']['role']}
        if response_path.is_file():
            response=_read(response_path);route=response.get('routing',{});config=request['config']
            real=bool(request.get('transport_kind')=='recorded_gateway' and config.get('model_id')
                and route.get('identity_status')=='MATCH' and route.get('provider_id')==config['model']
                and route.get('actual_model')==response.get('model')==config['model_id']
                and route.get('requested_model')==route.get('bound_model')==config['model_id']
                and request['identity']==response.get('identity'))
            row.update(response_ref=reference(store.root,response_path),actual_model=response.get('model'),
                request_id=response.get('request_id'),usage=response.get('usage',{}),attempts=response.get('attempts'),
                real_provider_identity_bound=real,status='RESPONSE_RECORDED')
            agent_bound=agent_bound or (row['role']=='agent' and real)
            if not real: failures.append('provider_identity_not_qualified')
        elif error_path.is_file():
            error=_read(error_path)
            row.update(error_ref=reference(store.root,error_path),status='ERROR_RECORDED',
                       outcome_unknown=error.get('outcome_unknown') is not False)
            if row['outcome_unknown']: failures.append('provider_outcome_unknown')
        else:
            row.update(status='OUTCOME_UNKNOWN',outcome_unknown=True)
            failures.append('provider_outcome_unknown')
        audit.append(row)
    if not sources['real_provider_backed'] or not agent_bound:
        failures.append('real_provider_planner_and_worker_required')
    return {'core_refs':refs,'core_sources':sources,'provider_call_audit':audit,
        'candidate_source_manifest':manifest,'failures':sorted(set(failures))}


def produce_project_session(store, project_id, run_id, *, candidate_dir, commit_sha,
                            release_trust_anchor=None, release_authorization=None):
    """Versioned input to the same production provenance/delivery authority."""
    root=store.run_dir(project_id,run_id);candidate=pathlib.Path(candidate_dir).resolve()
    if not commit_sha or _candidate_symlinks(candidate):
        raise ValueError('source commit and regular candidate files required')
    projection=_project_session_projection(store,project_id,run_id,candidate,
        release_trust_anchor=release_trust_anchor,
        release_authorization=release_authorization)
    path=root/FILE_NAME;previous=_read(path) if path.exists() else {}
    if previous and previous.get('generation_route')!='project_session':
        raise ValueError('historical provenance cannot be reinterpreted; use a new run')
    manifest=projection['candidate_source_manifest']
    candidate_hash=canonical_evidence_hash.candidate_source_hash(candidate)
    unchanged=previous and all(previous.get(k)==v for k,v in projection.items())
    document={'kind':KIND,'schema_version':'2.0','generation_route':'project_session',
        'producer':'scripts.production_candidate_provenance.produce_project_session',
        'production_entrypoint':'cgkn.application.software_project.service.SoftwareProjectGenerationService.run_profile',
        'generation_function':'cgkn.agent.project_loop.ProjectSession.run',
        'created_at':previous['created_at'] if unchanged else _now(),
        'run_id':run_id,'project_id':project_id,'candidate_id':'core-'+hashlib.sha256((project_id+'/'+run_id+'/'+candidate_hash).encode()).hexdigest()[:24],
        'candidate_hash':candidate_hash,'commit_sha':commit_sha,'candidate_root':str(candidate),
        'production_run_root':str(root),'core_store_root':str(store.root),
        'candidate_source_manifest_hash':_manifest_hash(manifest),
        'candidate_hash_method':'scripts.canonical_evidence_hash.candidate_source_hash',
        'status':'PASS' if not projection['failures'] else 'NEEDS_REWORK',
        **projection,'artifact_hash':''}
    if path.exists():
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        store.immutable_blob(root/'provenance_history'/(digest+'.json'),path.read_bytes())
    _write_hashed(path,document)
    return {**document,'provenance_ref':str(path),'provenance_hash':canonical_evidence_hash.sha256_file(path)}


def _inspect_project_session(path,document,**expected):
    failures=[];projection={}
    try:
        from cgkn.state import FileRunStore
        store_root=pathlib.Path(document['core_store_root']).resolve()
        if not store_root.is_dir(): raise ValueError('core store is missing')
        FileRunStore._validate_segment(document['project_id']);FileRunStore._validate_segment(document['run_id'])
        existing_root=(store_root/document['project_id']/document['run_id']).resolve()
        if not existing_root.is_dir() or not existing_root.is_relative_to(store_root):
            raise ValueError('core run is missing')
        store=FileRunStore(store_root)
        root=store.run_dir(document['project_id'],document['run_id'])
        candidate=pathlib.Path(document['candidate_root']).resolve()
        if (path!=root/FILE_NAME or str(root)!=document['production_run_root']
                or document.get('kind')!=KIND or document.get('status')!='PASS'
                or document.get('producer')!='scripts.production_candidate_provenance.produce_project_session'
                or document.get('production_entrypoint')!='cgkn.application.software_project.service.SoftwareProjectGenerationService.run_profile'
                or document.get('generation_function')!='cgkn.agent.project_loop.ProjectSession.run'
                or document.get('candidate_hash_method')!='scripts.canonical_evidence_hash.candidate_source_hash'
                or not document.get('commit_sha')
                or document.get('candidate_id')!='core-'+hashlib.sha256((document['project_id']+'/'+document['run_id']+'/'+document['candidate_hash']).encode()).hexdigest()[:24]
                or _candidate_symlinks(candidate)):
            raise ValueError('invalid core production provenance contract')
        if document['artifact_hash']!=canonical_evidence_hash.canonical_json_hash(document,('artifact_hash',)):
            raise ValueError('core production provenance hash mismatch')
        for key,field in [('expected_candidate_dir','candidate_root'),('expected_production_run_dir','production_run_root'),
                          ('expected_run_id','run_id'),('expected_candidate_id','candidate_id'),
                          ('expected_candidate_hash','candidate_hash'),('expected_commit_sha','commit_sha')]:
            if expected.get(key) is not None and str(expected[key])!=document[field]:
                raise ValueError('core production identity mismatch: '+field)
        projection=_project_session_projection(store,document['project_id'],document['run_id'],candidate,
            release_trust_anchor=expected.get('release_trust_anchor'),
            release_authorization=expected.get('release_authorization'))
        if any(document.get(k)!=v for k,v in projection.items()):
            raise ValueError('core production evidence changed')
        failures.extend(projection['failures'])
        if (canonical_evidence_hash.candidate_source_hash(candidate)!=document['candidate_hash']
                or _manifest_hash(projection['candidate_source_manifest'])!=document['candidate_source_manifest_hash']):
            raise ValueError('core candidate source identity changed')
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        failures.append('project_session_provenance:'+str(exc))
    return {'status':'PASS' if not failures else 'NEEDS_REWORK','failures':sorted(set(failures)),
        'provenance_ref':str(path),'provenance_hash':canonical_evidence_hash.sha256_file(path),
        'identity':{k:document.get(k,'') for k in ('run_id','candidate_id','candidate_hash','commit_sha')},
        'candidate_root':document.get('candidate_root'),'production_run_root':document.get('production_run_root'),
        'candidate_source_manifest':projection.get('candidate_source_manifest',{}),
        'candidate_source_manifest_hash':_manifest_hash(projection.get('candidate_source_manifest',{})),
        'candidate_hash_recomputed':canonical_evidence_hash.candidate_source_hash(candidate) if projection else '',
        'document':document}
