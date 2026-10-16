from __future__ import annotations

import ast
import http.client
import json
import os
import pathlib
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager


def project_root() -> pathlib.Path:
    value = os.environ.get("CGKN_GENERATED_PROJECT", "")
    if not value:
        raise RuntimeError("generated project was not supplied")
    return pathlib.Path(value).resolve()


def run(*args: str, cwd: pathlib.Path | None = None, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CGKN_GENERATED_PROJECT", None)
    return subprocess.run([sys.executable, *args], cwd=cwd or project_root(), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, env=env)


def assert_project_hygiene() -> None:
    root = project_root()
    assert (root / "README.md").is_file()
    forbidden = ("benchmarks/real_project_generation", "CGKN_GENERATED_PROJECT", "hidden_acceptance")
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        assert not path.is_absolute() or root in path.resolve().parents
        if path.suffix in {".py", ".md", ".json", ".html", ".js", ".css"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            assert not any(token in text for token in forbidden)
            assert "TODO" not in text and "FIXME" not in text
            if path.suffix == ".py":
                assert text.strip()
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = [alias.name.split(".")[0] for alias in node.names] if isinstance(node, ast.Import) else [str(node.module or "").split(".")[0]]
                        for name in names:
                            assert name in sys.stdlib_module_names or (root / name).exists() or (root / f"{name}.py").exists(), f"undeclared dependency: {name}"


@contextmanager
def server(module: str, data_dir: pathlib.Path):
    env = os.environ.copy()
    env.pop("CGKN_GENERATED_PROJECT", None)
    process = subprocess.Popen([sys.executable, "-m", module, "--host", "127.0.0.1", "--port", "0", "--data-dir", str(data_dir)], cwd=project_root(), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line_queue: queue.Queue[str] = queue.Queue()
    assert process.stdout is not None
    threading.Thread(target=lambda: line_queue.put(process.stdout.readline()), daemon=True).start()
    try:
        line = line_queue.get(timeout=10).strip()
        match = re.fullmatch(r"LISTENING 127\.0\.0\.1:(\d+)", line)
        assert match, f"server did not declare loopback port: {line!r}"
        yield int(match.group(1))
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)


def request(port: int, method: str, path: str, body: object | None = None) -> tuple[int, object, dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    raw = None if body is None else json.dumps(body)
    headers = {} if body is None else {"Content-Type": "application/json"}
    connection.request(method, path, body=raw, headers=headers)
    response = connection.getresponse()
    data = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    parsed = json.loads(data.decode()) if data and "json" in response_headers.get("content-type", "") else data.decode(errors="replace")
    return response.status, parsed, response_headers
