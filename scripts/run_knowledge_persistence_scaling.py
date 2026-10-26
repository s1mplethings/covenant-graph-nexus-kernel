from __future__ import annotations

import pathlib
import runpy
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
profile = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else "baseline"
module = {"alternatives": "alternatives.py", "workloads": "workloads.py"}.get(profile, "runner.py")
runpy.run_path(str(ROOT / "benchmarks" / "knowledge_persistence_scaling" / module), run_name="__main__")

