from __future__ import annotations

import json
import os
import pathlib
from typing import Any


def write_checkpoint(run_dir: pathlib.Path, checkpoint: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(run_dir) / "checkpoints" / f"{checkpoint['nodeId']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path
