from __future__ import annotations

import json
import pathlib

import pytest

from cgkn.application.project_corpus.contracts import (
    AttemptManifest,
    FileRecord,
    SnapshotManifest,
    build_benchmark_manifest,
    canonical_hash,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]


def _validator(name: str):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def _attempt() -> AttemptManifest:
    record = FileRecord("src/app.py", "sha256:" + "a" * 64, 1)
    snapshot = SnapshotManifest(
        "snapshot-1",
        "family-1",
        "attempt-1",
        "FINAL",
        "2026-10-26T00:00:00Z",
        (record,),
    )
    return AttemptManifest(
        corpus_entry_id="entry-1",
        family_id="family-1",
        attempt_id="attempt-1",
        run_id="run-1",
        created_at="2026-10-26T00:00:00Z",
        source_version="source-1",
        generator_version="generator-1",
        task_hash=canonical_hash({"task": "demo"}),
        status="PASS",
        provenance="generated_original",
        split="DEVELOPMENT",
        public_packet={"requirement": "demo"},
        snapshots=(snapshot,),
    )


def test_snapshot_and_entry_examples_validate_against_versioned_schemas():
    attempt = _attempt()
    assert not list(
        _validator("project_snapshot_manifest.schema.json").iter_errors(
            attempt.snapshots[0].as_dict()
        )
    )
    assert not list(
        _validator("project_corpus_entry.schema.json").iter_errors(attempt.as_dict())
    )


def test_benchmark_manifest_validates_and_hash_is_stable():
    manifest = build_benchmark_manifest(
        [{"entry_id": "entry-1", "family_id": "family-1", "attempt_id": "attempt-1"}],
        seed=5901,
        selection_rules={"split": "DEVELOPMENT"},
    )
    assert not list(
        _validator("project_benchmark_manifest.schema.json").iter_errors(manifest)
    )
    assert manifest == build_benchmark_manifest(
        [{"entry_id": "entry-1", "family_id": "family-1", "attempt_id": "attempt-1"}],
        seed=5901,
        selection_rules={"split": "DEVELOPMENT"},
    )
