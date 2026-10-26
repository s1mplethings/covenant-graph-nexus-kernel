from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class Collector:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def pytest_collection_modifyitems(self, items) -> None:
        self.items = [
            {"nodeid": item.nodeid.replace("\\", "/"), "markers": sorted({marker.name for marker in item.iter_markers()})}
            for item in items
        ]


def collect() -> dict[str, object]:
    plugin = Collector()
    stdout = io.StringIO(); stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = int(pytest.main(["--collect-only", "-q", "tests"], plugins=[plugin]))
    return {"kind": "CGKNKernelTestMetadata", "schema_version": "1.0", "exit_code": exit_code, "tests": plugin.items, "diagnostics": (stdout.getvalue() + stderr.getvalue())[-4000:]}


def main() -> int:
    value = collect()
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value["exit_code"] in {0, 5} else 1


if __name__ == "__main__":
    raise SystemExit(main())
