from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import time
import wave
from datetime import datetime, timezone
from typing import Any

try:
    import asr_evidence_tier
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import asr_evidence_tier


ENV_COMMAND = "CGKN_REAL_ASR_CMD"
ASR_STATUSES = {
    "no_asr_configured",
    "placeholder_transcription",
    "command_fixture_transcription",
    "asr_contract_fixture_verified",
    "real_local_asr_verified",
    "production_asr_candidate",
    "production_asr_verified",
    "real_asr_failed",
    "real_asr_timeout",
    "real_asr_invalid_output",
    "asr_quality_insufficient",
}
REQUIRED_TRANSCRIPT_FIELDS = [
    "stage",
    "status",
    "adapter_kind",
    "engine",
    "model_name",
    "model_path",
    "input_path",
    "output_path",
    "created_at",
    "language",
    "duration_seconds",
    "segments",
    "text",
    "production_asr",
    "degraded",
    "evidence",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: pathlib.Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}


def read_wave_duration(path: pathlib.Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
        return round(frames / rate, 6) if rate else 0.0
    except Exception:
        return 0.0


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_section(*, status: str, reason: str, fallback_transcription: dict[str, Any] | None = None) -> dict[str, Any]:
    adapter_kind = "fixture" if status == "command_fixture_transcription" else "none"
    return {
        "status": status,
        "adapter_kind": adapter_kind,
        "engine": None,
        "model_name": None,
        "model_path": None,
        "command": None,
        "returncode": None,
        "timed_out": False,
        "input_path": None,
        "output_path": None,
        "sha256": None,
        "size": None,
        "input_sha256": None,
        "input_size": None,
        "production_asr": False,
        "evidence_tier": asr_evidence_tier.tier_for_status(status),
        "quality_report_path": "",
        "degraded": True,
        "schema_valid": False,
        "schema_blockers": [],
        "commercial_ready": False,
        "reason": reason,
        "evidence": [fallback_transcription] if fallback_transcription else [],
    }


def fallback_section(transcription: dict[str, Any] | None) -> dict[str, Any]:
    if not transcription:
        return default_section(status="no_asr_configured", reason=f"{ENV_COMMAND} is not configured.")
    status = str(transcription.get("status", ""))
    if status == "local_model_verified":
        return default_section(
            status="command_fixture_transcription",
            reason="Only the legacy command-backed transcription fixture is configured; it is not real ASR.",
            fallback_transcription=transcription,
        )
    if status == "placeholder_transcription":
        return default_section(
            status="placeholder_transcription",
            reason="Only deterministic placeholder transcription exists; no real ASR command is configured.",
            fallback_transcription=transcription,
        )
    return default_section(status="no_asr_configured", reason=f"{ENV_COMMAND} is not configured.", fallback_transcription=transcription)


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


def command_from_template(template: str, *, input_path: pathlib.Path, output_path: pathlib.Path, project_dir: pathlib.Path) -> str | list[str]:
    if os.name == "nt":
        return template.format(input=str(input_path), output=str(output_path), project=str(project_dir))
    return [
        part.format(input=str(input_path), output=str(output_path), project=str(project_dir))
        for part in shlex.split(template)
    ]


def load_transcript(path: pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"invalid_json:{exc}"]
    if not isinstance(doc, dict):
        return {}, ["transcript_not_object"]
    blockers: list[str] = []
    for field in REQUIRED_TRANSCRIPT_FIELDS:
        if field not in doc:
            blockers.append(f"{field}_missing")
    if "confidence" not in doc and "confidence_unavailable_reason" not in doc:
        blockers.append("confidence_or_reason_missing")
    if doc.get("stage") != "transcription":
        blockers.append("stage_mismatch")
    if doc.get("status") != "verified":
        blockers.append("status_not_verified")
    if doc.get("adapter_kind") != "real_local_asr":
        blockers.append("adapter_kind_not_real_local_asr")
    if not doc.get("engine") and not doc.get("model_name"):
        blockers.append("engine_or_model_name_missing")
    if not str(doc.get("text", "")).strip():
        blockers.append("text_empty")
    if not isinstance(doc.get("segments"), list) or not doc.get("segments"):
        blockers.append("segments_empty")
    if not isinstance(doc.get("evidence"), list):
        blockers.append("evidence_not_list")
    return doc, blockers


def production_blockers(doc: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if doc.get("production_asr") is not True:
        blockers.append("production_asr_not_true")
    if doc.get("degraded") is not False:
        blockers.append("degraded_not_false")
    return blockers


def status_from_failure(run: dict[str, Any], blockers: list[str]) -> str:
    if run.get("timed_out"):
        return "real_asr_timeout"
    if run.get("returncode") != 0:
        return "real_asr_failed"
    if blockers:
        return "real_asr_invalid_output"
    return "real_local_asr_verified"


def evaluate(
    *,
    project_dir: pathlib.Path,
    input_path: pathlib.Path,
    output_path: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 2.0,
    fallback_transcription: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    source = pathlib.Path(input_path)
    if not source.is_absolute():
        source = (project / source).resolve()
    output = pathlib.Path(output_path or project / "real_asr_transcript.json")
    source_record = file_record(source) if source.exists() and source.is_file() else {"path": str(source), "sha256": "", "size": 0}
    command_template = str((env if env is not None else os.environ).get(ENV_COMMAND, "")).strip()
    if not command_template:
        section = fallback_section(fallback_transcription)
        section.update({"input_path": str(source), "input_sha256": source_record["sha256"], "input_size": source_record["size"]})
        return section

    command = command_from_template(command_template, input_path=source, output_path=output, project_dir=project)
    run = run_bounded(command, timeout=timeout)
    if run.get("returncode") != 0 or run.get("timed_out"):
        return {
            **default_section(status=status_from_failure(run, []), reason="Configured real ASR command did not complete successfully."),
            "adapter_kind": "real_local_asr",
            "command": command,
            "returncode": run.get("returncode"),
            "timed_out": bool(run.get("timed_out")),
            "input_path": str(source),
            "output_path": str(output),
            "input_sha256": source_record["sha256"],
            "input_size": source_record["size"],
            "evidence": [run],
        }

    doc, blockers = load_transcript(output)
    is_fixture = asr_evidence_tier.is_contract_fixture(doc, run)
    production_issues = [] if is_fixture else production_blockers(doc)
    all_blockers = blockers + production_issues
    if all_blockers:
        artifact = file_record(output) if output.exists() else {"path": str(output), "sha256": "", "size": 0}
        return {
            **default_section(status="real_asr_invalid_output", reason="Configured real ASR command output failed schema or production-ASR checks."),
            "adapter_kind": "real_local_asr",
            "engine": doc.get("engine"),
            "model_name": doc.get("model_name"),
            "model_path": doc.get("model_path"),
            "command": command,
            "returncode": run.get("returncode"),
            "timed_out": False,
            "input_path": str(source),
            "output_path": str(output),
            "sha256": artifact["sha256"],
            "size": artifact["size"],
            "input_sha256": source_record["sha256"],
            "input_size": source_record["size"],
            "production_asr": bool(doc.get("production_asr")),
            "degraded": bool(doc.get("degraded", True)),
            "schema_valid": False,
            "schema_blockers": all_blockers,
            "evidence": [run, {"schema_blockers": all_blockers}],
        }

    artifact = file_record(output)
    if is_fixture:
        return {
            "status": "asr_contract_fixture_verified",
            "adapter_kind": "contract_fixture",
            "engine": doc.get("engine"),
            "model_name": doc.get("model_name"),
            "model_path": doc.get("model_path"),
            "command": command,
            "returncode": run.get("returncode"),
            "timed_out": False,
            "input_path": str(source),
            "output_path": str(output),
            "sha256": artifact["sha256"],
            "size": artifact["size"],
            "input_sha256": source_record["sha256"],
            "input_size": source_record["size"],
            "production_asr": False,
            "evidence_tier": "contract_fixture",
            "quality_report_path": "",
            "degraded": True,
            "schema_valid": True,
            "schema_blockers": [],
            "commercial_ready": False,
            "reason": "A bounded ASR contract fixture validated the command and transcript schema path; it is not production ASR evidence.",
            "evidence": [
                {
                    "command": run.get("command"),
                    "returncode": run.get("returncode"),
                    "duration_seconds": run.get("duration_seconds"),
                    "timed_out": run.get("timed_out"),
                    "stdout_summary": str(run.get("stdout") or "")[:500],
                    "stderr_summary": str(run.get("stderr") or "")[:500],
                },
                {
                    "segments": len(doc.get("segments", [])),
                    "text_length": len(str(doc.get("text", ""))),
                    "input_sha256": source_record["sha256"],
                    "input_size": source_record["size"],
                    "contract_test_fixture": True,
                },
            ],
        }
    return {
        "status": "real_local_asr_verified",
        "adapter_kind": "real_local_asr",
        "engine": doc.get("engine"),
        "model_name": doc.get("model_name"),
        "model_path": doc.get("model_path"),
        "command": command,
        "returncode": run.get("returncode"),
        "timed_out": False,
        "input_path": str(source),
        "output_path": str(output),
        "sha256": artifact["sha256"],
        "size": artifact["size"],
        "input_sha256": source_record["sha256"],
        "input_size": source_record["size"],
        "production_asr": False,
        "evidence_tier": "single_sample_real",
        "quality_report_path": "",
        "degraded": False,
        "schema_valid": True,
        "schema_blockers": [],
        "commercial_ready": False,
        "reason": "A bounded real-local-ASR command produced one schema-valid transcript; commercial readiness still requires multi-sample quality and production readiness evidence.",
        "evidence": [
            {
                "command": run.get("command"),
                "returncode": run.get("returncode"),
                "duration_seconds": run.get("duration_seconds"),
                "timed_out": run.get("timed_out"),
                "stdout_summary": str(run.get("stdout") or "")[:500],
                "stderr_summary": str(run.get("stderr") or "")[:500],
            },
            {
                "segments": len(doc.get("segments", [])),
                "text_length": len(str(doc.get("text", ""))),
                "input_sha256": source_record["sha256"],
                "input_size": source_record["size"],
            },
        ],
    }


def fixture_transcript(input_path: pathlib.Path, output_path: pathlib.Path) -> dict[str, Any]:
    duration = read_wave_duration(input_path)
    record = file_record(input_path)
    text = f"Contract-test real ASR transcript for {input_path.name}."
    return {
        "stage": "transcription",
        "status": "verified",
        "adapter_kind": "real_local_asr",
        "engine": "cgkn_contract_fixture_engine",
        "model_name": "contract-fixture-asr-v1",
        "model_path": "contract_fixture_no_model_download",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "created_at": now(),
        "language": "en",
        "duration_seconds": duration,
        "segments": [
            {
                "id": "asr_contract_seg_001",
                "start": 0,
                "end": duration,
                "text": text,
                "confidence": 0.99,
            }
        ],
        "text": text,
        "confidence": 0.99,
        "production_asr": False,
        "degraded": True,
        "evidence": [
            {"input_sha256": record["sha256"], "input_size": record["size"]},
            "contract test fixture: validates CGKN_REAL_ASR_CMD schema path only, not production model quality",
        ],
        "contract_test_fixture": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--fixture-adapter", action="store_true")
    args = parser.parse_args()
    input_path = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output) if args.output else pathlib.Path(args.project_dir) / "real_asr_transcript.json"
    if args.fixture_adapter:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, fixture_transcript(input_path, output_path))
        print(json.dumps({"status": "ok", "output": str(output_path), "contract_test_fixture": True}, ensure_ascii=False))
        return 0
    result = evaluate(
        project_dir=pathlib.Path(args.project_dir),
        input_path=input_path,
        output_path=output_path,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ASR_STATUSES else 2


if __name__ == "__main__":
    raise SystemExit(main())
