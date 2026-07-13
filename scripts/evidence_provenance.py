from __future__ import annotations

import hashlib
import json
import pathlib
import struct
from datetime import datetime, timezone
from typing import Any


PROVENANCE_STATUSES = {"claimed", "observed", "verified", "rejected"}
SOURCE_TYPES = {"agent", "runner", "browser", "process", "pytest", "provider", "local_model", "packager", "evaluator"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _png_size(path: pathlib.Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _is_valid_png(path: pathlib.Path) -> bool:
    size = _png_size(path)
    return bool(size and size[0] > 0 and size[1] > 0)


class EvidenceProvenanceLedger:
    def __init__(self, path: str | pathlib.Path, *, run_id: str, candidate_id: str, root: str | pathlib.Path | None = None) -> None:
        self.path = pathlib.Path(path)
        self.run_id = run_id
        self.candidate_id = candidate_id
        self.root = pathlib.Path(root).resolve() if root else self.path.parent.resolve()

    def append(
        self,
        *,
        task_id: str,
        leaf_id: str,
        source_process_id: str,
        source_type: str,
        provenance_status: str,
        artifact_refs: list[str] | None = None,
        hashes: dict[str, str] | None = None,
        verification_method: str = "",
        verified_by: str = "",
        result: str = "NOT_EVALUATED",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if provenance_status not in PROVENANCE_STATUSES:
            raise ValueError(f"invalid provenance_status: {provenance_status}")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {source_type}")
        row = {
            "evidence_id": self._id(task_id, source_process_id, artifact_refs or [], provenance_status),
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "task_id": task_id,
            "leaf_id": leaf_id,
            "source_process_id": source_process_id,
            "source_type": source_type,
            "provenance_status": provenance_status,
            "timestamp": utc_now(),
            "artifact_refs": list(artifact_refs or []),
            "hashes": hashes or {},
            "verification_method": verification_method,
            "verified_by": verified_by,
            "result": result,
            "data": data or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def _id(self, task_id: str, source_process_id: str, refs: list[str], status: str) -> str:
        raw = json.dumps({"run_id": self.run_id, "candidate_id": self.candidate_id, "task_id": task_id, "source": source_process_id, "refs": refs, "status": status, "t": utc_now()}, sort_keys=True)
        return "prov_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def verify_artifact(self, evidence_id: str, *, verified_by: str = "evaluator", require_png: bool = False) -> dict[str, Any]:
        row = next((item for item in self.rows() if item.get("evidence_id") == evidence_id), None)
        if not row:
            raise KeyError(evidence_id)
        if row.get("provenance_status") == "claimed":
            return self.append(
                task_id=row["task_id"],
                leaf_id=row["leaf_id"],
                source_process_id=row["source_process_id"],
                source_type="evaluator",
                provenance_status="rejected",
                artifact_refs=row.get("artifact_refs", []),
                hashes=row.get("hashes", {}),
                verification_method="claimed_evidence_cannot_support_pass",
                verified_by=verified_by,
                result="NEEDS_REWORK",
                data={"source_evidence_id": evidence_id},
            )
        missing: list[str] = []
        hash_mismatch: list[str] = []
        invalid_png: list[str] = []
        for ref in row.get("artifact_refs", []):
            path = pathlib.Path(str(ref))
            resolved = path if path.is_absolute() else self.root / path
            if not resolved.exists():
                missing.append(str(ref))
                continue
            actual = sha256_file(resolved)
            expected = str(row.get("hashes", {}).get(str(ref)) or row.get("hashes", {}).get("sha256") or "")
            if expected and expected != actual:
                hash_mismatch.append(str(ref))
            if require_png and not _is_valid_png(resolved):
                invalid_png.append(str(ref))
        ok = not missing and not hash_mismatch and not invalid_png
        return self.append(
            task_id=row["task_id"],
            leaf_id=row["leaf_id"],
            source_process_id=row["source_process_id"],
            source_type="evaluator",
            provenance_status="verified" if ok else "rejected",
            artifact_refs=row.get("artifact_refs", []),
            hashes=row.get("hashes", {}),
            verification_method="artifact_hash_and_type_check",
            verified_by=verified_by,
            result="PASS" if ok else "NEEDS_REWORK",
            data={"source_evidence_id": evidence_id, "missing": missing, "hash_mismatch": hash_mismatch, "invalid_png": invalid_png},
        )


def gate_verified_evidence(rows: list[dict[str, Any]], *, required_results: list[str] | None = None, allow_rejected: bool = False) -> dict[str, Any]:
    required = set(required_results or ["PASS"])
    verified = [row for row in rows if row.get("provenance_status") == "verified" and row.get("result") in required]
    rejected = [row for row in rows if row.get("provenance_status") == "rejected"]
    claimed = [row for row in rows if row.get("provenance_status") == "claimed"]
    return {
        "status": "PASS" if verified and (allow_rejected or not rejected) else "NEEDS_REWORK",
        "verified_count": len(verified),
        "claimed_count": len(claimed),
        "rejected_count": len(rejected),
        "verified_evidence_ids": [row.get("evidence_id") for row in verified],
    }
