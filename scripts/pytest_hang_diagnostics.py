#!/usr/bin/env python3
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
DEFAULT_REPORT = ROOT / "artifacts" / "pytest_hang_diagnostics.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_nodes(pytest_args: list[str] | None = None, *, timeout: int = 60) -> list[str]:
    argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", *(pytest_args or [])]
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    nodes = [line.strip() for line in proc.stdout.splitlines() if "::" in line]
    return nodes


def run_node(node: str, *, timeout: int) -> dict[str, Any]:
    started = now()
    start = time.time()
    argv = [sys.executable, "-m", "pytest", node, "-q"]
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        duration = round(time.time() - start, 3)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        return {
            "nodeid": node,
            "status": status,
            "returncode": proc.returncode,
            "started_at": started,
            "ended_at": now(),
            "duration_seconds": duration,
            "timeout_seconds": timeout,
            "stdout_tail": proc.stdout[-3000:],
            "stderr_tail": proc.stderr[-3000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "nodeid": node,
            "status": "TIMEOUT",
            "returncode": None,
            "started_at": started,
            "ended_at": now(),
            "duration_seconds": round(time.time() - start, 3),
            "timeout_seconds": timeout,
            "stdout_tail": (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-3000:] if isinstance(exc.stderr, str) else "",
        }


def diagnose(
    *,
    start: int = 1,
    end: int | None = None,
    per_test_timeout: int = 30,
    stop_on_timeout: bool = True,
    pytest_args: list[str] | None = None,
) -> dict[str, Any]:
    nodes = collect_nodes(pytest_args)
    start_index = max(1, int(start or 1))
    end_index = min(len(nodes), int(end or len(nodes)))
    selected = nodes[start_index - 1 : end_index]
    results: list[dict[str, Any]] = []
    blocked: dict[str, Any] | None = None
    for offset, node in enumerate(selected, start=start_index):
        result = run_node(node, timeout=per_test_timeout)
        result["index"] = offset
        results.append(result)
        if result["status"] == "TIMEOUT":
            blocked = result
            if stop_on_timeout:
                break
    status = "BLOCKED" if blocked else ("FAIL" if any(item["status"] == "FAIL" for item in results) else "PASS")
    return {
        "created_at": now(),
        "status": status,
        "total_collected": len(nodes),
        "range": {"start": start_index, "end": end_index},
        "per_test_timeout_seconds": per_test_timeout,
        "blocked_test": blocked,
        "last_result": results[-1] if results else None,
        "results": results,
    }


def markdown_report(result: dict[str, Any]) -> str:
    blocked = result.get("blocked_test") or {}
    lines = [
        "# Pytest Hang Diagnostics",
        "",
        f"- status: `{result.get('status')}`",
        f"- total_collected: `{result.get('total_collected')}`",
        f"- range: `{result.get('range', {}).get('start')}-{result.get('range', {}).get('end')}`",
        f"- per_test_timeout_seconds: `{result.get('per_test_timeout_seconds')}`",
        "",
    ]
    if blocked:
        lines.extend(
            [
                "## Blocked Test",
                f"- index: `{blocked.get('index')}`",
                f"- nodeid: `{blocked.get('nodeid')}`",
                f"- duration_seconds: `{blocked.get('duration_seconds')}`",
                f"- external_dependency: `not detected by diagnostics; inspect test body and subprocess output`",
                "",
            ]
        )
    last = result.get("last_result") or {}
    if last:
        lines.extend(["## Last Result", f"- index: `{last.get('index')}`", f"- nodeid: `{last.get('nodeid')}`", f"- status: `{last.get('status')}`", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=0)
    parser.add_argument("--per-test-timeout", type=int, default=30)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--markdown-report", default=str(ROOT / "artifacts" / "pytest_hang_diagnostics.md"))
    parser.add_argument("--continue-on-timeout", action="store_true")
    args, pytest_args = parser.parse_known_args()
    result = diagnose(
        start=args.start,
        end=args.end or None,
        per_test_timeout=args.per_test_timeout,
        stop_on_timeout=not args.continue_on_timeout,
        pytest_args=pytest_args,
    )
    report = pathlib.Path(args.report)
    write_json(report, result)
    pathlib.Path(args.markdown_report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.markdown_report).write_text(markdown_report(result) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["status"] == "BLOCKED" else (1 if result["status"] == "FAIL" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
