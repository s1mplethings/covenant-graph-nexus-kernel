"""Minimal pytest plugin for machine-readable per-phase outcomes."""
from __future__ import annotations

import json
import os
import pathlib
import random
import threading
from datetime import datetime, timezone


_LOCK = threading.Lock()


def _path() -> pathlib.Path | None:
    raw = os.environ.get("CGKN_PYTEST_EVENT_LOG", "").strip()
    return pathlib.Path(raw).resolve() if raw else None


def _append(document: dict) -> None:
    path = _path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(document, ensure_ascii=False) + "\n")


def pytest_sessionstart(session) -> None:
    path = _path()
    if path is not None and path.exists():
        path.unlink()
    _append(
        {
            "event": "session_start",
            "at": datetime.now(timezone.utc).isoformat(),
            "python": os.sys.executable,
            "pytest_args": list(session.config.invocation_params.args),
            "plugins": sorted(
                {
                    str(name)
                    for name, _plugin in session.config.pluginmanager.list_name_plugin()
                    if name
                }
            ),
        }
    )


def pytest_collection_modifyitems(session, config, items) -> None:
    raw_seed = os.environ.get("CGKN_TEST_ORDER_SEED", "").strip()
    if raw_seed:
        random.Random(int(raw_seed)).shuffle(items)
    _append(
        {
            "event": "collection",
            "order_seed": int(raw_seed) if raw_seed else None,
            "count": len(items),
            "nodeids": [item.nodeid for item in items],
        }
    )


def pytest_deselected(items) -> None:
    _append(
        {
            "event": "deselected",
            "count": len(items),
            "nodeids": [item.nodeid for item in items],
        }
    )


def pytest_runtest_logreport(report) -> None:
    _append(
        {
            "event": "test_phase",
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "duration_seconds": float(report.duration),
            "wasxfail": str(getattr(report, "wasxfail", "") or ""),
            "longrepr": str(report.longrepr)[:12000] if report.failed else "",
        }
    )


def pytest_sessionfinish(session, exitstatus: int) -> None:
    _append(
        {
            "event": "session_finish",
            "at": datetime.now(timezone.utc).isoformat(),
            "exitstatus": int(exitstatus),
            "testscollected": int(session.testscollected),
        }
    )
