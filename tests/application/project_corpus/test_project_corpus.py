from __future__ import annotations

import json
import pathlib
import sqlite3
import zipfile

import pytest

from cgkn.application.project_corpus import ProjectCorpus
from cgkn.application.project_corpus.contracts import (
    FileRecord,
    SnapshotManifest,
    build_benchmark_manifest,
    derive_complexity,
    normalize_project_path,
)


def capture(
    corpus: ProjectCorpus,
    *,
    family: str = "csv-cleaner",
    attempt: str = "attempt-1",
    status: str = "PASS",
    files: dict[str, str] | None = None,
    snapshots: list[dict] | None = None,
    **kwargs,
):
    return corpus.capture_attempt(
        family_id=family,
        attempt_id=attempt,
        run_id=f"run-{attempt}",
        source_version="source-abc",
        generator_version="generator-v1",
        status=status,
        provenance="generated_original",
        public_packet={"requirement": "Build a CSV cleaner", "constraints": ["stdlib only"]},
        snapshots=snapshots
        or [{"stage": "FINAL", "files": files or {"app.py": "print('ok')\n"}}],
        metadata={"project_type": "CLI", "provider": "fake", "model": "fake-small", "tags": ["csv"]},
        **kwargs,
    )


def test_contract_round_trip_and_strict_paths():
    record = FileRecord("src/app.py", "sha256:" + "a" * 64, 4)
    manifest = SnapshotManifest("snapshot-1", "family-1", "attempt-1", "FINAL", "2026-10-26T00:00:00Z", (record,))
    assert SnapshotManifest.from_dict(manifest.as_dict()) == manifest
    assert derive_complexity({"file_count": 2, "source_loc": 20}) == "LOW"
    with pytest.raises(ValueError):
        normalize_project_path("../secret.txt")
    with pytest.raises(ValueError):
        normalize_project_path("C:\\Users\\private.txt")


def test_capture_reconstruct_verify_and_file_level_dedup(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = capture(
        corpus,
        snapshots=[
            {"stage": "INITIAL_GENERATION", "files": {"app.py": "print('v1')\n", "README.md": "demo\n"}},
            {"stage": "FINAL", "files": {"app.py": "print('v2')\n", "README.md": "demo\n"}},
        ],
    )
    assert result.status == "PASS"
    stats = corpus.stats()
    assert stats["snapshots"] == 2
    assert stats["object_references"] == 4
    assert stats["objects"] == 3
    manifest = corpus.show(result.corpus_entry_id)
    target = tmp_path / "restored"
    receipt = corpus.reconstruct(manifest["snapshot_refs"][-1]["snapshot_id"], target)
    assert receipt["status"] == "PASS"
    assert (target / "app.py").read_bytes() == b"print('v2')\n"
    assert (target / "README.md").read_bytes() == b"demo\n"
    assert corpus.verify()["status"] == "PASS"


def test_failure_repair_pass_chain_is_preserved(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = capture(
        corpus,
        attempt="repair-1",
        snapshots=[
            {"snapshot_id": "repair-1-input", "stage": "INPUT", "files": {"requirement.txt": "add must sum\n"}},
            {"snapshot_id": "repair-1-failed", "stage": "FAILED_TEST", "files": {"calc.py": "def add(a,b): return a-b\n"}},
            {"snapshot_id": "repair-1-pre", "stage": "PRE_REPAIR", "parent_snapshot_id": "repair-1-failed", "files": {"calc.py": "def add(a,b): return a-b\n"}},
            {"snapshot_id": "repair-1-post", "stage": "POST_REPAIR", "parent_snapshot_id": "repair-1-pre", "files": {"calc.py": "def add(a,b): return a+b\n"}},
            {"snapshot_id": "repair-1-final", "stage": "FINAL", "parent_snapshot_id": "repair-1-post", "files": {"calc.py": "def add(a,b): return a+b\n"}},
        ],
        events=[{"kind": "GENERATION"}, {"kind": "REPAIR"}],
        tests=[{"status": "FAIL", "command": "pytest"}, {"status": "PASS", "command": "pytest"}],
        failures=[{"failure_type": "TEST", "fingerprint": "assertion-add"}],
        repairs=[{"failure_fingerprint": "assertion-add", "patch": "a-b -> a+b", "before_hash": "old", "after_hash": "new", "status": "FIXED"}],
        lineage={"repair_of": "repair-1-failed"},
    )
    manifest = corpus.show(result.corpus_entry_id)
    assert [item["stage"] for item in manifest["snapshot_refs"]] == ["INPUT", "FAILED_TEST", "PRE_REPAIR", "POST_REPAIR", "FINAL"]
    assert manifest["failures"][0]["failure_type"] == "TEST"
    assert manifest["repairs"][0]["status"] == "FIXED"
    assert manifest["tests"][0]["status"] == "FAIL"
    assert manifest["tests"][1]["status"] == "PASS"


def test_private_evaluator_is_separate_and_never_exported(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = capture(corpus, private_evaluator_packet={"hidden_tests": "assert secret behavior", "gold": "answer"})
    manifest = corpus.show(result.corpus_entry_id)
    assert manifest["private_evaluator_ref"].startswith("sha256:")
    assert "hidden" not in json.dumps(manifest["public_project_packet"]).casefold()
    archive = tmp_path / "family.zip"
    corpus.export_family("csv-cleaner", archive)
    with zipfile.ZipFile(archive) as bundle:
        assert all(not name.startswith("private/") for name in bundle.namelist())
        assert "hidden_tests" not in "".join(
            bundle.read(name).decode("utf-8", "ignore") for name in bundle.namelist()
        )


def test_private_field_in_public_packet_fails_closed(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    with pytest.raises(ValueError, match="private evaluator"):
        corpus.capture_attempt(
            family_id="family", attempt_id="attempt", run_id="run", source_version="s", generator_version="g",
            status="PASS", provenance="generated_original",
            public_packet={"requirement": "ok", "hidden_tests": ["secret"]},
            snapshots=[{"stage": "FINAL", "files": {"a.py": "pass\n"}}],
        )


@pytest.mark.parametrize(
    "content",
    [
        "API_KEY=test-abcdefghijklmno\n",
        "Authorization: Bearer abcdefghijklmnop\n",
        "path = r'C:\\Users\\alice\\secret.txt'\n",
        "key = 'sk-abcdefghijklmnopqrstuvwxyz'\n",
    ],
)
def test_secret_or_machine_path_quarantines_without_storing_content(tmp_path: pathlib.Path, content: str):
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = capture(corpus, files={"app.py": content})
    assert result.status == "QUARANTINED"
    assert corpus.search() == []
    assert content.encode() not in [path.read_bytes() for path in corpus.objects.glob("*/*")]


def test_unknown_or_unlicensed_provenance_is_quarantined(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = corpus.capture_attempt(
        family_id="third-party", attempt_id="a1", run_id="r1", source_version="s", generator_version="g",
        status="PASS", provenance="public_repo_derived", public_packet={"requirement": "demo"},
        snapshots=[{"stage": "FINAL", "files": {"README.md": "demo\n"}}], metadata={"project_type": "OTHER"},
    )
    assert result.status == "QUARANTINED"


def test_directory_capture_ignores_junk_and_rejects_symlink(tmp_path: pathlib.Path):
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text("pass\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "app.pyc").write_bytes(b"junk")
    try:
        (source / "escape").symlink_to(tmp_path / "outside.txt")
    except OSError:
        pytest.skip("symlink creation unavailable")
    corpus = ProjectCorpus(tmp_path / "corpus")
    result = capture(corpus, snapshots=[{"stage": "FINAL", "root": str(source)}])
    assert result.status == "QUARANTINED"
    snapshot = corpus._load_snapshot("attempt-1-s001")
    assert [item.path for item in snapshot.files] == ["app.py"]


def test_catalog_rebuild_and_split_is_family_stable(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    first = capture(corpus, attempt="a1")
    second = capture(corpus, attempt="a2")
    assert corpus.show(first.corpus_entry_id)["split"] == corpus.show(second.corpus_entry_id)["split"]
    corpus.catalog_path.unlink()
    assert corpus.rebuild_catalog()["rebuilt_entries"] == 2
    assert corpus.stats()["attempts"] == 2
    assert corpus.check_split_leakage()["status"] == "PASS"


def test_split_leakage_detects_same_task_across_splits(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    capture(corpus, family="family-a", attempt="a1", split="DEVELOPMENT")
    capture(corpus, family="family-b", attempt="a2", split="VALIDATION")
    assert corpus.check_split_leakage()["status"] == "SPLIT_LEAKAGE"


def test_export_import_portable_bundle(tmp_path: pathlib.Path):
    source = ProjectCorpus(tmp_path / "source")
    capture(source)
    archive = tmp_path / "family.zip"
    source.export_family("csv-cleaner", archive)
    target = ProjectCorpus(tmp_path / "target")
    assert target.import_bundle(archive)["imported_entries"] == 1
    assert target.verify()["status"] == "PASS"
    assert target.stats()["objects"] == source.stats()["objects"]


def test_malicious_archive_and_oversized_archive_are_rejected(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus", max_file_bytes=64)
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(ValueError):
        corpus.import_bundle(traversal)
    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("bundle.json", "x" * 65)
    with pytest.raises(ValueError, match="size limit"):
        corpus.import_bundle(oversized)


def test_zip_bomb_ratio_and_inconsistent_bundle_are_rejected_before_import(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus", max_file_bytes=4 * 1024 * 1024)
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", b"0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="compression ratio"):
        corpus.import_bundle(bomb)
    assert corpus.list_attempts() == []

    invalid = tmp_path / "invalid.zip"
    with zipfile.ZipFile(invalid, "w") as archive:
        archive.writestr(
            "bundle.json",
            json.dumps(
                {
                    "kind": "CGNKPortableCorpusBundle",
                    "schema_version": "1.0",
                    "family_id": "family-a",
                    "entry_ids": ["missing-entry"],
                }
            ),
        )
    with pytest.raises(ValueError, match="entry list"):
        corpus.import_bundle(invalid)
    assert corpus.list_attempts() == []


def test_missing_object_is_integrity_failure(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    capture(corpus)
    next(corpus.objects.glob("*/*")).unlink()
    result = corpus.verify()
    assert result["status"] == "FAIL"
    assert result["errors"][0]["code"] == "OBJECT_MISSING"


def test_catalog_never_exposes_entry_when_indexing_fails(tmp_path: pathlib.Path, monkeypatch):
    corpus = ProjectCorpus(tmp_path / "corpus")
    monkeypatch.setattr(corpus, "_index_manifest", lambda manifest: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        capture(corpus)
    assert corpus.list_attempts() == []
    assert corpus.recover_staging()["incomplete_entries"]


def test_deterministic_sampling_excludes_quarantine(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    for index in range(5):
        capture(corpus, family=f"family-{index}", attempt=f"a{index}", split="DEVELOPMENT")
    capture(corpus, family="secret", attempt="q1", files={"x.py": "API_KEY=test-abcdefghijklmnop\n"})
    one = corpus.benchmark_sample(count=3, seed=5901, split="DEVELOPMENT")
    two = corpus.benchmark_sample(count=3, seed=5901, split="DEVELOPMENT")
    assert one == two
    assert len(one["entries"]) == 3
    assert all(item["family_id"] != "secret" for item in one["entries"])
    assert build_benchmark_manifest([], seed=5901, selection_rules={})["manifest_hash"].startswith("sha256:")


def test_100_snapshot_scale_and_10k_references_deduplicate(tmp_path: pathlib.Path):
    corpus = ProjectCorpus(tmp_path / "corpus")
    shared = {f"src/file_{index:03d}.py": f"VALUE = {index}\n" for index in range(100)}
    snapshots = [
        {"snapshot_id": f"scale-s{index:03d}", "stage": "POST_MATERIALIZATION", "files": shared}
        for index in range(100)
    ]
    result = capture(corpus, family="scale-family", attempt="scale-attempt", snapshots=snapshots)
    assert result.status == "PASS"
    stats = corpus.stats()
    assert stats["snapshots"] == 100
    assert stats["object_references"] == 10_000
    assert stats["objects"] == 100
    assert stats["dedup_ratio"] == 100.0
