from __future__ import annotations

import json
import pathlib
from typing import Any


class ArtifactValidationError(ValueError):
    pass


def _json_pointer(document: Any, fragment: str) -> Any:
    if not fragment:
        return document
    if not fragment.startswith("/"):
        raise ArtifactValidationError(f"unsupported schema fragment: #{fragment}")
    current = document
    for part in fragment[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


class ArtifactTypeRegistry:
    def __init__(self, root: pathlib.Path, specs: dict[str, dict[str, Any]] | None = None):
        self.root = pathlib.Path(root).resolve()
        self.specs = specs or self._load_specs()

    def _load_specs(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for path in sorted((self.root / "examples" / "artifacts").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            result[f"{doc['id']}@{doc['version']}"] = doc
        return result

    def get(self, artifact_type: str) -> dict[str, Any]:
        if artifact_type not in self.specs:
            raise ArtifactValidationError(f"artifact type does not exist: {artifact_type}")
        return self.specs[artifact_type]

    def content_schema(self, artifact_type: str) -> dict[str, Any]:
        spec = self.get(artifact_type)
        schema_ref = str(spec.get("schema_ref", ""))
        if not schema_ref:
            raise ArtifactValidationError(f"artifact type has no content schema: {artifact_type}")
        rel, _, fragment = schema_ref.partition("#")
        path = (self.root / rel).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactValidationError("artifact schema_ref escapes repository root") from exc
        if not path.is_file():
            raise ArtifactValidationError(f"artifact content schema does not exist: {schema_ref}")
        document = json.loads(path.read_text(encoding="utf-8"))
        selected = _json_pointer(document, fragment)
        if isinstance(selected, dict) and set(selected) == {"$ref"} and str(selected["$ref"]).startswith("#"):
            selected = _json_pointer(document, str(selected["$ref"])[1:])
        return dict(selected)

    def projection_fields(self, artifact_type: str) -> set[str]:
        return set(self.content_schema(artifact_type).get("properties", {}))

    def validate_content(self, artifact_type: str, content: Any) -> None:
        schema = self.content_schema(artifact_type)
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:  # pragma: no cover - repository test profile installs it
            raise ArtifactValidationError("jsonschema is required for artifact validation") from exc
        errors = sorted(Draft202012Validator(schema).iter_errors(content), key=lambda item: list(item.path))
        if errors:
            rendered = "; ".join(
                f"{'/'.join(str(part) for part in err.path) or '<root>'}: {err.message}" for err in errors
            )
            raise ArtifactValidationError(f"invalid {artifact_type} content: {rendered}")
