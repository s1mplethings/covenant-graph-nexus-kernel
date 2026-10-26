"""Content-addressed storage and derived SQLite catalog for Project Corpus v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from typing import Any, Iterator, Mapping, Sequence

from .contracts import (
    AttemptManifest,
    AttemptStatus,
    CorpusSplit,
    DEFAULT_SPLIT_SEED,
    FileRecord,
    Provenance,
    SnapshotManifest,
    SnapshotStage,
    build_benchmark_manifest,
    canonical_hash,
    canonical_json,
    derive_complexity,
    normalize_project_path,
    sha256_bytes,
    validate_identifier,
)


DEFAULT_EXCLUDES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "build",
        "dist",
        ".idea",
        ".vscode",
    }
)
PRIVATE_KEYS = frozenset(
    {
        "hidden_test",
        "hidden_tests",
        "hidden_acceptance",
        "gold",
        "gold_answer",
        "expected_output_private",
        "private_evaluator_packet",
    }
)
SECRET_PATTERNS = (
    ("authorization", re.compile(r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+")),
    ("api_key", re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*['\"]?[^\s'\",;]{8,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_token", re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\(?:Users|Documents and Settings|home)\\[^\s'\"]+)"),
    re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^\s'\"]+"),
)
LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C/C++",
    ".sh": "shell",
    ".ps1": "PowerShell",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _scan_text(value: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(value):
            findings.append({"kind": kind, "action": "QUARANTINE"})
    for pattern in ABSOLUTE_PATH_PATTERNS:
        if pattern.search(value):
            findings.append({"kind": "machine_absolute_path", "action": "QUARANTINE"})
            break
    return findings


def _scan_value(value: Any, path: str = "$") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in PRIVATE_KEYS:
                findings.append({"kind": "private_evaluator_field", "path": f"{path}.{key_text}", "action": "REJECT_PUBLIC_PACKET"})
            findings.extend(_scan_value(item, f"{path}.{key_text}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(_scan_value(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for finding in _scan_text(value):
            findings.append({**finding, "path": path})
    return findings


def _redact_text(value: str) -> str:
    output = value
    for kind, pattern in SECRET_PATTERNS:
        output = pattern.sub(f"[REDACTED:{kind}]", output)
    for pattern in ABSOLUTE_PATH_PATTERNS:
        output = pattern.sub("[REDACTED:machine_path]", output)
    return output


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize(item) for key, item in value.items() if str(key).casefold() not in PRIVATE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


@dataclass(frozen=True)
class CaptureResult:
    status: str
    corpus_entry_id: str = ""
    manifest_hash: str = ""
    reason: str = ""
    quarantine_findings: tuple[Mapping[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "corpus_entry_id": self.corpus_entry_id or None,
            "manifest_hash": self.manifest_hash or None,
            "reason": self.reason or None,
            "quarantine_findings": [dict(item) for item in self.quarantine_findings],
        }


class ProjectCorpus:
    """One local corpus root with immutable objects and a rebuildable catalog."""

    def __init__(self, root: pathlib.Path | str | None = None, *, max_file_bytes: int = 16 * 1024 * 1024):
        configured = root or os.environ.get("CGNK_PROJECT_CORPUS_ROOT")
        if not configured:
            raise ValueError("corpus root is required or CGNK_PROJECT_CORPUS_ROOT must be set")
        self.root = pathlib.Path(configured).expanduser().resolve()
        self.max_file_bytes = int(max_file_bytes)
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.objects = self.root / "objects"
        self.manifests = self.root / "manifests"
        self.snapshots = self.root / "snapshots"
        self.staging = self.root / "staging"
        self.private = self.root / "private" / "evaluator"
        self.quarantine = self.root / "quarantine"
        self.catalog_path = self.root / "catalog.sqlite3"

    def initialize(self) -> dict[str, Any]:
        for path in (self.objects, self.manifests, self.snapshots, self.staging, self.private, self.quarantine):
            path.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)
        policy = {
            "kind": "CGNKProjectCorpusRoot",
            "schema_version": "1.0",
            "created_at": _now(),
            "object_hash": "sha256",
            "catalog": "sqlite3-derived-rebuildable",
            "private_evaluator_searchable": False,
            "automatic_gc": False,
        }
        marker = self.root / "corpus.json"
        if not marker.exists():
            _write_json(marker, policy)
        return {"status": "PASS", "root": str(self.root), "catalog": str(self.catalog_path)}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.catalog_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS attempts (
              entry_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
              run_id TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
              provenance TEXT NOT NULL, split TEXT NOT NULL, project_type TEXT NOT NULL,
              languages TEXT NOT NULL, complexity TEXT NOT NULL, task_hash TEXT NOT NULL,
              source_version TEXT NOT NULL, manifest_hash TEXT NOT NULL UNIQUE,
              repair_rounds INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
              tags TEXT NOT NULL, searchable_text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_family ON attempts(family_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_search ON attempts(status, split, project_type, complexity);
            CREATE TABLE IF NOT EXISTS snapshots (
              snapshot_id TEXT PRIMARY KEY, entry_id TEXT NOT NULL, family_id TEXT NOT NULL,
              attempt_id TEXT NOT NULL, stage TEXT NOT NULL, created_at TEXT NOT NULL,
              snapshot_hash TEXT NOT NULL, parent_snapshot_id TEXT,
              FOREIGN KEY(entry_id) REFERENCES attempts(entry_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS files (
              snapshot_id TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
              size INTEGER NOT NULL, mode INTEGER NOT NULL, file_type TEXT NOT NULL, language TEXT NOT NULL,
              PRIMARY KEY(snapshot_id, path),
              FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);
            CREATE TABLE IF NOT EXISTS events (
              entry_id TEXT NOT NULL, ordinal INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY(entry_id, ordinal), FOREIGN KEY(entry_id) REFERENCES attempts(entry_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS failures (
              entry_id TEXT NOT NULL, ordinal INTEGER NOT NULL, failure_type TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY(entry_id, ordinal), FOREIGN KEY(entry_id) REFERENCES attempts(entry_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tests (
              entry_id TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY(entry_id, ordinal), FOREIGN KEY(entry_id) REFERENCES attempts(entry_id) ON DELETE CASCADE
            );
            """
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS attempt_fts USING fts5(entry_id UNINDEXED, searchable_text)"
            )
        except sqlite3.OperationalError:
            pass
        connection.commit()

    def _object_path(self, digest: str) -> pathlib.Path:
        raw = digest.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", raw):
            raise ValueError("invalid object digest")
        return self.objects / raw[:2] / raw[2:]

    def _store_object(self, content: bytes) -> str:
        digest = "sha256:" + sha256_bytes(content)
        target = self._object_path(digest)
        if target.exists():
            if target.read_bytes() != content:
                raise RuntimeError("CORRUPTION: object content does not match its hash")
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + f".tmp-{uuid.uuid4().hex}")
        temporary.write_bytes(content)
        os.replace(temporary, target)
        return digest

    def _source_files(self, source: Mapping[str, Any]) -> tuple[dict[str, bytes], list[dict[str, str]]]:
        if "files" in source:
            raw_files = source["files"]
            if not isinstance(raw_files, Mapping):
                raise ValueError("snapshot files must be a mapping")
            files = {
                normalize_project_path(str(path)): value.encode("utf-8") if isinstance(value, str) else bytes(value)
                for path, value in raw_files.items()
            }
            return files, []
        source_root = pathlib.Path(str(source["root"])).resolve()
        if not source_root.is_dir():
            raise ValueError("snapshot root must be an existing directory")
        files: dict[str, bytes] = {}
        findings: list[dict[str, str]] = []
        for current, dirs, names in os.walk(source_root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in DEFAULT_EXCLUDES]
            current_path = pathlib.Path(current)
            for name in names:
                path = current_path / name
                relative = normalize_project_path(path.relative_to(source_root).as_posix())
                if any(part in DEFAULT_EXCLUDES for part in pathlib.PurePosixPath(relative).parts):
                    continue
                if path.is_symlink():
                    findings.append({"kind": "symlink", "path": relative, "action": "QUARANTINE"})
                    continue
                size = path.stat().st_size
                if size > self.max_file_bytes:
                    findings.append({"kind": "oversized_file", "path": relative, "action": "QUARANTINE"})
                    continue
                files[relative] = path.read_bytes()
        return files, findings

    def _build_snapshot(
        self,
        *,
        family_id: str,
        attempt_id: str,
        source: Mapping[str, Any],
        ordinal: int,
    ) -> tuple[SnapshotManifest, list[dict[str, str]], dict[str, int]]:
        files, findings = self._source_files(source)
        records: list[FileRecord] = []
        source_loc = test_loc = 0
        modules: set[str] = set()
        for path, content in sorted(files.items()):
            if len(content) > self.max_file_bytes:
                findings.append({"kind": "oversized_file", "path": path, "action": "QUARANTINE"})
                continue
            text = ""
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            content_findings = _scan_text(text) if text else []
            if content_findings:
                findings.extend({**item, "path": path} for item in content_findings)
                continue
            suffix = pathlib.PurePosixPath(path).suffix.casefold()
            language = LANGUAGE_BY_SUFFIX.get(suffix, "")
            if text:
                lines = len(text.splitlines())
                if "test" in pathlib.PurePosixPath(path).parts or pathlib.PurePosixPath(path).name.startswith("test_"):
                    test_loc += lines
                else:
                    source_loc += lines
            if language:
                modules.add(str(pathlib.PurePosixPath(path).parent))
            digest = self._store_object(content)
            records.append(FileRecord(path, digest, len(content), int(source.get("mode", 0o644)), "source", language))
        snapshot_id = str(source.get("snapshot_id") or f"{attempt_id}-s{ordinal:03d}")
        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            family_id=family_id,
            attempt_id=attempt_id,
            stage=SnapshotStage(str(source["stage"])).value,
            created_at=str(source.get("created_at") or _now()),
            files=tuple(records),
            parent_snapshot_id=str(source.get("parent_snapshot_id") or ""),
            metadata=_sanitize(dict(source.get("metadata") or {})),
        )
        metrics = {
            "file_count": len(records),
            "source_loc": source_loc,
            "test_loc": test_loc,
            "module_count": len(modules),
        }
        return manifest, findings, metrics

    @staticmethod
    def assign_split(family_id: str, *, seed: int = DEFAULT_SPLIT_SEED) -> str:
        validate_identifier(family_id, field_name="family_id")
        bucket = int(sha256_bytes(f"{seed}:{family_id}".encode("utf-8"))[:8], 16) % 100
        if bucket < 70:
            return CorpusSplit.DEVELOPMENT.value
        if bucket < 85:
            return CorpusSplit.VALIDATION.value
        return CorpusSplit.FORMAL_HOLDOUT.value

    def capture_attempt(
        self,
        *,
        family_id: str,
        attempt_id: str,
        run_id: str,
        source_version: str,
        generator_version: str,
        status: str,
        provenance: str,
        public_packet: Mapping[str, Any],
        snapshots: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any] | None = None,
        lineage: Mapping[str, Any] | None = None,
        events: Sequence[Mapping[str, Any]] = (),
        tests: Sequence[Mapping[str, Any]] = (),
        failures: Sequence[Mapping[str, Any]] = (),
        repairs: Sequence[Mapping[str, Any]] = (),
        private_evaluator_packet: Mapping[str, Any] | None = None,
        split: str | None = None,
        corpus_entry_id: str | None = None,
    ) -> CaptureResult:
        self.initialize()
        family_id = validate_identifier(family_id, field_name="family_id")
        attempt_id = validate_identifier(attempt_id, field_name="attempt_id")
        run_id = validate_identifier(run_id, field_name="run_id")
        AttemptStatus(status)
        provenance_value = Provenance(provenance).value
        entry_id = validate_identifier(corpus_entry_id or f"entry-{attempt_id}", field_name="corpus_entry_id")
        public_findings = _scan_value(public_packet)
        if any(item["kind"] == "private_evaluator_field" for item in public_findings):
            raise ValueError("private evaluator material is forbidden in PUBLIC_PROJECT_PACKET")
        public_findings = [{**item, "action": "REDACT"} for item in public_findings]
        safe_public = _sanitize(dict(public_packet))
        safe_metadata = _sanitize(dict(metadata or {}))
        provenance_findings: list[dict[str, str]] = []
        if provenance_value in {Provenance.PUBLIC_REPO_DERIVED.value, Provenance.THIRD_PARTY_SEEDED.value, Provenance.BENCHMARK_DERIVED.value}:
            if not safe_metadata.get("license") or not safe_metadata.get("source_ref"):
                provenance_findings.append({"kind": "license_or_provenance_unknown", "path": "$.metadata", "action": "QUARANTINE"})
        if provenance_value == Provenance.UNKNOWN.value:
            provenance_findings.append({"kind": "provenance_unknown", "path": "$.provenance", "action": "QUARANTINE"})

        stage_dir = self.staging / f"{entry_id}-{uuid.uuid4().hex}"
        stage_dir.mkdir(parents=True, exist_ok=False)
        built: list[SnapshotManifest] = []
        all_findings = list(public_findings) + provenance_findings
        raw_complexity = dict(safe_metadata.get("complexity_metrics") or {})
        try:
            for ordinal, source in enumerate(snapshots, start=1):
                snapshot, findings, metrics = self._build_snapshot(
                    family_id=family_id, attempt_id=attempt_id, source=source, ordinal=ordinal
                )
                all_findings.extend(findings)
                built.append(snapshot)
                for key, value in metrics.items():
                    raw_complexity[key] = max(int(raw_complexity.get(key, 0)), value)
                _write_json(stage_dir / "snapshots" / f"{snapshot.snapshot_id}.json", snapshot.as_dict())
            if not built:
                raise ValueError("an attempt must contain at least one snapshot")
            raw_complexity.setdefault("dependency_count", int(safe_metadata.get("dependency_count", 0)))
            raw_complexity.setdefault("language_count", len({item.language for snapshot in built for item in snapshot.files if item.language}))
            raw_complexity.setdefault("task_episode_count", len(events))
            raw_complexity.setdefault("state_dependency_count", int(safe_metadata.get("state_dependency_count", 0)))
            raw_complexity.setdefault("capability_count", len(safe_metadata.get("selected_capabilities", ())))
            raw_complexity.setdefault("repair_rounds", len(repairs))
            raw_complexity.setdefault("knowledge_source_count", len(safe_metadata.get("evidence_refs", ())))
            raw_complexity.setdefault("version_count", len(built))
            safe_metadata["complexity_metrics"] = raw_complexity
            safe_metadata["complexity"] = derive_complexity(raw_complexity)
            quarantined = any(item.get("action") == "QUARANTINE" for item in all_findings)
            effective_status = AttemptStatus.QUARANTINED.value if quarantined else status
            effective_split = CorpusSplit.QUARANTINE.value if quarantined else CorpusSplit(split or self.assign_split(family_id)).value
            private_ref = ""
            if private_evaluator_packet is not None:
                private_body = {
                    "kind": "CGNKPrivateEvaluatorPacket",
                    "schema_version": "1.0",
                    "family_id": family_id,
                    "attempt_id": attempt_id,
                    "payload": dict(private_evaluator_packet),
                }
                private_ref = canonical_hash(private_body)
                _write_json(self.private / f"{private_ref.removeprefix('sha256:')}.json", private_body)
            task_hash = str(safe_public.get("task_hash") or canonical_hash(safe_public))
            manifest = AttemptManifest(
                corpus_entry_id=entry_id,
                family_id=family_id,
                attempt_id=attempt_id,
                run_id=run_id,
                created_at=_now(),
                source_version=str(source_version),
                generator_version=str(generator_version),
                task_hash=task_hash,
                status=effective_status,
                provenance=provenance_value,
                split=effective_split,
                public_packet=safe_public,
                snapshots=tuple(built),
                metadata=safe_metadata,
                lineage=_sanitize(dict(lineage or {})),
                events=tuple(_sanitize(dict(item)) for item in events),
                tests=tuple(_sanitize(dict(item)) for item in tests),
                failures=tuple(_sanitize(dict(item)) for item in failures),
                repairs=tuple(_sanitize(dict(item)) for item in repairs),
                private_evaluator_ref=private_ref,
            )
            _write_json(stage_dir / "attempt.json", manifest.as_dict())
            final_manifest = self.manifests / f"{entry_id}.json"
            if final_manifest.exists():
                existing = _read_json(final_manifest)
                if existing.get("manifest_hash") != manifest.manifest_hash:
                    raise ValueError("corpus_entry_id already exists with different content")
                shutil.rmtree(stage_dir)
                return CaptureResult("PASS", entry_id, manifest.manifest_hash, quarantine_findings=tuple(all_findings))
            for snapshot in built:
                staged = stage_dir / "snapshots" / f"{snapshot.snapshot_id}.json"
                destination = self.snapshots / f"{snapshot.snapshot_id}.json"
                if destination.exists() and _read_json(destination).get("snapshot_hash") != snapshot.snapshot_hash:
                    raise ValueError("snapshot_id already exists with different content")
                if not destination.exists():
                    os.replace(staged, destination)
            os.replace(stage_dir / "attempt.json", final_manifest)
            self._index_manifest(manifest)
            shutil.rmtree(stage_dir, ignore_errors=True)
            return CaptureResult(
                "QUARANTINED" if quarantined else "PASS",
                entry_id,
                manifest.manifest_hash,
                quarantine_findings=tuple(all_findings),
            )
        except Exception as exc:
            _write_json(stage_dir / "incomplete.json", {"status": "INCOMPLETE", "error_type": type(exc).__name__, "recorded_at": _now()})
            raise

    def _index_manifest(self, manifest: AttemptManifest) -> None:
        metadata = dict(manifest.metadata)
        languages = sorted({item.language for snapshot in manifest.snapshots for item in snapshot.files if item.language})
        tags = sorted(str(item) for item in metadata.get("tags", ()))
        searchable = " ".join(
            [
                manifest.family_id,
                manifest.attempt_id,
                str(metadata.get("project_type", "OTHER")),
                manifest.status,
                *languages,
                *tags,
                json.dumps(manifest.public_packet, ensure_ascii=False, sort_keys=True),
            ]
        )
        row = (
            manifest.corpus_entry_id,
            manifest.family_id,
            manifest.attempt_id,
            manifest.run_id,
            manifest.created_at,
            manifest.status,
            manifest.provenance,
            manifest.split,
            str(metadata.get("project_type", "OTHER")),
            json.dumps(languages),
            str(metadata.get("complexity", "LOW")),
            manifest.task_hash,
            manifest.source_version,
            manifest.manifest_hash,
            len(manifest.repairs),
            str(metadata.get("provider", "")),
            str(metadata.get("model", "")),
            json.dumps(tags),
            searchable,
        )
        with self._connect() as connection:
            self._create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
            connection.execute("DELETE FROM snapshots WHERE entry_id=?", (manifest.corpus_entry_id,))
            connection.execute("DELETE FROM events WHERE entry_id=?", (manifest.corpus_entry_id,))
            connection.execute("DELETE FROM failures WHERE entry_id=?", (manifest.corpus_entry_id,))
            connection.execute("DELETE FROM tests WHERE entry_id=?", (manifest.corpus_entry_id,))
            for snapshot in manifest.snapshots:
                connection.execute(
                    "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                    (
                        snapshot.snapshot_id,
                        manifest.corpus_entry_id,
                        manifest.family_id,
                        manifest.attempt_id,
                        snapshot.stage,
                        snapshot.created_at,
                        snapshot.snapshot_hash,
                        snapshot.parent_snapshot_id or None,
                    ),
                )
                for item in snapshot.files:
                    connection.execute(
                        "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                        (snapshot.snapshot_id, item.path, item.content_hash, item.size, item.mode, item.file_type, item.language),
                    )
            for table, rows, discriminator in (
                ("events", manifest.events, "kind"),
                ("failures", manifest.failures, "failure_type"),
                ("tests", manifest.tests, "status"),
            ):
                for ordinal, item in enumerate(rows):
                    connection.execute(
                        f"INSERT INTO {table} VALUES (?,?,?,?)",
                        (manifest.corpus_entry_id, ordinal, str(item.get(discriminator, "UNKNOWN")), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )
            try:
                connection.execute("DELETE FROM attempt_fts WHERE entry_id=?", (manifest.corpus_entry_id,))
                connection.execute("INSERT INTO attempt_fts(entry_id, searchable_text) VALUES (?,?)", (manifest.corpus_entry_id, searchable))
            except sqlite3.OperationalError:
                pass
            connection.commit()

    def _load_snapshot(self, snapshot_id: str) -> SnapshotManifest:
        validate_identifier(snapshot_id, field_name="snapshot_id")
        return SnapshotManifest.from_dict(_read_json(self.snapshots / f"{snapshot_id}.json"))

    def show(self, entry_id: str) -> dict[str, Any]:
        validate_identifier(entry_id, field_name="entry_id")
        return _read_json(self.manifests / f"{entry_id}.json")

    def list_attempts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT entry_id,family_id,attempt_id,status,split,project_type,complexity,created_at FROM attempts ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 10000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, **filters: Any) -> list[dict[str, Any]]:
        allowed = {"family_id", "status", "split", "project_type", "complexity", "provider", "model"}
        clauses: list[str] = ["split <> 'QUARANTINE'"]
        values: list[Any] = []
        for key, value in filters.items():
            if key in allowed and value not in (None, ""):
                clauses.append(f"{key}=?")
                values.append(str(value))
        text = str(filters.get("text") or "").strip()
        if text:
            clauses.append("searchable_text LIKE ?")
            values.append(f"%{text}%")
        query = "SELECT entry_id,family_id,attempt_id,status,split,project_type,languages,complexity,repair_rounds,created_at FROM attempts WHERE " + " AND ".join(clauses) + " ORDER BY created_at,entry_id"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, values).fetchall()]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            attempts = int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
            families = int(connection.execute("SELECT COUNT(DISTINCT family_id) FROM attempts").fetchone()[0])
            snapshots = int(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            refs = int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            logical = int(connection.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0])
            statuses = {row[0]: int(row[1]) for row in connection.execute("SELECT status,COUNT(*) FROM attempts GROUP BY status")}
            complexity = {row[0]: int(row[1]) for row in connection.execute("SELECT complexity,COUNT(*) FROM attempts GROUP BY complexity")}
        object_paths = [path for path in self.objects.glob("*/*") if path.is_file()]
        physical = sum(path.stat().st_size for path in object_paths)
        return {
            "families": families,
            "attempts": attempts,
            "snapshots": snapshots,
            "objects": len(object_paths),
            "object_references": refs,
            "logical_bytes": logical,
            "physical_bytes": physical,
            "dedup_ratio": round(logical / physical, 6) if physical else 1.0,
            "statuses": statuses,
            "complexity": complexity,
        }

    def reconstruct(self, snapshot_id: str, target: pathlib.Path | str) -> dict[str, Any]:
        manifest = self._load_snapshot(snapshot_id)
        destination = pathlib.Path(target).resolve()
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("reconstruction target must be empty")
        destination.mkdir(parents=True, exist_ok=True)
        for item in manifest.files:
            target_path = (destination / pathlib.PurePosixPath(item.path)).resolve()
            if destination not in target_path.parents:
                raise ValueError("reconstruction path escapes target")
            content = self._object_path(item.content_hash).read_bytes()
            if "sha256:" + sha256_bytes(content) != item.content_hash:
                raise RuntimeError("CORRUPTION: object hash mismatch")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
            target_path.chmod(item.mode)
        return {"status": "PASS", "snapshot_id": snapshot_id, "file_count": len(manifest.files), "snapshot_hash": manifest.snapshot_hash}

    def verify(self) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        referenced: set[str] = set()
        manifests = list(self.manifests.glob("*.json"))
        for path in manifests:
            try:
                value = _read_json(path)
                snapshot_values = [self._load_snapshot(str(item["snapshot_id"])) for item in value.get("snapshot_refs", ())]
                manifest = AttemptManifest.from_dict(value, snapshots=snapshot_values)
                for snapshot in manifest.snapshots:
                    for item in snapshot.files:
                        referenced.add(item.content_hash)
                        object_path = self._object_path(item.content_hash)
                        if not object_path.is_file():
                            errors.append({"code": "OBJECT_MISSING", "ref": item.content_hash})
                        elif "sha256:" + sha256_bytes(object_path.read_bytes()) != item.content_hash:
                            errors.append({"code": "OBJECT_HASH_MISMATCH", "ref": item.content_hash})
            except Exception as exc:
                errors.append({"code": "MANIFEST_INVALID", "ref": path.name, "error": type(exc).__name__})
        with self._connect() as connection:
            catalog_refs = {row[0] for row in connection.execute("SELECT manifest_hash FROM attempts")}
        manifest_hashes = {_read_json(path).get("manifest_hash") for path in manifests}
        if catalog_refs != manifest_hashes:
            errors.append({"code": "CATALOG_MANIFEST_MISMATCH", "ref": "catalog.sqlite3"})
        objects = {"sha256:" + path.parent.name + path.name for path in self.objects.glob("*/*") if path.is_file()}
        return {
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            "manifests": len(manifests),
            "referenced_objects": len(referenced),
            "unreferenced_objects": sorted(objects - referenced),
            "staged_entries": len(list(self.staging.glob("*/incomplete.json"))),
        }

    def recover_staging(self) -> dict[str, Any]:
        incomplete = sorted(path.parent.name for path in self.staging.glob("*/incomplete.json"))
        return {"status": "PASS", "incomplete_entries": incomplete, "action": "REPORT_ONLY"}

    def rebuild_catalog(self) -> dict[str, Any]:
        if self.catalog_path.exists():
            self.catalog_path.unlink()
        with self._connect() as connection:
            self._create_schema(connection)
        count = 0
        for path in sorted(self.manifests.glob("*.json")):
            value = _read_json(path)
            snapshots = tuple(self._load_snapshot(str(item["snapshot_id"])) for item in value.get("snapshot_refs", ()))
            manifest = AttemptManifest.from_dict(value, snapshots=snapshots)
            self._index_manifest(manifest)
            count += 1
        return {"status": "PASS", "rebuilt_entries": count}

    def benchmark_sample(self, *, count: int, seed: int = DEFAULT_SPLIT_SEED, **filters: Any) -> dict[str, Any]:
        import random

        candidates = self.search(**filters)
        rng = random.Random(int(seed))
        selected = rng.sample(candidates, min(max(int(count), 0), len(candidates)))
        entries = [
            {"entry_id": item["entry_id"], "family_id": item["family_id"], "attempt_id": item["attempt_id"]}
            for item in selected
        ]
        return build_benchmark_manifest(entries, seed=seed, selection_rules={**filters, "count": count})

    def check_split_leakage(self) -> dict[str, Any]:
        leaks: list[dict[str, str]] = []
        with self._connect() as connection:
            families = connection.execute("SELECT family_id,COUNT(DISTINCT split) FROM attempts GROUP BY family_id HAVING COUNT(DISTINCT split)>1").fetchall()
            for row in families:
                leaks.append({"kind": "FAMILY_SPLIT", "family_id": row[0]})
            rows = connection.execute("SELECT entry_id,family_id,split,task_hash FROM attempts WHERE split <> 'QUARANTINE'").fetchall()
        by_task: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_task.setdefault(str(row["task_hash"]), []).append(row)
        for task_hash, matches in by_task.items():
            if len({row["split"] for row in matches}) > 1:
                leaks.append({"kind": "TASK_HASH_SPLIT", "task_hash": task_hash})
        return {"status": "PASS" if not leaks else "SPLIT_LEAKAGE", "leaks": leaks}

    def export_family(self, family_id: str, output: pathlib.Path | str) -> dict[str, Any]:
        validate_identifier(family_id, field_name="family_id")
        destination = pathlib.Path(output).resolve()
        with self._connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT entry_id FROM attempts WHERE family_id=? AND split <> 'QUARANTINE'", (family_id,))]
        if not ids:
            raise ValueError("no exportable family found")
        destination.parent.mkdir(parents=True, exist_ok=True)
        object_refs: set[str] = set()
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry_id in ids:
                manifest = self.show(entry_id)
                archive.writestr(f"manifests/{entry_id}.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
                for ref in manifest.get("snapshot_refs", ()):
                    snapshot_id = str(ref["snapshot_id"])
                    snapshot = _read_json(self.snapshots / f"{snapshot_id}.json")
                    archive.writestr(f"snapshots/{snapshot_id}.json", json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
                    object_refs.update(str(item["content_hash"]) for item in snapshot.get("files", ()))
            for digest in sorted(object_refs):
                raw = digest.removeprefix("sha256:")
                archive.write(self._object_path(digest), f"objects/{raw[:2]}/{raw[2:]}")
            archive.writestr("bundle.json", json.dumps({"kind": "CGNKPortableCorpusBundle", "schema_version": "1.0", "family_id": family_id, "entry_ids": ids}, sort_keys=True, indent=2) + "\n")
        return {"status": "PASS", "family_id": family_id, "entries": len(ids), "objects": len(object_refs), "output": str(destination)}

    def import_bundle(self, archive_path: pathlib.Path | str) -> dict[str, Any]:
        self.initialize()
        source = pathlib.Path(archive_path).resolve()
        imported = 0
        with tempfile.TemporaryDirectory(prefix="cgnk-corpus-import-") as temporary:
            target = pathlib.Path(temporary)
            with zipfile.ZipFile(source) as archive:
                members = archive.infolist()
                if len(members) > 100_000:
                    raise ValueError("archive has too many members")
                total_size = sum(info.file_size for info in members)
                if total_size > max(self.max_file_bytes * 16, 64 * 1024 * 1024):
                    raise ValueError("archive exceeds total uncompressed size limit")
                for info in members:
                    normalized = normalize_project_path(info.filename)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError("archive symlinks are forbidden")
                    if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > 1000:
                        raise ValueError("archive member has unsafe compression ratio")
                    destination = (target / pathlib.PurePosixPath(normalized)).resolve()
                    if target.resolve() not in destination.parents:
                        raise ValueError("archive member escapes extraction root")
                    if info.file_size > self.max_file_bytes:
                        raise ValueError("archive member exceeds size limit")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(info))
            bundle = _read_json(target / "bundle.json")
            if bundle.get("kind") != "CGNKPortableCorpusBundle" or bundle.get("schema_version") != "1.0":
                raise ValueError("unsupported portable bundle")
            family_id = validate_identifier(str(bundle.get("family_id") or ""), field_name="family_id")
            expected_entry_ids = {
                validate_identifier(str(item), field_name="entry_id")
                for item in bundle.get("entry_ids", ())
            }
            object_values: dict[str, bytes] = {}
            for object_path in sorted((target / "objects").glob("*/*")):
                content = object_path.read_bytes()
                expected = object_path.parent.name + object_path.name
                if sha256_bytes(content) != expected:
                    raise ValueError("portable object hash mismatch")
                object_values["sha256:" + expected] = content
            snapshot_values: dict[str, SnapshotManifest] = {}
            for snapshot_path in sorted((target / "snapshots").glob("*.json")):
                snapshot = SnapshotManifest.from_dict(_read_json(snapshot_path))
                if snapshot.family_id != family_id:
                    raise ValueError("portable snapshot family mismatch")
                if snapshot.snapshot_id in snapshot_values:
                    raise ValueError("duplicate portable snapshot id")
                if any(item.content_hash not in object_values and not self._object_path(item.content_hash).is_file() for item in snapshot.files):
                    raise ValueError("portable snapshot references a missing object")
                snapshot_values[snapshot.snapshot_id] = snapshot
            manifests_to_import: list[AttemptManifest] = []
            for manifest_path in sorted((target / "manifests").glob("*.json")):
                value = _read_json(manifest_path)
                refs = value.get("snapshot_refs") or ()
                snapshots = tuple(snapshot_values[str(item["snapshot_id"])] for item in refs)
                manifest = AttemptManifest.from_dict(value, snapshots=snapshots)
                if manifest.family_id != family_id:
                    raise ValueError("portable manifest family mismatch")
                manifests_to_import.append(manifest)
            if {item.corpus_entry_id for item in manifests_to_import} != expected_entry_ids:
                raise ValueError("portable entry list does not match bundle metadata")

            # Only commit after every archive member and manifest has validated.
            for content in object_values.values():
                self._store_object(content)
            for snapshot in snapshot_values.values():
                final_snapshot = self.snapshots / f"{snapshot.snapshot_id}.json"
                if final_snapshot.exists() and _read_json(final_snapshot).get("snapshot_hash") != snapshot.snapshot_hash:
                    raise ValueError("portable snapshot conflicts with local snapshot")
                if not final_snapshot.exists():
                    _write_json(final_snapshot, snapshot.as_dict())
            for manifest in manifests_to_import:
                final = self.manifests / f"{manifest.corpus_entry_id}.json"
                if final.exists() and _read_json(final).get("manifest_hash") != manifest.manifest_hash:
                    raise ValueError("portable entry conflicts with local entry")
                if not final.exists():
                    _write_json(final, manifest.as_dict())
                imported += 1
        self.rebuild_catalog()
        return {"status": "PASS", "imported_entries": imported}


def best_effort_capture(root: pathlib.Path | str | None = None, **request: Any) -> CaptureResult:
    """Capture without allowing research-storage failure to alter a project result."""

    try:
        return ProjectCorpus(root).capture_attempt(**request)
    except Exception as exc:  # intentionally isolates project execution from corpus I/O
        return CaptureResult("CAPTURE_FAILED", reason=type(exc).__name__)
