from __future__ import annotations

import json
import pathlib
import warnings

from cgkn.artifacts.types import ArtifactTypeRegistry
from cgkn.specs import spec_directory


def write_spec(directory: pathlib.Path, artifact_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sample.json").write_text(
        json.dumps({"kind": "ArtifactTypeSpec", "id": artifact_id, "version": "1"}),
        encoding="utf-8",
    )


def test_specs_directory_has_priority_over_legacy_examples(tmp_path: pathlib.Path) -> None:
    write_spec(tmp_path / "specs" / "artifacts", "artifact.formal")
    write_spec(tmp_path / "examples" / "artifacts", "artifact.legacy")

    with warnings.catch_warnings(record=True) as caught:
        registry = ArtifactTypeRegistry(tmp_path)

    assert set(registry.specs) == {"artifact.formal@1"}
    assert spec_directory(tmp_path, "artifacts") == tmp_path / "specs" / "artifacts"
    assert caught == []


def test_legacy_examples_registry_is_warning_only_fallback(tmp_path: pathlib.Path) -> None:
    write_spec(tmp_path / "examples" / "artifacts", "artifact.legacy")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        registry = ArtifactTypeRegistry(tmp_path)

    assert set(registry.specs) == {"artifact.legacy@1"}
    assert any(item.category is DeprecationWarning for item in caught)
    assert "deprecated" in str(caught[0].message)
