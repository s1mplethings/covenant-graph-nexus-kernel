from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.knowledge_persistence_productionization.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
