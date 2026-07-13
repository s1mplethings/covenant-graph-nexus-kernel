#!/usr/bin/env python3
from __future__ import annotations

"""Legacy compact Product Studio artifact entrypoint.

This wrapper exists for historical tests and diagnostics only. It is not part of
the CGKN Telegram formal generation or delivery mainline.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legacy.run_product_studio import main


if __name__ == "__main__":
    raise SystemExit(main())
