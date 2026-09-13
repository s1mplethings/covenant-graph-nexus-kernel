#!/usr/bin/env python3
"""Run candidate-only CASE01/CASE03 diagnostics through the reviewed mainline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.project_generation_v1 import evaluator, run_benchmark  # noqa: E402
from scripts import audit_failure_to_repair, provider_jobs, provider_resilience  # noqa: E402
from scripts.customer_runtime_runner import _wait_for_health  # noqa: E402


EXPECTED_BENCHMARK_HASHES = {
    "cases.json": "1DBD6AAE9DBAC9FBCB0C321DAC6A07D6DA45D8B31605EACEA127C499149C0462",
    "evaluator.py": "227E330E8BA037DE38A163631E005D29F6AD6626B0AD46582604860707E95A18",
}
BENCHMARK_PATHS = {
    "cases.json": ROOT / "benchmarks" / "project_generation_v1" / "cases.json",
    "evaluator.py": ROOT / "benchmarks" / "project_generation_v1" / "evaluator.py",
}
CASE_IDS = {
    "CASE01": "CASE_01_CSV_DATA_CLEANER",
    "CASE03": "CASE_03_LOCAL_PROJECT_BOARD",
}
FORBIDDEN_SIDE_BRANCHES = (
    "acfv",
    "commercial_readiness",
    "telegram",
    "final_promotion",
    "public_delivery",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def benchmark_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest().upper()
        for name, path in BENCHMARK_PATHS.items()
    }


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def tracked_source_snapshot() -> dict[str, str]:
    files = [line for line in _git("ls-files").splitlines() if line]
    digest = hashlib.sha256()
    for relative in files:
        path = ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {"head": _git("rev-parse", "HEAD"), "tracked_tree_sha256": digest.hexdigest()}


def provider_preflight() -> dict[str, Any]:
    return provider_resilience.provider_preflight(
        goal="trimmed CASE01 CASE03 generation and repair diagnosis",
        live=True,
        requested_model="",
        required_role="generation",
        timeout=20,
    )


def provider_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    meta = preflight.get("metadata", {}) if isinstance(preflight.get("metadata"), dict) else {}
    checked: list[dict[str, Any]] = []
    for candidate in meta.get("candidates_checked", []):
        if not isinstance(candidate, dict):
            continue
        status = str(candidate.get("status") or "")
        checked.append(
            {
                "model": str(candidate.get("model") or ""),
                "available": status == "PROVIDER_OK",
                "quota_blocked": status == "PROVIDER_QUOTA_EXCEEDED",
                "non_json_risk": not bool(candidate.get("structured_output_verified")),
                "generation_score": candidate.get("generation_capability_score"),
                "repair_score": candidate.get("repair_capability_score"),
                "selected_reason": (
                    "selected_generation"
                    if candidate.get("model") == meta.get("selected_generation_model")
                    else "selected_repair"
                    if candidate.get("model") == meta.get("selected_repair_model")
                    else "not_selected"
                ),
            }
        )
    return {
        "status": "PASS" if meta.get("live_generation_allowed") else "BLOCKED_PROVIDER",
        "selected_generation_model": str(meta.get("selected_generation_model") or meta.get("selected_model") or ""),
        "selected_repair_model": str(meta.get("selected_repair_model") or meta.get("selected_model") or ""),
        "selection_reason": str(meta.get("selection_reason") or ""),
        "capability_probe_used": bool(meta.get("capability_probe_used")),
        "candidates_checked": checked,
        "endpoint": str(meta.get("endpoint") or ""),
    }


def _first(root: pathlib.Path, name: str) -> pathlib.Path | None:
    return next((path for path in root.rglob(name) if path.is_file()), None)


def _latest(root: pathlib.Path, pattern: str) -> pathlib.Path | None:
    paths = [path for path in root.rglob(pattern) if path.is_file()]
    return max(paths, key=lambda item: item.stat().st_mtime_ns) if paths else None


def route_methods(candidate: pathlib.Path) -> dict[str, set[str]]:
    routes: dict[str, set[str]] = {}
    for path in candidate.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r"@[A-Za-z_][A-Za-z0-9_]*\.(route|get|post|put|patch|delete)\(\s*['\"]([^'\"]+)[^)]*\)",
            text,
            flags=re.I | re.S,
        ):
            method, route = match.group(1).lower(), match.group(2)
            decorator = match.group(0)
            declared = {method.upper()} if method != "route" else set(re.findall(r"['\"](GET|POST|PUT|PATCH|DELETE)['\"]", decorator, flags=re.I))
            routes.setdefault(route, set()).update(item.upper() for item in (declared or {"GET"}))
    return routes


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def server_command(candidate: pathlib.Path, port: int) -> tuple[list[str], str]:
    sources = [candidate / "app" / "main.py", candidate / "app.py", candidate / "main.py"]
    for source in sources:
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        relative_source = source.relative_to(candidate).as_posix()
        module = source.relative_to(candidate).with_suffix("").as_posix().replace("/", ".")
        if re.search(r"\bFlask\b|\bfrom\s+flask\b", text):
            return [sys.executable, "-m", "flask", "--app", f"{relative_source}:app", "run", "--host", "127.0.0.1", "--port", str(port)], "flask"
        if re.search(r"\bFastAPI\b|\bfrom\s+fastapi\b", text):
            return [sys.executable, "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", str(port)], "fastapi"
        return [sys.executable, str(source.relative_to(candidate))], "python"
    static_root = candidate / "frontend" if (candidate / "frontend" / "index.html").is_file() else candidate
    if (static_root / "index.html").is_file():
        return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(static_root)], "static"
    return [], "unsupported"


def http_request(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - localhost-only debug probe
            body = response.read()
            return {"status": int(response.status), "content_type": str(response.headers.get("Content-Type") or ""), "body": body}
    except urllib.error.HTTPError as exc:
        return {"status": int(exc.code), "content_type": str(exc.headers.get("Content-Type") or ""), "body": exc.read()}
    except Exception as exc:
        return {"status": 0, "content_type": "", "body": str(exc).encode("utf-8", errors="replace")}


def multipart_csv(csv_text: str) -> tuple[bytes, str]:
    boundary = "----cgkn-trimmed-debug"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sample.csv\"\r\n"
        "Content-Type: text/csv\r\n\r\n"
        f"{csv_text}\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def _json_body(response: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(bytes(response.get("body") or b"").decode("utf-8", errors="replace"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _short_response(response: dict[str, Any]) -> str:
    body = bytes(response.get("body") or b"").decode("utf-8", errors="replace")
    return f"HTTP {response.get('status')}; content_type={response.get('content_type')}; body={body[:700]}"


def _behavior(name: str, expected: str, observed: str, passed: bool) -> dict[str, Any]:
    return {
        "behavior": name,
        "expected": expected,
        "observed": observed,
        "pass": bool(passed),
        "mapped_issue": "",
        "provider_job_created": False,
        "provider_called": False,
        "delta_returned": False,
        "delta_accepted": False,
        "why_not_fixed": "" if passed else "failure_not_detected",
    }


def probe_case01(candidate: pathlib.Path) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    port = _free_port()
    routes = route_methods(candidate)
    command, mode = server_command(candidate, port)
    if not command:
        failed = _behavior("static_root", "GET / returns an interactive CSV page.", "No supported startup entrypoint.", False)
        return [
            failed,
            _behavior("csv_upload", "A CSV upload is accepted.", "Server did not start.", False),
            _behavior("clean_preview", "Response contains before/after cleaning evidence.", "Server did not start.", False),
            _behavior("export_csv", "A persisted, readable CSV can be downloaded.", "Server did not start.", False),
        ], {"missing": False, "malformed": False}
    process = subprocess.Popen(command, cwd=candidate, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready_path = "/health" if "/health" in routes else "/"
        ready_code, ready_body = _wait_for_health(f"http://127.0.0.1:{port}{ready_path}")
        root = http_request(f"http://127.0.0.1:{port}/") if ready_code else {"status": 0, "content_type": "", "body": ready_body.encode()}
        root_pass = root.get("status") == 200 and bool(bytes(root.get("body") or b"").strip())
        records = [_behavior("static_root", "GET / returns an interactive CSV page.", f"mode={mode}; command={' '.join(command)}; {_short_response(root)}", root_pass)]

        upload_route = next((path for path in ("/api/upload", "/upload", "/api/process", "/api/clean", "/clean") if "POST" in routes.get(path, set())), "")
        sample = "name,email\nAlice,a@example.test\nAlice,a@example.test\nBob,\nCarol,c@example.test\n"
        upload: dict[str, Any]
        if upload_route and ready_code:
            body, content_type = multipart_csv(sample)
            upload = http_request(
                f"http://127.0.0.1:{port}{upload_route}",
                method="POST",
                data=body,
                headers={"Content-Type": content_type},
            )
        else:
            upload = {"status": 0, "content_type": "", "body": b"no POST upload/clean route"}
        upload_doc = _json_body(upload)
        upload_pass = 200 <= int(upload.get("status") or 0) < 300 and bool(upload_doc)
        records.append(_behavior("csv_upload", "A multipart CSV upload returns structured data.", f"route={upload_route or 'missing'}; {_short_response(upload)}", upload_pass))

        lower_keys = {str(key).lower() for key in upload_doc}
        stats = upload_doc.get("stats", {}) if isinstance(upload_doc.get("stats"), dict) else {}
        preview = upload_doc.get("preview") or upload_doc.get("cleaned_preview") or upload_doc.get("after_preview")
        before_present = bool({"before", "before_preview", "original", "original_preview", "raw_preview"} & lower_keys)
        after_present = bool(preview) or bool({"after", "after_preview", "cleaned", "cleaned_preview"} & lower_keys)
        difference_present = before_present and after_present
        records.append(
            _behavior(
                "clean_preview",
                "The clean response exposes both pre-clean and post-clean previews.",
                f"response_keys={sorted(lower_keys)}; stats={stats}; before_present={before_present}; after_present={after_present}",
                upload_pass and difference_present,
            )
        )

        export_route = next((path for path in ("/api/export", "/export", "/download") if "POST" in routes.get(path, set()) or "GET" in routes.get(path, set())), "")
        export_payload = json.dumps({"data": preview if isinstance(preview, list) else []}).encode("utf-8")
        export = (
            http_request(
                f"http://127.0.0.1:{port}{export_route}",
                method="POST" if "POST" in routes.get(export_route, set()) else "GET",
                data=export_payload if "POST" in routes.get(export_route, set()) else None,
                headers={"Content-Type": "application/json"},
            )
            if export_route and ready_code
            else {"status": 0, "content_type": "", "body": b"no export route"}
        )
        persisted = False
        if 200 <= int(export.get("status") or 0) < 300 and bytes(export.get("body") or b"").strip():
            with tempfile.TemporaryDirectory(prefix="cgkn_trimmed_export_") as temp_dir:
                exported = pathlib.Path(temp_dir) / "cleaned.csv"
                exported.write_bytes(bytes(export.get("body") or b""))
                persisted = exported.read_text(encoding="utf-8", errors="replace").count("\n") >= 1
        export_pass = persisted and "csv" in str(export.get("content_type") or "").lower()
        records.append(_behavior("export_csv", "Export returns a CSV that remains readable after persistence.", f"route={export_route or 'missing'}; persisted={persisted}; {_short_response(export)}", export_pass))
        return records, {
            "missing": bool(stats.get("raw_nulls") or stats.get("missing_values")),
            "malformed": bool(stats.get("malformed_rows")),
        }
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def dom_alignment(candidate: pathlib.Path) -> dict[str, Any]:
    html_path = candidate / "frontend" / "index.html"
    js_path = candidate / "frontend" / "app.js"
    if not html_path.is_file() or not js_path.is_file():
        return {"status": "NOT_EVALUATED", "missing_ids": [], "reason": "frontend/index.html or frontend/app.js missing"}
    html = html_path.read_text(encoding="utf-8", errors="replace")
    js = js_path.read_text(encoding="utf-8", errors="replace")
    html_ids = set(re.findall(r"\bid=['\"]([^'\"]+)", html))
    js_ids = set(re.findall(r"getElementById\(['\"]([^'\"]+)", js))
    js_ids.update(re.findall(r"querySelector\(['\"]#([^'\"]+)", js))
    missing = sorted(js_ids - html_ids)
    return {"status": "PASS" if js_ids and not missing else "FAIL", "missing_ids": missing, "html_ids": sorted(html_ids), "js_ids": sorted(js_ids)}


def probe_case03(candidate: pathlib.Path) -> dict[str, Any]:
    port = _free_port()
    routes = route_methods(candidate)
    command, mode = server_command(candidate, port)
    startup: dict[str, Any]
    if not command:
        startup = {"status": "NOT_EVALUATED", "reason": "no supported startup entrypoint"}
    else:
        process = subprocess.Popen(command, cwd=candidate, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready_path = "/health" if "/health" in routes else "/"
            ready_code, ready_body = _wait_for_health(f"http://127.0.0.1:{port}{ready_path}")
            root = http_request(f"http://127.0.0.1:{port}/") if ready_code else {"status": 0, "content_type": "", "body": ready_body.encode()}
            startup = {"status": "PASS" if root.get("status") == 200 else "FAIL", "mode": mode, "observed": _short_response(root)}
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
    return {"startup_static_root": startup, "dom_alignment": dom_alignment(candidate)}


BEHAVIOR_ALIASES = {
    "static_root": ("static root", "startup", "root route", "404", "route:/"),
    "csv_upload": ("upload", "csv import", "import_csv"),
    "clean_preview": ("clean", "preview", "missing value", "duplicate"),
    "export_csv": ("export", "download", "csv_bytes"),
}


def link_behavior_to_repair(case_run: pathlib.Path, record: dict[str, Any]) -> dict[str, Any]:
    artifacts = [read_json(path) for path in case_run.rglob("post_build_issue_ledger*.json")]
    issues = [row for doc in artifacts for row in doc.get("issues", []) if isinstance(row, dict)]
    unique_issues = {str(row.get("issue_id") or ""): row for row in issues if row.get("issue_id")}
    aliases = BEHAVIOR_ALIASES.get(str(record.get("behavior") or ""), ())
    matched = [row for row in unique_issues.values() if any(alias in json.dumps(row, ensure_ascii=False).lower() for alias in aliases)]
    issue_ids = {str(row.get("issue_id") or "") for row in matched}
    plans = [read_json(path) for path in case_run.rglob("post_build_repair_plan_attempt_*.json")]
    jobs: list[dict[str, Any]] = []
    for plan in plans:
        for key in ("provider_actions", "repair_bundles"):
            jobs.extend(row for row in plan.get(key, []) if isinstance(row, dict) and issue_ids.intersection(str(item) for item in row.get("issue_ids", [])))
    accounting = read_json(_latest(case_run, "repair_call_accounting.json"))
    decisions = [row for row in accounting.get("rows", []) if isinstance(row, dict) and issue_ids.intersection(str(item) for item in row.get("issue_ids", []))]
    called = bool(decisions)
    returned = any(int(row.get("provider_calls_in_batch", 0) or 0) > 0 for row in decisions)
    accepted = any(bool(row.get("issue_level_acceptance") or row.get("accepted")) for row in decisions)
    if record.get("pass"):
        why = ""
    elif not matched:
        why = "failure_not_mapped"
    elif not jobs:
        why = "issue_no_provider_job"
    elif not returned:
        why = "provider_job_no_delta"
    elif not accepted:
        reasons = sorted({str(row.get("pre_acceptance_failure") or row.get("rejection_reason") or "delta_rejected") for row in decisions})
        why = "delta_rejected:" + ",".join(reasons)
    else:
        why = "provider_patch_wrong"
    return {
        **record,
        "mapped_issue": ",".join(sorted(issue_ids)),
        "provider_job_created": bool(jobs),
        "provider_called": called,
        "delta_returned": returned,
        "delta_accepted": accepted,
        "why_not_fixed": why,
    }


def semantic_handoff_diagnosis(production: dict[str, Any], case_run: pathlib.Path) -> dict[str, Any]:
    diagnostics = production.get("diagnostics", {}) if isinstance(production.get("diagnostics"), dict) else {}
    blockers = [str(item) for item in diagnostics.get("blockers", [])]
    selenium = next((item for item in blockers if "selenium" in item.lower()), "")
    candidate_materialized = bool(production.get("candidate_materialized"))
    ledger = _latest(case_run, "post_build_issue_ledger*.json")
    plan = _latest(case_run, "post_build_repair_plan_attempt_*.json")
    fatal = [str(item) for item in production.get("fatal_fact_blockers", [])]
    repairable = [str(item) for item in production.get("repairable_fact_blockers", [])]
    return {
        "candidate_materialized": candidate_materialized,
        "blocked_stage": str(diagnostics.get("stage") or ("" if candidate_materialized else production.get("reason") or "unknown")),
        "blocked_reason": selenium or "; ".join(blockers[:3]) or str(production.get("why_project_dir_was_not_materialized") or ""),
        "fatal_or_repairable": "repairable" if selenium and not fatal else "fatal_materialization_block" if fatal else "not_blocked",
        "should_have_materialized_with_warning": bool(selenium and not fatal and repairable),
        "semantic_violation_repairable": bool(selenium and not fatal),
        "issue_created": ledger is not None,
        "provider_job_created": plan is not None,
        "reached_post_build_issue_ledger": ledger is not None,
    }


def make_case01_observations(case: dict[str, Any], run_id: str, candidate: pathlib.Path, records: list[dict[str, Any]], extra: dict[str, bool]) -> list[dict[str, Any]]:
    by_name = {str(row["behavior"]): row for row in records}
    candidate_hash = evaluator.candidate_tree_hash(candidate)
    mapping = {
        "csv.runtime": (by_name["static_root"]["pass"], "benchmark_http_probe", by_name["static_root"]["observed"], ["R1"]),
        "csv.clean": (by_name["csv_upload"]["pass"], "benchmark_http_probe", by_name["csv_upload"]["observed"], ["R1", "R2", "R3"]),
        "csv.preview": (by_name["clean_preview"]["pass"], "benchmark_http_probe", by_name["clean_preview"]["observed"], ["R4"]),
        "csv.persist": (by_name["export_csv"]["pass"], "benchmark_persistence_probe", by_name["export_csv"]["observed"], ["R5"]),
        "csv.integration": (all(row["pass"] for row in records), "benchmark_http_probe", json.dumps(records, ensure_ascii=False), ["R2", "R4", "R5"]),
        "csv.missing": (extra["missing"], "benchmark_http_probe", f"missing_detected={extra['missing']}", ["R3"]),
        "csv.malformed": (extra["malformed"], "benchmark_http_probe", f"malformed_detected={extra['malformed']}", ["R6"]),
    }
    return [
        evaluator.make_observation(
            case_id=str(case["case_id"]),
            run_id=run_id,
            candidate_sha256=candidate_hash,
            criterion_id=criterion,
            status="PASS" if passed else "FAIL",
            producer=producer,
            details=details,
            requirement_ids=requirements,
        )
        for criterion, (passed, producer, details, requirements) in mapping.items()
    ]


def scan_side_branches(run_root: pathlib.Path) -> list[str]:
    findings: list[str] = []
    for phase_log in run_root.rglob("provider_phase_log.jsonl"):
        for line in phase_log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            identity = " ".join(str(event.get(key) or "") for key in ("event", "phase", "stage")).strip()
            if any(marker in identity.lower() for marker in FORBIDDEN_SIDE_BRANCHES):
                findings.append(f"phase:{identity}")
    for path in run_root.rglob("*"):
        if not path.is_file() or "candidate" in {part.lower() for part in path.parts}:
            continue
        relative = path.relative_to(run_root).as_posix().lower()
        if path.name in {"final_project_bundle.zip", "delivery_manifest.json"} or any(marker in relative for marker in FORBIDDEN_SIDE_BRANCHES):
            findings.append(f"artifact:{relative}")
    return sorted(set(findings))


def execute(args: argparse.Namespace) -> tuple[pathlib.Path, dict[str, Any]]:
    if not args.live:
        raise ValueError("--live is required; this runner never substitutes mock output")
    before_source = tracked_source_snapshot()
    before_hashes = benchmark_hashes()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("CGKN_TRIMMED_CASE_DEBUG_%Y%m%dT%H%M%SZ")
    run_root = args.output_root.resolve() / run_id
    if run_root.exists():
        raise FileExistsError(f"trimmed debug run already exists: {run_root}")
    run_root.mkdir(parents=True)
    preflight = provider_preflight()
    provider = provider_summary(preflight)
    write_json(run_root / "provider_preflight.json", preflight)
    report: dict[str, Any] = {
        "kind": "CGKNTrimmedCaseDebugReport",
        "schema_version": "1.0",
        "profile": "trimmed_case_debug",
        "created_at": utc_now(),
        "head": before_source["head"],
        "source_snapshot_before": before_source,
        "benchmark_hash_before": before_hashes,
        "benchmark_hash_expected": EXPECTED_BENCHMARK_HASHES,
        "provider_auto_select": provider,
        "cases": {},
        "forbidden_branches": list(FORBIDDEN_SIDE_BRANCHES),
        "manual_candidate_patch": False,
        "provider_execution_path": "existing production split-file leaf executor",
    }
    report_path = run_root / "trimmed_debug_report.json"
    if before_hashes != EXPECTED_BENCHMARK_HASHES:
        report.update(status="BENCHMARK_HASH_MISMATCH", unexpected_side_branch_called=False)
        write_json(report_path, report)
        return report_path, report
    if provider["status"] != "PASS":
        report.update(status="BLOCKED_PROVIDER", unexpected_side_branch_called=False)
        write_json(report_path, report)
        return report_path, report

    catalog = evaluator.load_case_catalog(BENCHMARK_PATHS["cases.json"])
    selected_ids = {CASE_IDS[name.upper()] for name in args.cases}
    selected = [case for case in catalog["cases"] if case["case_id"] in selected_ids]
    prior_profile = os.environ.get("CGNK_PROFILE")
    prior_repair_model = os.environ.get("CGKN_PROVIDER_REPAIR_MODEL")
    os.environ["CGNK_PROFILE"] = "trimmed_case_debug"
    os.environ["CGKN_PROVIDER_REPAIR_MODEL"] = provider["selected_repair_model"]
    try:
        for case in selected:
            case_id = str(case["case_id"])
            case_run_id = f"{run_id}_{case_id}"
            case_run = run_root / "case_runs" / case_id
            case_dir = case_run / "cases" / case_id
            case_dir.mkdir(parents=True)
            production_args = run_benchmark.build_parser().parse_args(
                [
                    "--case",
                    "01" if "CASE_01" in case_id else "03",
                    "--run-id",
                    case_run_id,
                    "--output-root",
                    str(run_root),
                    "--model",
                    provider["selected_generation_model"],
                    "--parallelism",
                    str(provider_jobs.configured_parallelism()),
                ]
            )
            candidate, provider_error, metrics = run_benchmark.invoke_production(
                case,
                run_dir=case_run,
                case_dir=case_dir,
                args=production_args,
            )
            production = read_json(_first(case_run / "production_slots", "production_result.json"))
            observations: list[dict[str, Any]] = []
            behavior_records: list[dict[str, Any]] = []
            case_payload: dict[str, Any] = {
                "score": None,
                "candidate_materialized": candidate.is_dir(),
                "production_return_code": metrics.get("production_return_code"),
                "provider_calls": metrics.get("provider_api_calls"),
            }
            if case_id == CASE_IDS["CASE01"] and candidate.is_dir():
                behavior_records, extra = probe_case01(candidate)
                behavior_records = [link_behavior_to_repair(case_run, row) for row in behavior_records]
                observations = make_case01_observations(case, case_run_id, candidate, behavior_records, extra)
                case_payload["behaviors"] = behavior_records
            elif case_id == CASE_IDS["CASE03"]:
                semantic = semantic_handoff_diagnosis(production, case_run)
                case_payload.update(semantic)
                if candidate.is_dir():
                    case_payload.update(probe_case03(candidate))
                    case_payload["crud_move_persistence_export"] = {
                        "status": "DIAGNOSED_BY_POST_BUILD_ISSUE_LEDGER",
                        "issue_ledger": str(_latest(case_run, "post_build_issue_ledger*.json") or ""),
                    }
                else:
                    case_payload.update(
                        startup_static_root={"status": "NOT_EVALUATED", "reason": "candidate_not_materialized"},
                        dom_alignment={"status": "NOT_EVALUATED", "reason": "candidate_not_materialized"},
                        crud_move_persistence_export={"status": "NOT_EVALUATED", "reason": "candidate_not_materialized"},
                    )
            result = evaluator.evaluate_case(
                case,
                run_id=case_run_id,
                candidate_dir=candidate,
                observations=observations,
                metrics=metrics,
                provider_error=provider_error,
                require_repair=False,
            )
            evaluator.write_json(case_dir / "case_result.json", result)
            evaluator.write_json(case_dir / "evidence" / "external_observations.json", {"observations": observations})
            case_payload.update(
                score=result.get("score"),
                final_status=result.get("result"),
                hard_failures=result.get("hard_failures", []),
                criteria_not_evaluated=result.get("criteria_not_evaluated", []),
                failure_to_repair_audit=audit_failure_to_repair.audit_case(case_run),
            )
            report["cases"][case_id] = case_payload
    finally:
        if prior_profile is None:
            os.environ.pop("CGNK_PROFILE", None)
        else:
            os.environ["CGNK_PROFILE"] = prior_profile
        if prior_repair_model is None:
            os.environ.pop("CGKN_PROVIDER_REPAIR_MODEL", None)
        else:
            os.environ["CGKN_PROVIDER_REPAIR_MODEL"] = prior_repair_model

    after_source = tracked_source_snapshot()
    after_hashes = benchmark_hashes()
    side_branches = scan_side_branches(run_root)
    report.update(
        status="COMPLETE",
        source_snapshot_after=after_source,
        source_change_during_run=before_source != after_source,
        benchmark_hash_after=after_hashes,
        benchmark_hash_unchanged=before_hashes == after_hashes == EXPECTED_BENCHMARK_HASHES,
        unexpected_side_branch_called=bool(side_branches),
        unexpected_side_branch_findings=side_branches,
    )
    write_json(report_path, report)
    return report_path, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=sorted(CASE_IDS), default=list(CASE_IDS))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--output-root",
        type=pathlib.Path,
        default=ROOT / "artifacts" / "project_generation_benchmark",
    )
    return parser


def main() -> int:
    try:
        report_path, report = execute(build_parser().parse_args())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": report.get("status"), "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
