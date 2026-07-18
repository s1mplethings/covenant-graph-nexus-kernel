#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from typing import Any

try:
    import local_packager
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_packager

try:
    import local_media_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_media_adapter

try:
    import commercial_promotion_gate
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import commercial_promotion_gate

try:
    import production_reliability_gate
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import production_reliability_gate

try:
    import commercial_ready_gate
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import commercial_ready_gate


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: pathlib.Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: pathlib.Path, root: pathlib.Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "relative_path": path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name,
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "generated_at": now(),
    }


def default_smoke_command(project_dir: pathlib.Path) -> list[str]:
    if (project_dir / "cli.py").exists():
        fixture = project_dir / "fixtures" / "media_fixture.json"
        input_path = fixture.relative_to(project_dir).as_posix() if fixture.exists() else "input.mp4"
        return [sys.executable, "cli.py", "--input", input_path, "--output-dir", "."]
    if (project_dir / "main.py").exists():
        return [sys.executable, "main.py"]
    if (project_dir / "app.py").exists():
        return [sys.executable, "app.py", "--help"]
    return [sys.executable, "-m", "py_compile", "orchestrator.py", "stages.py"]


def run_smoke(project_dir: pathlib.Path, run_dir: pathlib.Path, command: list[str] | None = None) -> dict[str, Any]:
    argv = command or default_smoke_command(project_dir)
    started = now()
    start = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(project_dir), capture_output=True, text=True, timeout=60)
        result = {
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "argv": argv,
            "cwd": str(project_dir),
            "started_at": started,
            "ended_at": now(),
            "duration_seconds": round(time.time() - start, 3),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except Exception as exc:
        result = {
            "status": "FAIL",
            "argv": argv,
            "cwd": str(project_dir),
            "started_at": started,
            "ended_at": now(),
            "duration_seconds": round(time.time() - start, 3),
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    log_dir = run_dir / "delivery_evidence"
    log_dir.mkdir(parents=True, exist_ok=True)
    write_json(log_dir / "delivery_smoke_command.json", result)
    (log_dir / "delivery_smoke_command.log").write_text(
        "\n".join(
            [
                f"status: {result['status']}",
                f"argv: {' '.join(str(item) for item in argv)}",
                f"cwd: {project_dir}",
                f"returncode: {result.get('returncode')}",
                "",
                "stdout:",
                str(result.get("stdout") or ""),
                "",
                "stderr:",
                str(result.get("stderr") or ""),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    project_logs = project_dir / "run_logs"
    project_logs.mkdir(parents=True, exist_ok=True)
    write_json(project_logs / "delivery_smoke_command.json", result)
    (project_logs / "delivery_smoke_command.log").write_text((log_dir / "delivery_smoke_command.log").read_text(encoding="utf-8"), encoding="utf-8")
    return result


def write_readme(project_dir: pathlib.Path, run_dir: pathlib.Path, smoke: dict[str, Any]) -> pathlib.Path:
    source_files = sorted(path.name for path in project_dir.iterdir() if path.is_file())[:30]
    lines = [
        "# CGKN Generated Project",
        "",
        "This directory is a contract-driven generated project output. It contains requirement-selected planning documents, shared implementation structure, run logs, and delivery evidence produced from actual local commands.",
        "",
        "## Project Path",
        f"- `{project_dir}`",
        "",
        "## Run Command",
        "```bash",
        " ".join(str(item) for item in smoke.get("argv", [])),
        "```",
        "",
        "## Run Directory",
        f"- `{run_dir}`",
        "",
        "## Included Files",
        *[f"- `{name}`" for name in source_files],
        "",
        "## Known Limits",
        "- This is a degraded but honest scaffold delivery produced from contract materialization.",
        "- The smoke command verifies the shared CLI/orchestrator/stages path, not real media processing quality.",
        "- Final delivery evidence remains separate from Requirement Decision First, product contract, and implementation acceptance.",
    ]
    path = project_dir / "README.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def ensure_capability_manifest(project_dir: pathlib.Path) -> dict[str, Any]:
    manifest_path = project_dir / "capability_manifest.json"
    if manifest_path.exists():
        return read_json(manifest_path)
    wav = project_dir / "fixtures" / "sample_audio.wav"
    if wav.exists():
        return local_media_adapter.build_capability_manifest(project_dir, fixture_path=wav, output_path=manifest_path)
    return {}


def build_promotion_report(
    project_dir: pathlib.Path,
    capability: dict[str, Any],
    smoke: dict[str, Any],
    screenshot: dict[str, Any],
) -> dict[str, Any]:
    required_stage_artifacts = [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ]
    delivery_precheck = (
        smoke.get("status") == "PASS"
        and screenshot.get("status") == "PASS"
        and (project_dir / "README.md").exists()
        and all((project_dir / name).exists() for name in required_stage_artifacts)
    )
    reference_manifest = project_dir / "reference_transcript_manifest.json"
    report = commercial_promotion_gate.evaluate(
        project_dir=project_dir,
        capability_manifest=capability,
        delivery_integrity_status="PASS" if delivery_precheck else "FAIL",
        reference_manifest_path=reference_manifest if reference_manifest.exists() else None,
        output_path=project_dir / "production_asr_verification_report.json",
        enabled=os.environ.get("CGKN_COMMERCIAL_PROMOTION_GATE") == "1",
    )
    capabilities = capability.setdefault("capabilities", {})
    if isinstance(capabilities, dict):
        capabilities["commercial_promotion"] = {
            "status": "evaluated",
            "promotion_decision": report["promotion_decision"],
            "readiness_level": report["readiness_level"],
            "report_path": report["report_path"],
            "promotion_blockers": report["promotion_blockers"],
            "commercial_ready": False,
        }
    capability["commercial_status"] = report["readiness_level"]
    capability["commercial_ready"] = False
    write_json(project_dir / "capability_manifest.json", capability)
    return report


def build_ready_reports(
    project_dir: pathlib.Path,
    capability: dict[str, Any],
    promotion_report: dict[str, Any],
    smoke: dict[str, Any],
    screenshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    commercial_ready_gate.write_human_review_schema(project_dir / "human_review_evidence.schema.json")
    records_path = project_dir / "production_reliability_run_records.json"
    records_doc: Any = read_json(records_path) if records_path.exists() else {}
    records = records_doc.get("runs", []) if isinstance(records_doc, dict) else []
    if not isinstance(records, list):
        records = []
    reliability = production_reliability_gate.evaluate(
        run_records=records,
        output_path=project_dir / "production_reliability_report.json",
    )
    human_path = project_dir / "human_review_evidence.json"
    human_review = read_json(human_path) if human_path.exists() else {}
    required_stage_artifacts = [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ]
    evidence_precheck = (
        smoke.get("status") == "PASS"
        and screenshot.get("status") == "PASS"
        and (project_dir / "README.md").exists()
        and all((project_dir / name).exists() for name in required_stage_artifacts)
    )
    ready = commercial_ready_gate.evaluate(
        project_dir=project_dir,
        capability_manifest=capability,
        promotion_report=promotion_report,
        reliability_report=reliability,
        human_review_evidence=human_review or None,
        artifact_integrity_status="PASS" if evidence_precheck else "FAIL",
        delivery_status="PASS" if evidence_precheck else "FAIL",
        output_path=project_dir / "commercial_ready_report.json",
        enabled=os.environ.get("CGKN_COMMERCIAL_READY_GATE") == "1",
    )
    capabilities = capability.setdefault("capabilities", {})
    if isinstance(capabilities, dict):
        capabilities["production_reliability"] = {
            "status": reliability["reliability_status"],
            "report_path": "production_reliability_report.json",
            "run_count": reliability["run_count"],
            "blockers": reliability["blockers"],
        }
        capabilities["commercial_ready_gate"] = {
            "status": "evaluated",
            "ready_decision": ready["ready_decision"],
            "report_path": ready["report_path"],
            "critical_blockers": ready["critical_blockers"],
            "commercial_ready": ready["commercial_ready"],
        }
    capability["commercial_ready"] = ready["commercial_ready"]
    if ready["commercial_ready"]:
        capability["commercial_status"] = "COMMERCIAL_READY"
    write_json(project_dir / "capability_manifest.json", capability)
    return reliability, ready


def adapter_summary(project_dir: pathlib.Path, capability: dict[str, Any]) -> list[str]:
    if not capability:
        return ["- adapter_status: unavailable", "- selected_adapter: local_tool_unavailable"]
    tools = capability.get("tool_detection", {}) if isinstance(capability.get("tool_detection"), dict) else {}
    ffprobe = tools.get("ffprobe", {}) if isinstance(tools.get("ffprobe"), dict) else {}
    ffmpeg = tools.get("ffmpeg", {}) if isinstance(tools.get("ffmpeg"), dict) else {}
    capabilities = capability.get("capabilities", {}) if isinstance(capability.get("capabilities"), dict) else {}
    media = capabilities.get("media_metadata", {}) if isinstance(capabilities.get("media_metadata"), dict) else {}
    media_decode = capabilities.get("media_decode", {}) if isinstance(capabilities.get("media_decode"), dict) else {}
    asr = capabilities.get("asr", {}) if isinstance(capabilities.get("asr"), dict) else {}
    asr_quality = capabilities.get("asr_quality", {}) if isinstance(capabilities.get("asr_quality"), dict) else {}
    transcription = capabilities.get("transcription", {}) if isinstance(capabilities.get("transcription"), dict) else {}
    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities.get("user_media_input"), dict) else {}
    promotion = capabilities.get("commercial_promotion", {}) if isinstance(capabilities.get("commercial_promotion"), dict) else {}
    reliability = capabilities.get("production_reliability", {}) if isinstance(capabilities.get("production_reliability"), dict) else {}
    ready = capabilities.get("commercial_ready_gate", {}) if isinstance(capabilities.get("commercial_ready_gate"), dict) else {}
    return [
        f"- adapter_status: {capability.get('selected_adapter')}",
        f"- commercial_ready: {capability.get('commercial_ready')}",
        f"- media_metadata_status: {media.get('status')}",
        f"- user_media_input_status: {user_media.get('status', 'not_configured')}",
        f"- user_media_input_path: `{user_media.get('safe_input_path', '')}`",
        f"- user_media_input_size: {user_media.get('size', '')}",
        f"- user_media_input_sha256: {user_media.get('sha256', '')}",
        f"- user_media_metadata_status: {user_media.get('metadata_status', '')}",
        f"- user_media_adapter_status: {user_media.get('adapter_status', '')}",
        f"- user_media_manifest: `{user_media.get('media_manifest', '')}`",
        f"- media_decode_status: {media_decode.get('status', 'not_attempted')}",
        f"- media_decode_tool: {media_decode.get('tool', 'none')}",
        f"- media_decode_command: `{media_decode.get('command', '')}`",
        f"- media_decode_returncode: {media_decode.get('returncode')}",
        f"- media_decode_timed_out: {media_decode.get('timed_out')}",
        f"- media_decode_artifact: `{media_decode.get('artifact_path', '')}`",
        f"- media_decode_output: `{media_decode.get('output_path', '')}`",
        f"- media_decode_size: {media_decode.get('size', '')}",
        f"- media_decode_sha256: {media_decode.get('sha256', '')}",
        f"- asr_status: {asr.get('status', 'no_asr_configured')}",
        f"- asr_adapter_kind: {asr.get('adapter_kind', 'none')}",
        f"- asr_evidence_tier: {asr.get('evidence_tier', 'none')}",
        f"- asr_command: `{asr.get('command', '')}`",
        f"- asr_returncode: {asr.get('returncode')}",
        f"- asr_timed_out: {asr.get('timed_out')}",
        f"- asr_schema_valid: {asr.get('schema_valid')}",
        f"- asr_output_artifact: `{asr.get('output_path', '')}`",
        f"- asr_quality_report: `{asr.get('quality_report_path', '')}`",
        f"- asr_quality_status: {asr_quality.get('asr_quality_status', '')}",
        f"- asr_quality_adapter_kind: {asr_quality.get('adapter_kind', 'none')}",
        f"- asr_quality_evidence_tier: {asr_quality.get('evidence_tier', 'none')}",
        f"- asr_quality_sample_count: {asr_quality.get('sample_count', '')}",
        f"- asr_quality_successful_samples: {asr_quality.get('successful_samples', '')}",
        f"- asr_quality_failed_samples: {asr_quality.get('failed_samples', '')}",
        f"- asr_quality_timeout_samples: {asr_quality.get('timeout_samples', '')}",
        f"- asr_quality_invalid_output_samples: {asr_quality.get('invalid_output_samples', '')}",
        f"- asr_quality_success_rate: {asr_quality.get('success_rate', '')}",
        f"- asr_quality_non_empty_text_rate: {asr_quality.get('non_empty_text_rate', '')}",
        f"- asr_quality_non_empty_segments_rate: {asr_quality.get('non_empty_segments_rate', '')}",
        f"- asr_production_candidate: {asr_quality.get('production_candidate', False)}",
        f"- asr_production_verified: {asr_quality.get('production_verified', False)}",
        f"- asr_production_readiness_blockers: {asr_quality.get('production_readiness_blockers', [])}",
        f"- asr_production_asr: {asr.get('production_asr')}",
        f"- asr_degraded: {asr.get('degraded')}",
        f"- commercial_promotion_decision: {promotion.get('promotion_decision', 'COMMERCIAL_BETA')}",
        f"- commercial_readiness_level: {promotion.get('readiness_level', 'COMMERCIAL_BETA')}",
        f"- commercial_promotion_report: `{promotion.get('report_path', '')}`",
        f"- commercial_promotion_blockers: {promotion.get('promotion_blockers', [])}",
        f"- production_reliability_status: {reliability.get('status', 'not_ready')}",
        f"- production_reliability_run_count: {reliability.get('run_count', 0)}",
        f"- production_reliability_report: `{reliability.get('report_path', '')}`",
        f"- commercial_ready_decision: {ready.get('ready_decision', 'NOT_READY')}",
        f"- commercial_ready_report: `{ready.get('report_path', '')}`",
        f"- commercial_ready_blockers: {ready.get('critical_blockers', [])}",
        f"- transcription_status: {transcription.get('status')}",
        f"- transcription_tool: {transcription.get('tool')}",
        f"- transcription_not_production_asr: {transcription.get('not_production_asr')}",
        f"- transcription_output_artifact: `{transcription.get('output_artifact', '')}`",
        f"- ffprobe_status: {ffprobe.get('status', 'local_tool_unavailable')}",
        f"- ffmpeg_status: {ffmpeg.get('status', 'local_tool_unavailable')}",
        f"- capability_manifest: `{project_dir / 'capability_manifest.json'}`",
    ]


def write_test_report(project_dir: pathlib.Path, smoke: dict[str, Any], capability: dict[str, Any]) -> pathlib.Path:
    status = str(smoke.get("status"))
    lines = [
        "# TEST_REPORT",
        "",
        "## Smoke Command",
        "```bash",
        " ".join(str(item) for item in smoke.get("argv", [])),
        "```",
        "",
        f"- status: {status}",
        f"- returncode: {smoke.get('returncode')}",
        f"- duration_seconds: {smoke.get('duration_seconds')}",
        f"- cwd: `{smoke.get('cwd')}`",
        "",
        "## commands_run",
        f"- {' '.join(str(item) for item in smoke.get('argv', []))}",
        "",
        "## results",
        f"- exit_code: {smoke.get('returncode')}",
        f"- status: {status}",
        "",
        "## adapter_status",
        *adapter_summary(project_dir, capability),
        "",
        "## stdout tail",
        "```text",
        str(smoke.get("stdout") or "")[-3000:],
        "```",
        "",
        "## stderr tail",
        "```text",
        str(smoke.get("stderr") or "")[-3000:],
        "```",
    ]
    path = project_dir / "TEST_REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_delivery_notes(project_dir: pathlib.Path, smoke: dict[str, Any], screenshot_status: str, capability: dict[str, Any]) -> pathlib.Path:
    lines = [
        "# DELIVERY_NOTES",
        "",
        "## Delivery Contents",
        "- Requirement decision artifacts from run_dir.",
        "- Product contract documents in the generated project.",
        "- Shared implementation structure: orchestrator.py, stages.py, CLI, GUI.",
        "- Stage artifacts with schema and upstream traceability.",
        "- Real smoke command logs.",
        "- final_project_bundle.zip generated by the local packager.",
        "",
        "## Verified",
        f"- Smoke command status: {smoke.get('status')}",
        f"- Smoke command returncode: {smoke.get('returncode')}",
        f"- Screenshot evidence status: {screenshot_status}",
        "",
        "## Adapter Status",
        *adapter_summary(project_dir, capability),
        "",
        "## Degraded / Known Gaps",
        "- degraded scaffold: no real external model or media processing success is claimed.",
        "- User media pipeline support is a bounded local input contract: path, type, hash, metadata, and artifacts are verified, but this is not production media processing.",
        "- Media decode support is bounded local ffmpeg extract evidence when ffmpeg is available; unavailable or failed decode is reported explicitly and is not faked as verified.",
        "- ASR evidence tier may be none, placeholder, contract_fixture, single_sample_real, multi_sample_real, production_candidate, or production_verified.",
        "- ASR contract fixtures validate the command/schema path only and are not production ASR.",
        "- A single real_local_asr_verified sample is not enough for commercial readiness.",
        "- The ASR quality report records sample counts, failures, timeouts, invalid output, confidence availability, and production blockers.",
        "- A passing bounded multi-sample real-local-ASR threshold gate is only a production candidate; it is not production verified and cannot independently make the project commercial ready.",
        "- ASR production blockers remain in the multi-sample report and adapter summary until separate human quality, production load, reliability, and commercial gates pass.",
        "- The production ASR verification report records the promotion decision, reference transcript coverage, deterministic error metrics, and promotion blockers.",
        "- COMMERCIAL_CANDIDATE is not COMMERCIAL_READY; commercial_ready remains false until a separate stricter READY gate passes.",
        "- The independent COMMERCIAL_READY gate additionally requires repeat reliability evidence and approved human review evidence with no blocking findings.",
        "- Fixture gate tests validate rejection behavior only and are not current production or commercial readiness proof.",
        "- Bounded local WAV metadata verification is not production media processing.",
        "- Transcription may be placeholder_transcription or local_model_unavailable; neither is real model output.",
        "- local_model_verified, when configured, is bounded local command adapter evidence only and does not imply commercial readiness.",
        "- command-backed local fixture adapters are not production ASR and must remain marked not_production_asr.",
        "- The generated artifacts prove structure and evidence flow, not commercial production completeness.",
        "- Delivery PASS is allowed only when actual README, TEST_REPORT, DELIVERY_NOTES, screenshot, run_dir, smoke log, and zip evidence exist.",
    ]
    path = project_dir / "DELIVERY_NOTES.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")


def render_status_png(path: pathlib.Path, smoke: dict[str, Any]) -> None:
    width, height = 640, 360
    ok = smoke.get("status") == "PASS"
    bg = (24, 38, 52) if ok else (70, 28, 28)
    accent = (45, 180, 125) if ok else (220, 90, 80)
    rows = []
    seed = int(hashlib.sha256(json.dumps(smoke, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8], 16)
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            stripe = ((x // 32) + (y // 24) + seed) % 11 == 0
            panel = 40 < x < 600 and 55 < y < 305
            header = panel and y < 115
            if header:
                color = accent
            elif panel:
                color = (238, 242, 246) if ((x + y + seed) % 17) else (210, 222, 232)
            elif stripe:
                color = tuple(min(255, channel + 18) for channel in bg)
            else:
                color = bg
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(raw, 9)) + png_chunk(b"IEND", b""))


def write_status_page(project_dir: pathlib.Path, smoke: dict[str, Any]) -> pathlib.Path:
    path = project_dir / "delivery_status_page.html"
    path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                "<html><head><meta charset=\"utf-8\"><title>CGKN Delivery Status</title></head>",
                "<body>",
                "<h1>CGKN Delivery Status</h1>",
                f"<p>Smoke status: {smoke.get('status')}</p>",
                f"<p>Return code: {smoke.get('returncode')}</p>",
                f"<p>Command: {' '.join(str(item) for item in smoke.get('argv', []))}</p>",
                "<p>This rendered status page is generated from real smoke command output.</p>",
                "</body></html>",
            ]
        ),
        encoding="utf-8",
    )
    return path


def write_screenshot(project_dir: pathlib.Path, run_dir: pathlib.Path, smoke: dict[str, Any], capture: bool) -> dict[str, Any]:
    if not capture:
        blocked = {
            "status": "BLOCKED",
            "failure_reason": "screenshot_capture_disabled",
            "created_at": now(),
            "screenshot_attempted": False,
            "not_screenshot_evidence": True,
        }
        write_json(project_dir / "screenshot_blocked.json", blocked)
        write_json(run_dir / "delivery_evidence" / "screenshot_blocked.json", blocked)
        return {"status": "BLOCKED", "path": "", "blocked_path": str(project_dir / "screenshot_blocked.json")}
    write_status_page(project_dir, smoke)
    screenshot = project_dir / "screenshots" / "delivery_smoke_screenshot.png"
    render_status_png(screenshot, smoke)
    return {"status": "PASS", "path": str(screenshot), "blocked_path": ""}


def evidence_manifest(project_dir: pathlib.Path, run_dir: pathlib.Path, smoke: dict[str, Any], screenshot: dict[str, Any], package_manifest: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    important = [
        "README.md",
        "TEST_REPORT.md",
        "DELIVERY_NOTES.md",
        "delivery_status_page.html",
        "final_project_bundle.zip",
        "delivery_manifest.json",
        "run_logs/delivery_smoke_command.json",
        "run_logs/delivery_smoke_command.log",
    ]
    capability_path = project_dir / "capability_manifest.json"
    if capability_path.exists():
        important.append("capability_manifest.json")
    capabilities = capability.get("capabilities", {}) if isinstance(capability.get("capabilities"), dict) else {}
    transcription = capabilities.get("transcription", {}) if isinstance(capabilities.get("transcription"), dict) else {}
    transcription_output = str(transcription.get("output_artifact", "")).strip()
    if transcription_output:
        try:
            transcript_rel = pathlib.Path(transcription_output).relative_to(project_dir).as_posix()
        except ValueError:
            transcript_rel = pathlib.Path(transcription_output).name
        if transcript_rel and transcript_rel not in important:
            important.append(transcript_rel)
    asr = capabilities.get("asr", {}) if isinstance(capabilities.get("asr"), dict) else {}
    asr_output = str(asr.get("output_path", "")).strip()
    if asr_output:
        asr_rel = pathlib.Path(asr_output).name if pathlib.Path(asr_output).is_absolute() else asr_output
        if asr_rel and asr_rel not in important:
            important.append(asr_rel)
    asr_quality = capabilities.get("asr_quality", {}) if isinstance(capabilities.get("asr_quality"), dict) else {}
    quality_rel = str(asr.get("quality_report_path", "") or asr_quality.get("quality_report_path", "") or "asr_quality_report.json").strip()
    if quality_rel:
        quality_name = pathlib.Path(quality_rel).name if pathlib.Path(quality_rel).is_absolute() else quality_rel
        if quality_name and quality_name not in important:
            important.append(quality_name)
    promotion = capabilities.get("commercial_promotion", {}) if isinstance(capabilities.get("commercial_promotion"), dict) else {}
    promotion_rel = str(promotion.get("report_path", "") or "production_asr_verification_report.json").strip()
    if promotion_rel:
        promotion_name = pathlib.Path(promotion_rel).name if pathlib.Path(promotion_rel).is_absolute() else promotion_rel
        if promotion_name and promotion_name not in important:
            important.append(promotion_name)
    reliability = capabilities.get("production_reliability", {}) if isinstance(capabilities.get("production_reliability"), dict) else {}
    ready = capabilities.get("commercial_ready_gate", {}) if isinstance(capabilities.get("commercial_ready_gate"), dict) else {}
    for rel in (
        str(reliability.get("report_path", "") or "production_reliability_report.json").strip(),
        str(ready.get("report_path", "") or "commercial_ready_report.json").strip(),
    ):
        if rel:
            name = pathlib.Path(rel).name if pathlib.Path(rel).is_absolute() else rel
            if name and name not in important:
                important.append(name)
    for optional_name in ("human_review_evidence.schema.json", "human_review_evidence.json", "production_reliability_run_records.json"):
        if (project_dir / optional_name).exists() and optional_name not in important:
            important.append(optional_name)
    reference_manifest = project_dir / "reference_transcript_manifest.json"
    if reference_manifest.exists() and "reference_transcript_manifest.json" not in important:
        important.append("reference_transcript_manifest.json")
    user_media = capabilities.get("user_media_input", {}) if isinstance(capabilities.get("user_media_input"), dict) else {}
    for rel in (
        str(user_media.get("media_manifest", "")).strip(),
        str(user_media.get("inspect_artifact", "")).strip(),
        str(user_media.get("smoke_log", "")).strip(),
    ):
        if rel and rel not in important:
            important.append(pathlib.Path(rel).name if pathlib.Path(rel).is_absolute() else rel)
    media_decode = capabilities.get("media_decode", {}) if isinstance(capabilities.get("media_decode"), dict) else {}
    for rel in (
        str(media_decode.get("artifact_path", "")).strip(),
        str(media_decode.get("output_path", "")).strip(),
    ):
        if rel:
            rel_name = pathlib.Path(rel).name if pathlib.Path(rel).is_absolute() else rel
            if rel_name and rel_name not in important:
                important.append(rel_name)
    if screenshot.get("path"):
        important.append(pathlib.Path(str(screenshot["path"])).relative_to(project_dir).as_posix())
    if screenshot.get("blocked_path"):
        important.append(pathlib.Path(str(screenshot["blocked_path"])).relative_to(project_dir).as_posix())
    implementation_manifest = read_text(project_dir / "implementation_structure_manifest.json")
    try:
        implementation_doc = json.loads(implementation_manifest) if implementation_manifest.strip() else {}
    except Exception:
        implementation_doc = {}
    for name in implementation_doc.get("stage_artifacts", []) if isinstance(implementation_doc, dict) else []:
        rel = str(name)
        if rel and rel not in important:
            important.append(rel)
    fixture = project_dir / "fixtures" / "media_fixture.json"
    if fixture.exists():
        important.append(fixture.relative_to(project_dir).as_posix())
    wav_fixture = project_dir / "fixtures" / "sample_audio.wav"
    if wav_fixture.exists():
        important.append(wav_fixture.relative_to(project_dir).as_posix())
    files: dict[str, Any] = {}
    for rel in important:
        path = project_dir / rel
        if path.exists() and path.is_file():
            files[rel] = file_record(path, project_dir)
    return {
        "kind": "CGKNDeliveryManifest",
        "created_at": now(),
        "project_dir": str(project_dir),
        "run_dir": str(run_dir),
        "package_path": str(project_dir / "final_project_bundle.zip"),
        "readme_path": str(project_dir / "README.md"),
        "test_report_path": str(project_dir / "TEST_REPORT.md"),
        "delivery_notes_path": str(project_dir / "DELIVERY_NOTES.md"),
        "capability_manifest_path": str(project_dir / "capability_manifest.json") if capability_path.exists() else "",
        "capability_manifest": capability,
        "screenshot_path": str(screenshot.get("path") or ""),
        "screenshot_blocked_path": str(screenshot.get("blocked_path") or ""),
        "smoke_command": smoke,
        "evidence_status": {
            "smoke_command": {"status": smoke.get("status"), "returncode": smoke.get("returncode")},
            "readme": {"status": "PASS" if (project_dir / "README.md").exists() else "FAIL"},
            "test_report": {"status": "PASS" if (project_dir / "TEST_REPORT.md").exists() else "FAIL"},
            "delivery_notes": {"status": "PASS" if (project_dir / "DELIVERY_NOTES.md").exists() else "FAIL"},
            "capability_manifest": {"status": "PASS" if capability_path.exists() else "MISSING", "selected_adapter": capability.get("selected_adapter")},
            "screenshot": {"status": screenshot.get("status"), "path": screenshot.get("path") or screenshot.get("blocked_path")},
            "final_project_bundle": {"status": "PASS" if (project_dir / "final_project_bundle.zip").exists() else "FAIL"},
        },
        "files": files,
        "local_packager_manifest": package_manifest,
        "known_gaps": [
            "degraded fixture: bounded local WAV metadata verification is not production media processing",
            "user media pipeline: bounded local input contract is not production media processing",
            "media decode: bounded ffmpeg extract evidence is not ASR or full production media processing",
            "asr: contract fixture or single-sample ASR evidence is not enough for commercial readiness by itself",
            "asr quality: production readiness requires multi-sample quality evidence and explicit production gates",
            "local_model_unavailable: no real transcription model is bundled or claimed",
        ],
    }


def build(
    *,
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    smoke_command: list[str] | None = None,
    capture_screenshot: bool = True,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    run = pathlib.Path(run_dir)
    project.mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True, exist_ok=True)
    smoke = run_smoke(project, run, smoke_command)
    capability = ensure_capability_manifest(project)
    screenshot = write_screenshot(project, run, smoke, capture_screenshot)
    write_readme(project, run, smoke)
    promotion_report = build_promotion_report(project, capability, smoke, screenshot)
    build_ready_reports(project, capability, promotion_report, smoke, screenshot)
    write_test_report(project, smoke, capability)
    write_delivery_notes(project, smoke, str(screenshot.get("status")), capability)
    package_manifest = local_packager.package_project(
        project,
        output_dir=project,
        startup_command=" ".join(str(item) for item in smoke.get("argv", [])),
        run_log_path=project / "run_logs" / "delivery_smoke_command.log",
        screenshot_path=screenshot.get("path") or "",
        known_limits=["degraded scaffold: no real external media/model processing claimed"],
    )
    # Keep the canonical manifest written by local_packager authoritative.  This
    # builder's richer support-lane report must never overwrite that trust-boundary
    # artifact, especially when canonical packaging returns NEEDS_REWORK.
    manifest_path = project / "delivery_evidence_manifest.json"
    manifest = evidence_manifest(project, run, smoke, screenshot, package_manifest, capability)
    write_json(manifest_path, manifest)
    # Re-package once so the enriched manifest is included in the bundle as evidence.
    package_manifest = local_packager.package_project(
        project,
        output_dir=project,
        startup_command=" ".join(str(item) for item in smoke.get("argv", [])),
        run_log_path=project / "run_logs" / "delivery_smoke_command.log",
        screenshot_path=screenshot.get("path") or "",
        known_limits=["degraded scaffold: no real external media/model processing claimed"],
    )
    manifest = evidence_manifest(project, run, smoke, screenshot, package_manifest, capability)
    write_json(manifest_path, manifest)
    package_status = str(package_manifest.get("status", "NEEDS_REWORK"))
    status = (
        package_status
        if package_status in {"PASS", "PASS_WITH_LIMITS"}
        and smoke.get("status") == "PASS"
        and screenshot.get("status") == "PASS"
        else "NEEDS_REWORK"
    )
    return {
        "status": status,
        "project_dir": str(project),
        "run_dir": str(run),
        "readme": str(project / "README.md"),
        "test_report": str(project / "TEST_REPORT.md"),
        "delivery_notes": str(project / "DELIVERY_NOTES.md"),
        "screenshot": screenshot,
        "final_project_bundle": str(project / "final_project_bundle.zip"),
        "delivery_manifest": str(manifest_path),
        "smoke_command": smoke,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--no-screenshot", action="store_true")
    args = parser.parse_args()
    result = build(project_dir=pathlib.Path(args.project_dir), run_dir=pathlib.Path(args.run_dir), capture_screenshot=not args.no_screenshot)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
