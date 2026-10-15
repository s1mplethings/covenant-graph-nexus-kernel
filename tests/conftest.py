from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRESS_PATH = ROOT / "artifacts" / "pytest_progress.jsonl"
DEFAULT_SKIPPED_MARKERS = (
    "slow",
    "longrun",
    "long_journey",
    "provider",
    "live_provider",
    "codex",
    "e2e",
    "benchmark",
)


@pytest.fixture(autouse=True)
def _isolate_process_global_provider_adapter() -> Any:
    """Prevent one non-live Provider test from redirecting later live tests.

    The executable scripts intentionally retain adapter context across calls so
    a single process can resume a run.  A pytest process, however, executes
    unrelated runs in the same interpreter.  Clear every loaded import spelling
    at test boundaries while preserving resume behavior inside each test.
    """
    module_names = ("surrogate_provider_adapter", "scripts.surrogate_provider_adapter")
    previous = {
        name: getattr(sys.modules[name], "_CONTEXT", None)
        for name in module_names
        if name in sys.modules
    }
    for name in module_names:
        module = sys.modules.get(name)
        if module is not None:
            module._CONTEXT = None
    yield
    for name in module_names:
        module = sys.modules.get(name)
        if module is not None:
            module._CONTEXT = previous.get(name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_progress(record: dict[str, Any]) -> None:
    if os.environ.get("CGKN_PYTEST_PROGRESS", "1").lower() in {"0", "false", "no"}:
        return
    try:
        PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROGRESS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return


def pytest_sessionstart(session: Any) -> None:
    _write_progress({"event": "session_start", "created_at": _now(), "root": str(ROOT)})


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--run-profile-marked",
        action="store_true",
        default=False,
        help="Run tests excluded from the default fast verification profile.",
    )


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    import pytest

    if config.getoption("--run-profile-marked") or os.environ.get("CGKN_INCLUDE_PROFILE_MARKS", "").lower() in {"1", "true", "yes"}:
        return
    skip = pytest.mark.skip(reason="profile-marked test skipped by default; use scripts/run_test_profile.py or --run-profile-marked")
    for item in items:
        if any(item.get_closest_marker(marker) for marker in DEFAULT_SKIPPED_MARKERS):
            item.add_marker(skip)


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    file_path, line, test_name = location
    _write_progress({"event": "test_start", "created_at": _now(), "nodeid": nodeid, "file": file_path, "line": line, "test_name": test_name})


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    file_path, line, test_name = location
    _write_progress({"event": "test_finish", "created_at": _now(), "nodeid": nodeid, "file": file_path, "line": line, "test_name": test_name})


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    _write_progress({"event": "session_finish", "created_at": _now(), "exitstatus": int(exitstatus)})
