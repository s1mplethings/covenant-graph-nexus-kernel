from __future__ import annotations

import json

import pytest

from cgkn.artifacts.types import ArtifactTypeRegistry, ArtifactValidationError, _json_pointer


pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.security]


def test_json_pointer_root_list_and_escaping() -> None:
    document = {"a/b": {"~key": ["zero"]}}
    assert _json_pointer(document, "") is document
    assert _json_pointer(document, "/a~1b/~0key/0") == "zero"
    with pytest.raises(ArtifactValidationError, match="unsupported"):
        _json_pointer(document, "a")


def test_registry_missing_type_schema_ref_escape_and_missing_file(tmp_path) -> None:
    with pytest.raises(ArtifactValidationError, match="does not exist"):
        ArtifactTypeRegistry(tmp_path, {}).get("artifact.none@1")
    registry = ArtifactTypeRegistry(tmp_path, {"artifact.x@1": {}})
    with pytest.raises(ArtifactValidationError, match="no content schema"):
        registry.content_schema("artifact.x@1")
    registry.specs["artifact.x@1"] = {"schema_ref": "../escape.json"}
    with pytest.raises(ArtifactValidationError, match="escapes"):
        registry.content_schema("artifact.x@1")
    registry.specs["artifact.x@1"] = {"schema_ref": "missing.json"}
    with pytest.raises(ArtifactValidationError, match="does not exist"):
        registry.content_schema("artifact.x@1")


def test_registry_local_ref_projection_and_validation(tmp_path) -> None:
    schema = {"$defs": {"Value": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}, "additionalProperties": False}}, "selected": {"$ref": "#/$defs/Value"}}
    (tmp_path / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    registry = ArtifactTypeRegistry(tmp_path, {"artifact.x@1": {"schema_ref": "schema.json#/selected"}})
    assert registry.projection_fields("artifact.x@1") == {"name"}
    registry.validate_content("artifact.x@1", {"name": "valid"})
    with pytest.raises(ArtifactValidationError, match="invalid artifact.x@1 content"):
        registry.validate_content("artifact.x@1", {"extra": True})


def test_registry_loads_specs_in_deterministic_order(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "b.json").write_text(json.dumps({"id": "artifact.b", "version": "1", "schema_ref": "schema.json"}), encoding="utf-8")
    (specs / "a.json").write_text(json.dumps({"id": "artifact.a", "version": "1", "schema_ref": "schema.json"}), encoding="utf-8")
    monkeypatch.setattr("cgkn.artifacts.types.spec_directory", lambda _root, _kind: specs)
    assert list(ArtifactTypeRegistry(tmp_path).specs) == ["artifact.a@1", "artifact.b@1"]
