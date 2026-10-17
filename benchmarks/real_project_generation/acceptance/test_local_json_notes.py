from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ["CGKN_GENERATED_PROJECT"]).resolve()


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "notes", *args], cwd=cwd, env=env, text=True, capture_output=True, timeout=10)


def test_hidden_stateful_contract(tmp_path: Path):
    assert run(tmp_path, "add", "hello world").stdout == "1\n"
    assert run(tmp_path, "add", "tagged", "--tag", "work").stdout == "2\n"
    assert run(tmp_path, "list").stdout == "1\thello world\t\n2\ttagged\twork\n"
    assert run(tmp_path, "list", "--tag", "work").stdout == "2\ttagged\twork\n"
    assert run(tmp_path, "show", "2").stdout == "2\ttagged\twork\n"
    assert run(tmp_path, "delete", "1").stdout == "deleted 1\n"
    assert run(tmp_path, "add", "third").stdout == "3\n"
    assert run(tmp_path, "list").stdout == "2\ttagged\twork\n3\tthird\t\n"
    state = json.loads((tmp_path / "notes.json").read_text(encoding="utf-8"))
    assert "1" not in json.dumps(state) and "3" in json.dumps(state)


def test_hidden_errors_and_help(tmp_path: Path):
    for args in (("show", "99"), ("delete", "99"), ("show", "not-an-id")):
        result = run(tmp_path, *args)
        assert result.returncode != 0 and result.stderr.strip()
    help_result = run(tmp_path, "--help")
    assert help_result.returncode == 0
    for command in ("add", "list", "show", "delete"):
        assert command in help_result.stdout


def test_hidden_assets_and_boundaries():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in ("python -m notes", "add", "list", "show", "delete", "--tag"):
        assert text in readme
    assert any((ROOT / "tests").glob("test_*.py"))
    forbidden = {"requests", "httpx", "aiohttp", "socket", "urllib", "pytest"}
    for path in (ROOT / "notes").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not imports & forbidden
