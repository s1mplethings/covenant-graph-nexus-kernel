#!/usr/bin/env python3
"""Name-stable CLI facade for the existing complexity-scale benchmark.

This module adds no generation or scheduling path; it delegates directly to the
reviewed ACFV/complexity-scale benchmark implementation.
"""

from __future__ import annotations

try:
    from .run_complexity_scale_benchmark import main
except ImportError:  # pragma: no cover - direct script execution
    from run_complexity_scale_benchmark import main


if __name__ == "__main__":
    raise SystemExit(main())
