from __future__ import annotations

import subprocess
import sys
import time


def test_cold_core_import_completes_within_generous_regression_budget() -> None:
    started = time.perf_counter()
    completed = subprocess.run([sys.executable, "-c", "import cgkn.artifacts, cgkn.component, cgkn.execution, cgkn.runtime, cgkn.state"], check=False, capture_output=True, text=True, timeout=10)
    elapsed = time.perf_counter() - started
    assert completed.returncode == 0, completed.stderr
    assert elapsed < 5.0


def test_core_import_does_not_start_network_or_background_threads() -> None:
    code = "import threading; before=len(threading.enumerate()); import cgkn.artifacts,cgkn.runtime; after=len(threading.enumerate()); print(after-before)"
    completed = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "0"
