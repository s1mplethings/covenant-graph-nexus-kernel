from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

try:
    import local_media_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_media_adapter


ENV_COMMAND = "CGKN_LOCAL_TRANSCRIBE_CMD"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transcript_schema(
    *,
    status: str,
    adapter: str,
    input_path: pathlib.Path,
    output_path: pathlib.Path,
    text: str,
    degraded: bool,
    evidence: list[Any],
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "transcription",
        "status": status,
        "adapter": adapter,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "created_at": now(),
        "segments": segments or [],
        "text": text,
        "degraded": degraded,
        "evidence": evidence,
    }


def placeholder_transcript(input_path: pathlib.Path, output_path: pathlib.Path) -> dict[str, Any]:
    artifact = transcript_schema(
        status="placeholder",
        adapter="deterministic_placeholder",
        input_path=input_path,
        output_path=output_path,
        text="Placeholder transcript generated from fixture metadata. This is not model output.",
        degraded=True,
        evidence=["placeholder_transcription", "no local model command configured or used"],
        segments=[
            {
                "id": "placeholder_001",
                "start": 0,
                "end": 0,
                "text": "Placeholder transcript generated from fixture metadata.",
                "degraded": True,
            }
        ],
    )
    write_json(output_path, artifact)
    return artifact


def run_bounded(command: str | list[str], *, timeout: float) -> dict[str, Any]:
    started = time.time()
    use_shell = isinstance(command, str)
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=use_shell)
        return {
            "command": command,
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:4000],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": str(exc.stdout or "")[:4000],
            "stderr": str(exc.stderr or "")[:4000],
            "timed_out": True,
        }
    except Exception as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }


def validate_transcript(path: pathlib.Path) -> tuple[bool, list[str], dict[str, Any]]:
    blockers: list[str] = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"invalid_json:{exc}"], {}
    if not isinstance(doc, dict):
        return False, ["transcript_not_object"], {}
    if doc.get("stage") != "transcription":
        blockers.append("stage_mismatch")
    if doc.get("status") not in {"verified", "placeholder", "unavailable", "failed"}:
        blockers.append("status_invalid")
    if not isinstance(doc.get("segments"), list):
        blockers.append("segments_missing")
    if not isinstance(doc.get("text", ""), str):
        blockers.append("text_invalid")
    return not blockers, blockers, doc


def _command_from_env(env: dict[str, str] | None) -> str:
    source = env if env is not None else os.environ
    return str(source.get(ENV_COMMAND, "")).strip()


def evaluate(
    *,
    project_dir: pathlib.Path,
    input_path: pathlib.Path,
    output_path: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 2.0,
    placeholder: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    output = output_path or project / "transcription_adapter_result.json"
    command_template = _command_from_env(env)

    if not command_template:
        if placeholder:
            artifact = placeholder_transcript(input_path, output)
            record = local_media_adapter.file_record(output)
            return {
                "status": "placeholder_transcription",
                "tool": "none",
                "model": None,
                "adapter": "deterministic_placeholder",
                "command": None,
                "returncode": None,
                "input_artifact": str(input_path),
                "output_artifact": str(output),
                "artifact": record,
                "evidence": artifact.get("evidence", []),
                "commercial_ready": False,
                "reason": "Only deterministic placeholder transcription is available; no local model is configured.",
                "model_status": "local_model_unavailable",
            }
        return {
            "status": "local_model_unavailable",
            "tool": "none",
            "model": None,
            "adapter": "",
            "command": None,
            "returncode": None,
            "input_artifact": str(input_path),
            "output_artifact": "",
            "artifact": {},
            "evidence": [f"{ENV_COMMAND} is not configured"],
            "commercial_ready": False,
            "reason": "No local transcription model adapter command is configured.",
            "model_status": "local_model_unavailable",
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        parts = shlex.split(command_template, posix=False)
        command: str | list[str] = command_template.format(input=str(input_path), output=str(output), project=str(project))
        adapter_name = parts[0].strip('"') if parts else "configured_command"
    else:
        parts = shlex.split(command_template)
        command = [part.format(input=str(input_path), output=str(output), project=str(project)) for part in parts]
        adapter_name = parts[0] if parts else "configured_command"
    run = run_bounded(command, timeout=timeout)
    if run.get("returncode") != 0 or run.get("timed_out"):
        return {
            "status": "failed",
            "tool": "configured_command",
            "model": "configured_command",
            "adapter": adapter_name,
            "command": command,
            "returncode": run.get("returncode"),
            "input_artifact": str(input_path),
            "output_artifact": str(output),
            "artifact": local_media_adapter.file_record(output) if output.exists() else {},
            "evidence": [run],
            "commercial_ready": False,
            "reason": "Configured local transcription adapter did not complete successfully.",
            "model_status": "local_model_configured",
        }

    valid, blockers, doc = validate_transcript(output)
    if not valid or doc.get("status") != "verified":
        return {
            "status": "failed",
            "tool": "configured_command",
            "model": "configured_command",
            "adapter": str(doc.get("adapter") or adapter_name),
            "command": command,
            "returncode": run.get("returncode"),
            "input_artifact": str(input_path),
            "output_artifact": str(output),
            "artifact": local_media_adapter.file_record(output) if output.exists() else {},
            "evidence": [run, {"schema_blockers": blockers}],
            "commercial_ready": False,
            "reason": "Configured local transcription adapter output was not valid verified transcript evidence.",
            "model_status": "local_model_configured",
        }

    return {
        "status": "local_model_verified",
        "tool": "configured_command",
        "model": str(doc.get("adapter") or "configured_command"),
        "adapter": str(doc.get("adapter") or adapter_name),
        "command": command,
        "returncode": run.get("returncode"),
        "input_artifact": str(input_path),
        "output_artifact": str(output),
        "artifact": local_media_adapter.file_record(output),
        "evidence": [run, {"transcript_status": doc.get("status"), "segments": len(doc.get("segments", []))}],
        "commercial_ready": False,
        "reason": "Configured local model adapter produced valid bounded transcript evidence, but this alone is not production readiness.",
        "model_status": "local_model_verified",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--placeholder", action="store_true")
    args = parser.parse_args()
    result = evaluate(
        project_dir=pathlib.Path(args.project_dir),
        input_path=pathlib.Path(args.input),
        output_path=pathlib.Path(args.output) if args.output else None,
        timeout=args.timeout,
        placeholder=args.placeholder,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"local_model_unavailable", "placeholder_transcription", "local_model_verified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
