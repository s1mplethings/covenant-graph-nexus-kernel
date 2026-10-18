from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import tempfile
from typing import Mapping

from cgkn.application.capability_builder.revision_store import CandidateRevisionStore
from cgkn.execution.contracts import utc_now

from .contracts import AssemblyReceipt, GenerationManifest, canonical_hash


class ProjectAssembler:
    def __init__(self, revision_store: CandidateRevisionStore) -> None:
        self.revision_store = revision_store

    def assemble(self, manifest: GenerationManifest, revisions: Mapping[str, str], workspace: pathlib.Path | str) -> AssemblyReceipt:
        destination = pathlib.Path(workspace).resolve()
        if set(revisions) != {item.bundle_id for item in manifest.bundle_specs}:
            raise ValueError("assembly requires one validated revision per bundle")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = pathlib.Path(tempfile.mkdtemp(prefix=".assembly-", dir=destination.parent))
        rows: dict[str, str] = {}
        source_hashes: dict[str, str] = {}
        try:
            if destination.is_dir():
                for item in destination.iterdir():
                    if item.name not in {".git", "state"}:
                        target = staging / item.name
                        shutil.copytree(item, target) if item.is_dir() else shutil.copyfile(item, target)
            for spec in manifest.bundle_specs:
                revision = self.revision_store.load_revision(revisions[spec.bundle_id])
                if revision.subject_kind != "PROJECT_BUNDLE" or revision.subject_ref != spec.bundle_id:
                    raise ValueError("bundle revision subject mismatch")
                source_hashes[spec.bundle_id] = revision.source_hash
                source = self.revision_store.source_path(revision.revision_id)
                present = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
                if present != set(spec.target_paths):
                    raise ValueError("bundle revision target manifest mismatch")
                for relative in spec.target_paths:
                    output = staging / pathlib.PurePosixPath(relative)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / pathlib.PurePosixPath(relative), output)
                    rows[relative] = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
            assembly_hash = canonical_hash(rows)
            backup = destination.with_name(destination.name + ".assembly-backup")
            if backup.exists():
                shutil.rmtree(backup)
            if destination.exists():
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
            except Exception:
                if backup.exists() and not destination.exists():
                    os.replace(backup, destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            return AssemblyReceipt(manifest.project_id, manifest.manifest_hash, tuple(revisions[item.bundle_id] for item in manifest.bundle_specs), source_hashes, tuple(sorted(rows)), assembly_hash, utc_now())
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
