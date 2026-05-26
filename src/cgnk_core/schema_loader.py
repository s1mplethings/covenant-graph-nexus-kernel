from __future__ import annotations

import json
import pathlib
import warnings
from typing import Any

from .diagnostics import CGNK_SCHEMA_INVALID, Diagnostic

SCHEMA_BY_KIND = {
    "ArtifactTypeSpec": "artifact_type.schema.json",
    "ModuleContract": "module_contract.schema.json",
    "FlowSpec": "flow_spec.schema.json",
    "PolicySpec": "policy_spec.schema.json",
    "GraphEditProposal": "graph_edit_proposal.schema.json",
    "MigrationSpec": "migration_spec.schema.json",
    "ContractPack": "contract_pack.schema.json",
    "CompileResult": "compile_result.schema.json",
    "CompiledContractBundle": "compiled_contract_bundle.schema.json",
}


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SchemaLoader:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.schemas_dir = root / "schemas"
        self._validator_cls = None
        self._resolver_cls = None
        self._store: dict[str, Any] | None = None

    def _ensure_jsonschema(self):
        if self._validator_cls is not None:
            return self._validator_cls, self._resolver_cls
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from jsonschema import Draft202012Validator, RefResolver  # type: ignore
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("jsonschema is required for schema validation") from exc
        self._validator_cls = Draft202012Validator
        self._resolver_cls = RefResolver
        return Draft202012Validator, RefResolver

    def store(self) -> dict[str, Any]:
        if self._store is not None:
            return self._store
        store: dict[str, Any] = {}
        for path in self.schemas_dir.glob("*.json"):
            doc = load_json(path)
            store[str(path.resolve().as_uri())] = doc
            if "$id" in doc:
                store[str(doc["$id"])] = doc
                store[str(doc["$id"]).rsplit("/", 1)[0] + "/" + path.name] = doc
        self._store = store
        return store

    def validate(self, doc: dict[str, Any], schema_name: str | None = None, path: str = "$") -> list[Diagnostic]:
        kind = doc.get("kind")
        selected = schema_name or SCHEMA_BY_KIND.get(kind)
        if selected is None:
            return [Diagnostic(CGNK_SCHEMA_INVALID, "error", path, "No schema registered for document kind", actual=kind)]
        Draft202012Validator, RefResolver = self._ensure_jsonschema()
        schema_path = self.schemas_dir / selected
        schema = load_json(schema_path)
        resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema, store=self.store())
        validator = Draft202012Validator(schema, resolver=resolver)
        diagnostics: list[Diagnostic] = []
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            loc = ".".join(str(x) for x in err.path)
            diagnostics.append(Diagnostic(CGNK_SCHEMA_INVALID, "error", f"{path}.{loc}" if loc else path, err.message))
        return diagnostics

    def validate_examples(self) -> list[Diagnostic]:
        pairs = {
            "examples/artifacts": "artifact_type.schema.json",
            "examples/modules": "module_contract.schema.json",
            "examples/flows": "flow_spec.schema.json",
            "examples/policies": "policy_spec.schema.json",
            "examples/proposals": "graph_edit_proposal.schema.json",
            "examples/migrations": "migration_spec.schema.json",
        }
        diagnostics: list[Diagnostic] = []
        for rel, schema in pairs.items():
            for path in sorted((self.root / rel).glob("*.json")):
                diagnostics.extend(self.validate(load_json(path), schema, path.relative_to(self.root).as_posix()))
        for path in sorted(self.root.glob("examples/*.contract_pack.json")):
            diagnostics.extend(self.validate(load_json(path), "contract_pack.schema.json", path.relative_to(self.root).as_posix()))
        for path in sorted((self.root / "examples/compile_results").glob("*.json")):
            diagnostics.extend(self.validate(load_json(path), "compile_result.schema.json", path.relative_to(self.root).as_posix()))
        return diagnostics
