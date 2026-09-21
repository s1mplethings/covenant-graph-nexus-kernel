from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from cgkn.artifacts.models import ArtifactRef
from cgkn.artifacts.store import ArtifactStore


class ArtifactCache:
    def __init__(self, run_dir: pathlib.Path):
        self.root = pathlib.Path(run_dir) / "cache"

    def _path(self, node_id: str, fingerprint: str) -> pathlib.Path:
        digest = fingerprint.split(":", 1)[-1]
        return self.root / node_id / f"{digest}.json"

    def lookup(self, node_id: str, fingerprint: str, store: ArtifactStore) -> list[ArtifactRef] | None:
        path = self._path(node_id, fingerprint)
        if not path.is_file():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        refs = [ArtifactRef.from_dict(item) for item in entry.get("outputs", [])]
        if not refs:
            return None
        for ref in refs:
            try:
                artifact = store.resolve_artifact_ref(ref)
            except ValueError:
                return None
            if artifact.status != "fresh" or not store.verify_artifact_hash(ref):
                return None
        return refs

    def record(self, node_id: str, fingerprint: str, outputs: list[ArtifactRef]) -> None:
        path = self._path(node_id, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        value: dict[str, Any] = {
            "kind": "ArtifactCacheEntry",
            "fingerprint": fingerprint,
            "nodeId": node_id,
            "outputs": [item.as_dict() for item in outputs],
        }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
