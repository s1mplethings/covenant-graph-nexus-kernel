from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from scripts import refresh_local_codex_plugin as deployment


def make_plugin(root: pathlib.Path, *, version: str, server: str) -> pathlib.Path:
    plugin = root / "plugin"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "cgkn", "version": version}), encoding="utf-8"
    )
    (plugin / "scripts" / "cgkn_mcp_server.py").write_text(server, encoding="utf-8")
    return plugin


def test_p01_p03_identical_package_reuses_verified_cache(tmp_path: pathlib.Path) -> None:
    source = make_plugin(tmp_path / "source", version="1.0.0+build.2", server="generation_job = True\n")
    installed = tmp_path / "cache" / "personal" / "cgkn" / "1.0.0+build.2"
    installed.parent.mkdir(parents=True)
    installed.mkdir()
    for path in source.rglob("*"):
        if path.is_file():
            target = installed / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    result = deployment.refresh(source=source, cache_root=tmp_path / "cache", codex=tmp_path / "codex",
                                runner=lambda _argv: pytest.fail("identical package must not reinstall"))
    assert result["changed"] is False


def test_p02_p04_changed_package_uses_cli_and_exposes_managed_server(tmp_path: pathlib.Path) -> None:
    source = make_plugin(tmp_path / "source", version="1.0.0+build.3", server="generation_job = True\n")
    cache = tmp_path / "cache"
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        if "add" in argv:
            installed = cache / "personal" / "cgkn" / "1.0.0+build.3"
            for path in source.rglob("*"):
                if path.is_file():
                    target = installed / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    result = deployment.refresh(source=source, cache_root=cache, codex=tmp_path / "codex", runner=runner)
    assert result["changed"] is True
    assert [call[2] for call in calls] == ["add"]
    assert "generation_job" in (pathlib.Path(result["installed_root"]) / "scripts" / "cgkn_mcp_server.py").read_text()


def test_p05_p08_manifest_and_runtime_identity_are_safe_and_distinguishable() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "plugins/cgkn/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
    server = (root / "plugins/cgkn/scripts/cgkn_mcp_server.py").read_text(encoding="utf-8")
    assert manifest["version"] == "0.2.0-rc.3+codex.20261026080000"
    assert 'artifacts["runtime_identity"]' in server
    assert "server_sha256" in server and "repository_revision" in server
    assert "API_KEY" not in json.dumps(manifest)


def test_p06_p07_package_digest_ignores_runtime_bytecode_and_does_not_touch_task_state(tmp_path: pathlib.Path) -> None:
    source = make_plugin(tmp_path, version="1.0.0+build.4", server="generation_job = True\n")
    before = deployment.package_digest(source)
    pycache = source / "scripts" / "__pycache__"
    pycache.mkdir()
    (pycache / "server.pyc").write_bytes(b"runtime")
    assert deployment.package_digest(source) == before
    assert not (source / ".cgkn").exists()
