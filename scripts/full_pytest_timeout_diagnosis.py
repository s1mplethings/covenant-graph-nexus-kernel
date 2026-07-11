from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tail(text: str, limit: int = 2000) -> str:
    return str(text or "")[-limit:]


def collect_test_files(tests_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in tests_dir.glob("test_*.py") if path.is_file())


def diagnose_full_pytest_timeout(
    *,
    out_dir: str | pathlib.Path,
    per_file_timeout: int = 120,
    max_total_seconds: int = 840,
    tests_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tests_root = pathlib.Path(tests_dir) if tests_dir is not None else ROOT / "tests"
    tests = collect_test_files(tests_root)
    started = time.time()
    results: list[dict[str, Any]] = []
    for path in tests:
        display_path = str(path if tests_dir is not None else path.relative_to(ROOT)).replace("\\", "/")
        elapsed_total = time.time() - started
        if elapsed_total >= max_total_seconds:
            results.append({"path": display_path, "status": "not_run_total_timeout", "duration": 0, "exit_code": None, "stdout_tail": "", "stderr_tail": ""})
            continue
        item_started = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(path), "-q"],
                cwd=ROOT if tests_dir is None else pathlib.Path(tests_dir).parent,
                capture_output=True,
                text=True,
                timeout=per_file_timeout,
                env={**dict(), **__import__("os").environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            duration = round(time.time() - item_started, 3)
            status = "pass" if proc.returncode == 0 else "fail"
            results.append({"path": display_path, "duration": duration, "exit_code": proc.returncode, "status": status, "stdout_tail": _tail(proc.stdout), "stderr_tail": _tail(proc.stderr)})
        except subprocess.TimeoutExpired as exc:
            duration = round(time.time() - item_started, 3)
            results.append({"path": display_path, "duration": duration, "exit_code": None, "status": "timeout", "stdout_tail": _tail(exc.stdout if isinstance(exc.stdout, str) else ""), "stderr_tail": _tail(exc.stderr if isinstance(exc.stderr, str) else "")})
    timeouts = [item for item in results if item["status"] == "timeout"]
    not_run = [item for item in results if item["status"] == "not_run_total_timeout"]
    slowest = sorted([item for item in results if isinstance(item.get("duration"), (int, float))], key=lambda item: item.get("duration", 0), reverse=True)[:20]
    generated_scanned = any("generated/" in item["path"] or item["path"].startswith("generated/") for item in results)
    provider_suspects = [item for item in results if any(token in item["path"].lower() for token in ("provider", "telegram", "real_", "live", "long_run")) and item["status"] in {"timeout", "not_run_total_timeout"}]
    summary = {
        "kind": "FullPytestTimeoutDiagnosis",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collected_test_files": len(tests),
        "completed_files": len([item for item in results if item["status"] not in {"not_run_total_timeout"}]),
        "timeout_files": [item["path"] for item in timeouts],
        "not_run_due_to_total_timeout": [item["path"] for item in not_run],
        "slowest_files": slowest,
        "generated_directory_scanned": generated_scanned,
        "provider_or_telegram_timeout_suspects": [item["path"] for item in provider_suspects],
        "diagnosis_verdict": "PASS" if tests and (slowest or timeouts or not_run) else "FAIL",
        "suspected_cause": "provider/telegram/long-run tests or cumulative suite size" if provider_suspects or not_run else "slow individual tests",
    }
    (out / "full_pytest_file_timings.json").write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Full Pytest File Timings", "", f"- collected test files: {len(tests)}", f"- completed files: {summary['completed_files']}", f"- timeout files: {len(timeouts)}", f"- not run due total timeout: {len(not_run)}", ""]
    for item in results:
        lines.append(f"- {item['path']}: {item['status']} ({item.get('duration', 0)}s)")
    (out / "full_pytest_file_timings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "slowest_tests.md").write_text("# Slowest Tests\n\n" + "\n".join(f"- {item['path']}: {item.get('duration', 0)}s {item['status']}" for item in slowest) + "\n", encoding="utf-8")
    (out / "timeout_tests.md").write_text("# Timeout Tests\n\n" + "\n".join(f"- {item['path']}" for item in timeouts) + ("\n" if timeouts else "- none\n"), encoding="utf-8")
    collection = subprocess.run([sys.executable, "-m", "pytest", str(tests_root), "--collect-only", "-q"], cwd=ROOT if tests_dir is None else pathlib.Path(tests_dir).parent, capture_output=True, text=True, timeout=120)
    (out / "pytest_collection_summary.txt").write_text(_tail(collection.stdout, 8000) + "\n" + _tail(collection.stderr, 4000), encoding="utf-8")
    recs = ["# Recommendations", "", f"- suspected cause: {summary['suspected_cause']}", f"- generated directory scanned: {generated_scanned}", "- keep long-running provider/Telegram tests behind explicit timeout guards or markers.", "- keep full pytest timeout reporting separate from targeted PASS reporting."]
    (out / "recommendations.md").write_text("\n".join(recs) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--per-file-timeout", type=int, default=120)
    parser.add_argument("--max-total-seconds", type=int, default=840)
    args = parser.parse_args()
    summary = diagnose_full_pytest_timeout(out_dir=args.out, per_file_timeout=args.per_file_timeout, max_total_seconds=args.max_total_seconds)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("diagnosis_verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
