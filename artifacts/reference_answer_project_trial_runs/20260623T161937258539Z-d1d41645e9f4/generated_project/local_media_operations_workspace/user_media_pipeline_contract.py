from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    import local_media_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_media_adapter


SUPPORTED_MEDIA_SUFFIXES = {".wav", ".mp3", ".mp4", ".m4a", ".mov"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _within(child: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_user_media_input(input_path: pathlib.Path, *, project_dir: pathlib.Path) -> dict[str, Any]:
    raw = pathlib.Path(input_path)
    project = pathlib.Path(project_dir).resolve()
    if raw.is_absolute():
        resolved = raw.resolve()
        policy = "safe_absolute_path_recorded"
    else:
        resolved = (project / raw).resolve()
        policy = "relative_path_within_project"
        if not _within(resolved, project):
            return {
                "status": "FAIL",
                "policy": policy,
                "original_input_path": str(input_path),
                "safe_input_path": str(resolved),
                "blockers": ["input_path_escapes_project"],
            }
    blockers: list[str] = []
    if not resolved.exists():
        blockers.append("input_file_missing")
    elif not resolved.is_file():
        blockers.append("input_is_not_file")
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_MEDIA_SUFFIXES:
        blockers.append("unsupported_media_type")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "policy": policy,
        "original_input_path": str(input_path),
        "safe_input_path": str(resolved),
        "file_type": suffix.lstrip(".") or "unknown",
        "blockers": blockers,
    }


def inspect_user_media(path: pathlib.Path, *, timeout: float = 2.0) -> dict[str, Any]:
    suffix = path.suffix.lower()
    evidence: list[Any] = []
    metadata: dict[str, Any] = {}
    metadata_status = "local_tool_unavailable"
    adapter_status = "local_tool_unavailable"
    if suffix == ".wav":
        try:
            metadata = local_media_adapter.read_wave_metadata(path)
            metadata_status = "python_wave_verified"
            adapter_status = "python_wave_verified"
            evidence.append({"python_wave": metadata})
        except Exception as exc:
            return {
                "status": "FAIL",
                "metadata_status": "invalid_media",
                "adapter_status": "python_wave_failed",
                "metadata": {},
                "evidence": [str(exc)],
            }
    ffprobe = local_media_adapter.inspect_with_ffprobe(path, timeout=timeout)
    if ffprobe.get("status") == "local_tool_verified":
        metadata_status = "ffprobe_verified"
        adapter_status = "ffprobe_verified"
    evidence.append({"ffprobe": ffprobe})
    return {
        "status": "PASS" if metadata_status in {"python_wave_verified", "ffprobe_verified"} else "NEEDS_REWORK",
        "metadata_status": metadata_status,
        "adapter_status": adapter_status,
        "metadata": metadata,
        "evidence": evidence,
    }


def user_media_fixture_doc(media_manifest: dict[str, Any]) -> dict[str, Any]:
    item = {
        "path": str(media_manifest["safe_input_path"]),
        "kind": "audio" if media_manifest.get("file_type") in {"wav", "mp3", "m4a"} else "video",
        "label": pathlib.Path(str(media_manifest["safe_input_path"])).name,
        "duration_seconds": media_manifest.get("metadata", {}).get("duration_seconds", 0),
        "size": media_manifest["size"],
        "sha256": media_manifest["sha256"],
        "real_user_media_input": True,
    }
    return {
        "kind": "CGKNLocalMediaFixture",
        "source": "user_media_pipeline_contract_v1",
        "user_media_contract": True,
        "original_input_path": media_manifest["original_input_path"],
        "safe_input_path": media_manifest["safe_input_path"],
        "file_type": media_manifest["file_type"],
        "size": media_manifest["size"],
        "sha256": media_manifest["sha256"],
        "metadata_status": media_manifest["metadata_status"],
        "adapter_status": media_manifest["adapter_status"],
        "files": [item],
        "candidate_keywords": ["user", "media", "local", "review"],
        "segments": [
            {
                "id": "user_media_seg_001",
                "start": 0,
                "end": media_manifest.get("metadata", {}).get("duration_seconds", 0),
                "text": f"User media input verified from {item['label']}",
            }
        ],
        "not_real_ai_model": True,
    }


def prepare_user_media_pipeline(
    *,
    project_dir: pathlib.Path,
    input_path: pathlib.Path,
    output_dir: pathlib.Path | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    output = pathlib.Path(output_dir or project)
    output.mkdir(parents=True, exist_ok=True)
    resolved = resolve_user_media_input(input_path, project_dir=project)
    inspect: dict[str, Any] = {
        "status": "FAIL",
        "metadata_status": "unavailable",
        "adapter_status": "local_tool_unavailable",
        "metadata": {},
        "evidence": [],
    }
    if resolved["status"] == "PASS":
        inspect = inspect_user_media(pathlib.Path(resolved["safe_input_path"]), timeout=timeout)

    safe_path = pathlib.Path(str(resolved.get("safe_input_path", "")))
    file_info = local_media_adapter.file_record(safe_path) if safe_path.exists() and safe_path.is_file() else {"path": str(safe_path), "sha256": "", "size": 0}
    status = "PASS" if resolved["status"] == "PASS" and inspect["status"] == "PASS" else "FAIL"
    blockers = list(resolved.get("blockers", []))
    if inspect["status"] != "PASS":
        blockers.append(f"metadata_status:{inspect.get('metadata_status')}")
    media_manifest = {
        "stage": "media_manifest",
        "status": status,
        "input_path": str(input_path),
        "output_path": str(output / "media_manifest.json"),
        "created_at": now(),
        "upstream_artifacts": [],
        "items": [
            {
                "id": safe_path.stem if safe_path.name else "user_media_input",
                "path": str(safe_path),
                "file_type": resolved.get("file_type", "unknown"),
                "size": file_info["size"],
                "sha256": file_info["sha256"],
            }
        ],
        "evidence": inspect.get("evidence", []),
        "original_input_path": str(input_path),
        "safe_input_path": str(safe_path),
        "file_type": resolved.get("file_type", "unknown"),
        "size": file_info["size"],
        "sha256": file_info["sha256"],
        "metadata_status": inspect.get("metadata_status"),
        "adapter_status": inspect.get("adapter_status"),
        "metadata": inspect.get("metadata", {}),
        "safe_input_policy": resolved.get("policy"),
        "blockers": blockers,
        "real_user_media_input": True,
        "not_production_asr": True,
        "commercial_ready": False,
    }
    inspect_artifact = {
        "stage": "inspect_media",
        "status": status,
        "input_path": str(input_path),
        "output_path": str(output / "user_media_inspect.json"),
        "created_at": now(),
        "upstream_artifacts": [str(output / "media_manifest.json")],
        "items": media_manifest["items"],
        "evidence": inspect.get("evidence", []),
        "metadata_status": inspect.get("metadata_status"),
        "adapter_status": inspect.get("adapter_status"),
        "blockers": blockers,
    }
    write_json(output / "media_manifest.json", media_manifest)
    write_json(output / "user_media_inspect.json", inspect_artifact)
    fixture_path = output / "user_media_fixture.json"
    if status == "PASS":
        write_json(fixture_path, user_media_fixture_doc(media_manifest))
    smoke = {
        "stage": "user_media_smoke",
        "status": status,
        "input_path": str(input_path),
        "output_path": str(output / "user_media_smoke_log.json"),
        "created_at": now(),
        "upstream_artifacts": [str(output / "media_manifest.json"), str(output / "user_media_inspect.json")],
        "items": media_manifest["items"],
        "evidence": [{"blockers": blockers}, {"metadata_status": media_manifest["metadata_status"]}],
        "fixture_path": str(fixture_path) if fixture_path.exists() else "",
    }
    write_json(output / "user_media_smoke_log.json", smoke)
    return {
        "status": status,
        "media_manifest": str(output / "media_manifest.json"),
        "inspect_artifact": str(output / "user_media_inspect.json"),
        "smoke_log": str(output / "user_media_smoke_log.json"),
        "fixture_path": str(fixture_path) if fixture_path.exists() else "",
        "metadata_status": media_manifest["metadata_status"],
        "adapter_status": media_manifest["adapter_status"],
        "sha256": media_manifest["sha256"],
        "size": media_manifest["size"],
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    project = pathlib.Path(args.project_dir)
    result = prepare_user_media_pipeline(
        project_dir=project,
        input_path=pathlib.Path(args.input),
        output_dir=pathlib.Path(args.output_dir) if args.output_dir else project,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
