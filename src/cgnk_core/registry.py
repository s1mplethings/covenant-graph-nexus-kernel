from __future__ import annotations

import pathlib
from typing import Any

from .diagnostics import CGNK_DUPLICATE_REF, CGNK_REF_INVALID, Diagnostic
from .refs import is_valid_ref, ref_of
from .schema_loader import SchemaLoader, load_json


class ContractRegistry:
    def __init__(self, root: pathlib.Path, validate_schema: bool = False):
        self.root = root
        self.schema_loader = SchemaLoader(root)
        self.diagnostics: list[Diagnostic] = []
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.modules: dict[str, dict[str, Any]] = {}
        self.flows: dict[str, dict[str, Any]] = {}
        self.policies: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.contract_packs: dict[str, dict[str, Any]] = {}
        self.migration_specs: dict[str, dict[str, Any]] = {}
        self._load_all(validate_schema)

    def _add(self, bucket: dict[str, dict[str, Any]], doc: dict[str, Any], rel_path: str, expected_kind: str, validate_schema: bool) -> None:
        ref = ref_of(doc) if "version" in doc else f"{doc['id']}@1"
        if not is_valid_ref(ref, expected_kind):
            self.diagnostics.append(Diagnostic(CGNK_REF_INVALID, "error", rel_path, "Invalid canonical ref", actual=ref))
        if ref in bucket:
            self.diagnostics.append(Diagnostic(CGNK_DUPLICATE_REF, "error", rel_path, "Duplicate contract ref", actual=ref))
        bucket[ref] = doc
        if validate_schema:
            self.diagnostics.extend(self.schema_loader.validate(doc, path=rel_path))

    def _load_dir(self, rel: str, bucket: dict[str, dict[str, Any]], expected_kind: str, validate_schema: bool) -> None:
        directory = self.root / rel
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            self._add(bucket, load_json(path), path.relative_to(self.root).as_posix(), expected_kind, validate_schema)

    def _load_all(self, validate_schema: bool) -> None:
        self._load_dir("examples/artifacts", self.artifacts, "artifact", validate_schema)
        self._load_dir("examples/modules", self.modules, "module", validate_schema)
        self._load_dir("examples/flows", self.flows, "flow", validate_schema)
        self._load_dir("examples/policies", self.policies, "policy", validate_schema)
        self._load_dir("examples/proposals", self.proposals, "proposal", validate_schema)
        self._load_dir("examples/migration_specs", self.migration_specs, "migration", validate_schema)
        self._load_dir("examples/migrations", self.migration_specs, "migration", validate_schema)
        for path in sorted(self.root.glob("examples/*.contract_pack.json")):
            doc = load_json(path)
            key = f"{doc.get('flow', path.stem)}:{doc.get('version', '1')}"
            self.contract_packs[key] = doc
            if validate_schema:
                self.diagnostics.extend(self.schema_loader.validate(doc, path=path.relative_to(self.root).as_posix()))

    def resolve_artifact(self, ref: str) -> dict[str, Any] | None:
        return self.artifacts.get(ref)

    def resolve_module(self, ref: str) -> dict[str, Any] | None:
        return self.modules.get(ref)

    def resolve_flow(self, ref: str) -> dict[str, Any] | None:
        return self.flows.get(ref)

    def resolve_policy(self, ref: str) -> dict[str, Any] | None:
        return self.policies.get(ref)
