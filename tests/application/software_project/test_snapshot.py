import pytest

from cgkn.application.software_project.snapshot import snapshot_project


@pytest.mark.happy_path
@pytest.mark.determinism
@pytest.mark.local_functional
def test_snapshot_hashes_files_and_excludes_runtime_artifacts(tmp_path):
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir(); (tmp_path / ".pytest_cache" / "x").write_text("ignored", encoding="utf-8")
    first = snapshot_project(tmp_path, entrypoints=("app.py",))
    second = snapshot_project(tmp_path, entrypoints=("app.py",))
    assert first.snapshot_hash == second.snapshot_hash
    assert [row["path"] for row in first.files] == ["app.py"]
    assert first.excluded_files == (".pytest_cache/x",)
