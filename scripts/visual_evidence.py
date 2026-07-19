#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any

try:
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


def _legacy() -> Any:
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "real_image_file"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "real_image_file"):
        return packaged
    top_level = sys.modules.get("run_local_pipeline")
    if top_level is not None and hasattr(top_level, "real_image_file"):
        return top_level
    implementation = sys.modules.get("scripts.run_local_pipeline_impl")
    if implementation is not None:
        return implementation
    try:
        return importlib.import_module("scripts.run_local_pipeline_impl")
    except ModuleNotFoundError:
        return importlib.import_module("run_local_pipeline_impl")


def _legacy_call(name: str, *args: Any, **kwargs: Any) -> Any:
    return getattr(_legacy(), name)(*args, **kwargs)


def real_image_file(path: pathlib.Path) -> bool:
    try:
        from canonical_media_validation import validate_image
    except ModuleNotFoundError:
        from scripts.canonical_media_validation import validate_image
    target = pathlib.Path(path)
    result = validate_image(target, target.parent, requested_role="screenshot")
    return result.get("status") == "PASS"


def video_requested(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return str(os.environ.get("CGNK_DISABLE_VIDEO", "")).strip().lower() not in {"1", "true", "yes", "on"}


def video_file_diagnostics(path: pathlib.Path) -> dict[str, Any]:
    target = pathlib.Path(path)
    result: dict[str, Any] = {
        "path": str(target),
        "exists": target.exists(),
        "size_bytes": target.stat().st_size if target.exists() else 0,
        "duration_seconds": 0.0,
        "valid": False,
        "reason": "",
    }
    if not target.exists() or not target.is_file():
        result["reason"] = "missing"
        return result
    if target.stat().st_size < 2048:
        result["reason"] = "too_small"
        return result
    try:
        header = target.read_bytes()[:64]
    except Exception:
        header = b""
    if header.strip().lower().startswith((b"placeholder", b"fake", b"not a video")):
        result["reason"] = "placeholder"
        return result
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            proc = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(target)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode == 0:
                result["duration_seconds"] = float(str(proc.stdout).strip() or 0.0)
        except Exception:
            result["duration_seconds"] = 0.0
        if float(result["duration_seconds"] or 0.0) <= 1.0:
            result["reason"] = "duration_too_short"
            return result
    result["valid"] = True
    result["reason"] = "ok"
    return result


def write_video_blocked(
    project_dir: pathlib.Path,
    reason: str,
    *,
    failure_reason: str = "unknown",
    environment: dict[str, str] | None = None,
    browser_used: str = "",
    attempted_url: str = "",
    video_requested_value: bool = True,
    next_repair_hint: str = "",
) -> str:
    allowed = {
        "not_requested",
        "ffmpeg_unavailable",
        "browser_video_unavailable",
        "browser_unavailable",
        "startup_failed",
        "page_blank",
        "timeout",
        "capture_failed",
        "environment_failure",
        "unknown",
    }
    normalized = str(failure_reason or "unknown")
    if normalized not in allowed:
        normalized = "unknown"
    if normalized == "not_requested" and video_requested_value:
        normalized = "unknown"
    env = environment or _legacy_call("screenshot_environment_diagnostics")
    path = pathlib.Path(project_dir) / "video_blocked.json"
    path.write_text(
        json.dumps(
            {
                "status": "blocked",
                "video_requested": bool(video_requested_value),
                "failure_reason": normalized,
                "reason": reason,
                "ffmpeg_path": str(env.get("ffmpeg", "")),
                "playwright_available": "unavailable" not in str(env.get("playwright", "")).lower(),
                "browser_used": browser_used,
                "attempted_url": attempted_url,
                "next_repair_hint": next_repair_hint,
                "created_at": _legacy_call("now"),
                "candidate_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(path)


def startup_entry_candidates(project_dir: pathlib.Path) -> list[dict[str, Any]]:
    project = pathlib.Path(project_dir)
    script_candidates = [
        candidate
        for candidate in _legacy_call("candidate_startup_candidates", project)
        if str(candidate.get("mode", "")) != "static_html"
    ]
    static_candidates: list[dict[str, Any]] = []
    if (project / "index.html").exists():
        static_candidates.append({"mode": "static_html", "path": "index.html"})
    if (project / "dist" / "index.html").exists():
        static_candidates.append({"mode": "static_html", "path": "dist/index.html"})
    # Visual capture prefers the pipeline-owned static server so screenshots do not
    # depend on a generated project's fragile start script unless static serving is unavailable.
    return static_candidates + script_candidates


def startup_base_details(
    candidate: dict[str, Any] | None = None,
    *,
    project_dir: pathlib.Path,
    environment: dict[str, str] | None = None,
    opened_url: str = "",
    startup_command: list[str] | None = None,
    port: int | None = None,
    browser_available: bool = True,
    failure_reason: str = "",
) -> dict[str, Any]:
    candidate = candidate or {}
    entrypoint = str(candidate.get("path") or candidate.get("script") or candidate.get("mode") or "")
    command = " ".join(startup_command or [str(item) for item in candidate.get("argv", []) if str(item).strip()])
    return {
        "detected_entrypoint": entrypoint,
        "startup_command": command,
        "startup_cwd": str(pathlib.Path(project_dir)),
        "startup_returncode": None,
        "startup_stdout_tail": "",
        "startup_stderr_tail": "",
        "port": port,
        "server_ready": False,
        "opened_url": opened_url,
        "browser_used": "chromium" if browser_available else "",
        "browser_available": browser_available,
        "page_title": "",
        "body_text_length": 0,
        "body_text_sample": "",
        "console_errors": [],
        "network_errors": [],
        "screenshot_attempted": False,
        "screenshot_path": "",
        "environment": environment or _legacy_call("screenshot_environment_diagnostics"),
        "failure_reason": failure_reason,
        "next_repair_hint": "",
    }


def _tail(value: str, limit: int = 2000) -> str:
    return str(value or "")[-limit:]


def _record_process_tail(proc: subprocess.Popen[str] | None, details: dict[str, Any]) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
    except Exception:
        try:
            if sys.platform.startswith("win"):
                _legacy_call("kill_windows_process_tree", proc.pid)
            else:
                proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", ""
    details["startup_returncode"] = proc.returncode
    details["startup_stdout_tail"] = _tail(stdout)
    details["startup_stderr_tail"] = _tail(stderr)


def _open_and_capture(url: str, out: pathlib.Path, details: dict[str, Any], timeout: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
            console_errors: list[str] = []
            network_errors: list[str] = []
            try:
                page.on("console", lambda msg: console_errors.append(str(msg.text)) if str(getattr(msg, "type", "")).lower() == "error" else None)
                page.on("requestfailed", lambda req: network_errors.append(str(req.url)))
            except Exception:
                pass
            page.goto(url, wait_until="domcontentloaded", timeout=min(timeout, 30) * 1000)
            page.wait_for_timeout(500)
            try:
                details["page_title"] = str(page.title())
            except Exception:
                details["page_title"] = ""
            try:
                body_text = str(page.evaluate("() => document.body ? document.body.innerText : ''") or "")
            except Exception:
                body_text = ""
            details["body_text_length"] = len(body_text)
            details["body_text_sample"] = body_text[:500]
            details["console_errors"] = console_errors[:20]
            details["network_errors"] = network_errors[:20]
            details["screenshot_attempted"] = True
            details["screenshot_path"] = str(out)
            page.screenshot(path=str(out), full_page=True)
        finally:
            browser.close()


def capture_candidate_screenshot(project_dir: pathlib.Path, run_dir: pathlib.Path, timeout: int = 60) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    out_dir = project / "artifacts" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "candidate_home.png"
    attempts: list[dict[str, Any]] = []
    environment = _legacy_call("screenshot_environment_diagnostics")
    candidates = startup_entry_candidates(project)
    if not candidates:
        details = startup_base_details(project_dir=project, environment=environment, browser_available=True, failure_reason="entrypoint_missing")
        details["next_repair_hint"] = "Add a runnable entrypoint such as package.json start script, index.html, dist/index.html, app.py, or main.py."
        blocked = _legacy_call("write_screenshot_blocked", project, "no candidate startup mode detected", failure_type="entrypoint_missing", details=details)
        return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}

    try:
        import playwright  # noqa: F401
    except Exception as exc:
        details = startup_base_details(candidates[0], project_dir=project, environment=environment, browser_available=False, failure_reason="browser_unavailable")
        details["next_repair_hint"] = "Install or repair browser automation runtime; do not repair project code for this environment-only failure."
        blocked = _legacy_call("write_screenshot_blocked", project, f"playwright unavailable: {exc}", failure_type="browser_unavailable", details=details)
        return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}

    last_error = ""
    last_details = startup_base_details(candidates[0], project_dir=project, environment=environment)
    for candidate in candidates:
        proc: subprocess.Popen[str] | None = None
        details = startup_base_details(candidate, project_dir=project, environment=environment)
        try:
            mode = str(candidate.get("mode", ""))
            port = int(_legacy_call("find_free_local_port"))
            env = os.environ.copy()
            env["PORT"] = str(port)
            env["HOST"] = "127.0.0.1"
            if mode == "static_html":
                rel_path = str(candidate.get("path", "index.html")).replace("\\", "/").lstrip("/")
                url = f"http://127.0.0.1:{port}/{rel_path}"
                argv = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
                details.update(startup_base_details(candidate, project_dir=project, environment=environment, opened_url=url, startup_command=argv, port=port))
                proc = subprocess.Popen(argv, cwd=str(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            else:
                url = f"http://127.0.0.1:{port}"
                raw_argv = [str(item) for item in candidate.get("argv", [])]
                if not _legacy_call("argv_is_allowed", raw_argv):
                    details.update(startup_base_details(candidate, project_dir=project, environment=environment, opened_url=url, startup_command=raw_argv, port=port, failure_reason="startup_failed"))
                    details["next_repair_hint"] = "Startup command is not in the allowed command list."
                    attempts.append({"candidate": candidate, "ok": False, "reason": "startup command not allowed", "url": url, "diagnostics": details})
                    last_error = "startup command not allowed"
                    last_details = details
                    continue
                argv = _legacy_call("normalize_allowed_argv", raw_argv)
                details.update(startup_base_details(candidate, project_dir=project, environment=environment, opened_url=url, startup_command=argv, port=port))
                proc = subprocess.Popen(argv, cwd=str(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

            if not _legacy_call("wait_for_url", url, timeout=min(timeout, 25)):
                last_error = "startup URL did not become ready"
                details["failure_reason"] = "startup_failed"
                details["server_ready"] = False
                details["next_repair_hint"] = "The candidate did not expose a reachable local HTTP URL for visual capture."
                _record_process_tail(proc, details)
                proc = None
                attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "url": url, "diagnostics": details})
                last_details = details
                continue

            details["server_ready"] = True
            _open_and_capture(url, out, details, timeout)
            image_diag = _legacy_call("image_file_diagnostics", out)
            details["image_diagnostics"] = image_diag
            details.update(image_diag)
            smoke = _legacy_call(
                "candidate_ui_smoke",
                details,
                ["Task", "Bug", "Todo", "Doing", "Done", "Open", "Fixed", "Add", "Dashboard"],
            )
            if real_image_file(out) and smoke.get("status") == "pass":
                attempts.append({"candidate": candidate, "ok": True, "url": url, "screenshot": str(out), "diagnostics": details})
                _record_process_tail(proc, details)
                proc = None
                return {"status": "pass", "screenshots": [str(out)], "screenshot_blocked": "", "attempts": attempts, "startup": candidate, "ui_smoke": smoke}

            last_error = "captured screenshot was missing or invalid" if real_image_file(out) else "captured screenshot was blank or invalid"
            details["failure_reason"] = "page_blank" if int(details.get("body_text_length") or 0) <= 50 else _legacy_call(
                "screenshot_failure_reason",
                last_error,
                failure_type="screenshot_failure",
                body_text_length=int(details.get("body_text_length") or 0),
                image_diag=image_diag,
            )
            details["next_repair_hint"] = "Page loaded but failed UI smoke; inspect body text, console errors, network errors, and entrypoint wiring."
            try:
                out.unlink(missing_ok=True)
            except Exception:
                pass
            attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "url": url, "diagnostics": details})
            last_details = details
        except Exception as exc:
            last_error = str(exc)
            failure_type = "browser_unavailable" if "playwright install" in last_error.lower() or "executable doesn't exist" in last_error.lower() else ("page_load_timeout" if "timeout" in last_error.lower() else "screenshot_failure")
            details["failure_reason"] = _legacy_call(
                "screenshot_failure_reason",
                last_error,
                failure_type=failure_type,
                body_text_length=int(details.get("body_text_length") or 0),
                image_diag=details.get("image_diagnostics") if isinstance(details.get("image_diagnostics"), dict) else {},
            )
            details["next_repair_hint"] = "Browser automation failed while opening or capturing the candidate page."
            try:
                out.unlink(missing_ok=True)
            except Exception:
                pass
            attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "failure_type": failure_type, "diagnostics": details})
            last_details = details
        finally:
            if proc is not None:
                _record_process_tail(proc, details)

    final_reason = last_error or "candidate screenshot capture failed"
    preferred = dict(last_details)
    preferred["attempts"] = [{key: value for key, value in attempt.items() if key != "diagnostics"} for attempt in attempts]
    failure_type = "browser_unavailable" if str(preferred.get("failure_reason", "")).lower() == "browser_unavailable" else "screenshot_failure"
    if not preferred.get("failure_reason"):
        preferred["failure_reason"] = _legacy_call("screenshot_failure_reason", final_reason, failure_type=failure_type, body_text_length=int(preferred.get("body_text_length") or 0), image_diag=preferred.get("image_diagnostics") if isinstance(preferred.get("image_diagnostics"), dict) else {})
    blocked = _legacy_call("write_screenshot_blocked", project, final_reason, failure_type=failure_type, details=preferred)
    return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}


def capture_candidate_video(
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    *,
    timeout: int = 60,
    explicit_requested: bool | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    requested = video_requested(explicit_requested)
    environment = _legacy_call("screenshot_environment_diagnostics")
    if not requested:
        blocked = write_video_blocked(
            project,
            "video capture disabled by user option",
            failure_reason="not_requested",
            environment=environment,
            video_requested_value=False,
        )
        return {"status": "blocked", "video": "", "video_blocked": blocked, "video_requested": False, "failure_reason": "not_requested"}

    candidates = startup_entry_candidates(project)
    if not candidates:
        blocked = write_video_blocked(
            project,
            "no candidate startup mode detected",
            failure_reason="startup_failed",
            environment=environment,
            video_requested_value=True,
            next_repair_hint="Add index.html, dist/index.html, or a reachable start script before video capture.",
        )
        return {"status": "blocked", "video": "", "video_blocked": blocked, "video_requested": True, "failure_reason": "startup_failed"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        blocked = write_video_blocked(
            project,
            f"playwright video unavailable: {exc}",
            failure_reason="browser_video_unavailable",
            environment=environment,
            video_requested_value=True,
            next_repair_hint="Install or repair Playwright browser video support.",
        )
        return {"status": "blocked", "video": "", "video_blocked": blocked, "video_requested": True, "failure_reason": "browser_video_unavailable"}

    out_dir = project / "artifacts" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    record_dir = pathlib.Path(run_dir) / "artifacts" / "browser_video"
    record_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    last_reason = "unknown"
    last_url = ""
    for candidate in candidates:
        proc: subprocess.Popen[str] | None = None
        details = startup_base_details(candidate, project_dir=project, environment=environment)
        try:
            mode = str(candidate.get("mode", ""))
            port = int(_legacy_call("find_free_local_port"))
            env = os.environ.copy()
            env["PORT"] = str(port)
            env["HOST"] = "127.0.0.1"
            if mode == "static_html":
                rel_path = str(candidate.get("path", "index.html")).replace("\\", "/").lstrip("/")
                url = f"http://127.0.0.1:{port}/{rel_path}"
                argv = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
            else:
                url = f"http://127.0.0.1:{port}"
                raw_argv = [str(item) for item in candidate.get("argv", [])]
                if not _legacy_call("argv_is_allowed", raw_argv):
                    last_reason = "startup_failed"
                    attempts.append({"candidate": candidate, "ok": False, "reason": "startup command not allowed", "url": url})
                    continue
                argv = _legacy_call("normalize_allowed_argv", raw_argv)
            last_url = url
            details.update(startup_base_details(candidate, project_dir=project, environment=environment, opened_url=url, startup_command=argv, port=port))
            proc = subprocess.Popen(argv, cwd=str(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            if not _legacy_call("wait_for_url", url, timeout=min(timeout, 25)):
                last_reason = "startup_failed"
                _record_process_tail(proc, details)
                proc = None
                attempts.append({"candidate": candidate, "ok": False, "reason": "startup URL did not become ready", "url": url, "diagnostics": details})
                continue
            details["server_ready"] = True
            before = {path.resolve() for path in record_dir.glob("*.webm")}
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(record_dir))
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=min(timeout, 30) * 1000)
                    page.wait_for_timeout(1000)
                    try:
                        body_text = str(page.evaluate("() => document.body ? document.body.innerText : ''") or "")
                    except Exception:
                        body_text = ""
                    details["body_text_length"] = len(body_text)
                    details["body_text_sample"] = body_text[:500]
                    if len(body_text) <= 50:
                        last_reason = "page_blank"
                    page.mouse.wheel(0, 600)
                    page.wait_for_timeout(1500)
                    page.mouse.wheel(0, -300)
                    page.wait_for_timeout(1500)
                finally:
                    context.close()
                    browser.close()
            if last_reason == "page_blank":
                attempts.append({"candidate": candidate, "ok": False, "reason": "page_blank", "url": url, "diagnostics": details})
                continue
            time.sleep(0.2)
            videos = [path for path in record_dir.glob("*.webm") if path.resolve() not in before]
            videos = sorted(videos, key=lambda path: path.stat().st_mtime, reverse=True)
            if not videos:
                last_reason = "browser_video_unavailable"
                attempts.append({"candidate": candidate, "ok": False, "reason": "no recorded video", "url": url, "diagnostics": details})
                continue
            source = videos[0]
            target = out_dir / "candidate_demo.webm"
            shutil.copy2(source, target)
            diag = video_file_diagnostics(target)
            if diag.get("valid"):
                attempts.append({"candidate": candidate, "ok": True, "url": url, "video": str(target), "diagnostics": details, "video_diagnostics": diag})
                _record_process_tail(proc, details)
                proc = None
                return {"status": "pass", "video": str(target), "video_blocked": "", "video_requested": True, "attempts": attempts, "video_diagnostics": diag}
            last_reason = "capture_failed"
            attempts.append({"candidate": candidate, "ok": False, "reason": str(diag.get("reason", "capture_failed")), "url": url, "diagnostics": details, "video_diagnostics": diag})
        except Exception as exc:
            text = str(exc).lower()
            last_reason = "timeout" if "timeout" in text else ("browser_video_unavailable" if "playwright" in text or "executable doesn't exist" in text else "capture_failed")
            attempts.append({"candidate": candidate, "ok": False, "reason": str(exc), "url": last_url})
        finally:
            if proc is not None:
                _record_process_tail(proc, details)

    if last_reason == "unknown" and not environment.get("ffmpeg") and "unavailable" in str(environment.get("playwright", "")).lower():
        last_reason = "ffmpeg_unavailable"
    blocked = write_video_blocked(
        project,
        "candidate browser video could not be captured",
        failure_reason=last_reason,
        environment=environment,
        browser_used="chromium",
        attempted_url=last_url,
        video_requested_value=True,
        next_repair_hint="Inspect startup, UI smoke, browser recording support, and video diagnostics.",
    )
    return {"status": "blocked", "video": "", "video_blocked": blocked, "video_requested": True, "failure_reason": last_reason, "attempts": attempts}


def run(**kwargs: Any) -> dict[str, Any]:
    if kwargs.get("mode") == "video" and {"project_dir", "run_dir"}.issubset(kwargs):
        return capture_candidate_video(
            pathlib.Path(kwargs["project_dir"]),
            pathlib.Path(kwargs["run_dir"]),
            timeout=int(kwargs.get("timeout", 60)),
            explicit_requested=kwargs.get("video_requested") if isinstance(kwargs.get("video_requested"), bool) else None,
        )
    if {"project_dir", "run_dir"}.issubset(kwargs):
        return capture_candidate_screenshot(pathlib.Path(kwargs["project_dir"]), pathlib.Path(kwargs["run_dir"]), int(kwargs.get("timeout", 60)))
    return base_result(status="warning", verdict="visual_evidence_requires_project_dir_and_run_dir", metadata=dict(kwargs))


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="replaceable_module",
        metadata={
            "responsibilities": ["screenshot capture", "startup diagnostics", "pipeline static HTTP server", "UI smoke", "screenshot diagnostics", "blank image rejection", "video attempt", "video blocked", "metadata"],
            "forbidden": ["provider-faked screenshots", "provider-faked videos", "accept blank image"],
        },
    )
