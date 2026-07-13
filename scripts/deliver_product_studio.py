#!/usr/bin/env python3
from __future__ import annotations

"""Legacy compact Product Studio delivery entrypoint.

This wrapper exists for historical tests and diagnostics only. It cannot create
a formal CGKN delivery success; the formal delivery exit remains local_packager.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legacy.deliver_product_studio import *  # noqa: F401,F403
from legacy.deliver_product_studio import main


if __name__ == "__main__":
    raise SystemExit(main())
