from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

import psutil


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.knowledge_persistence_scaling import runner as base  # noqa: E402
from cgnk_knowledge.internalization import KnowledgeMaintenancePolicy, internalize_evidence  # noqa: E402
from cgnk_knowledge.store import ACTIVE_BUCKETS, rebuild_pack_indexes  # noqa: E402


STRATEGIES = ("S1_CHUNKED", "S2_APPEND_LOG", "S3_AUTHORITY_SIDECAR")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _checksum(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_json_bytes(payload)).hexdigest()


def _atomic_write(path: pathlib.Path, data: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return len(data)


def _write_document(path: pathlib.Path, payload: Any) -> int:
    return _atomic_write(path, _json_bytes({"payload": payload, "checksum": _checksum(payload)}))


def _read_document(path: pathlib.Path) -> Any:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document["payload"]
    if document.get("checksum") != _checksum(payload):
        raise ValueError(f"checksum mismatch: {path.name}")
    return payload


def _metadata(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": pack.get("kind"), "id": pack.get("id"), "project": pack.get("project"),
        "version": pack.get("version"), "knowledge_revision": pack.get("knowledge_revision"),
        "diagnostics": list(pack.get("diagnostics", [])),
    }


def _empty_pack(metadata: Mapping[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return rebuild_pack_indexes(
        {
            **dict(metadata),
            **{bucket: [] for bucket in ACTIVE_BUCKETS.values()},
            "archived_items": [], "discarded_items": [], "all_items": items, "knowledge_index": {},
        }
    )


def _storage(root: pathlib.Path) -> dict[str, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return {"file_count": len(files), "total_bytes": sum(path.stat().st_size for path in files)}


class ChunkedStore:
    name = "S1_CHUNKED"

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.manifest_path = root / "manifest.json"
        self.manifest: dict[str, Any] = {}

    @staticmethod
    def _branch_items(pack: Mapping[str, Any], branch: str) -> list[dict[str, Any]]:
        index = pack["knowledge_index"]
        all_items = pack["all_items"]
        return [dict(all_items[int(index["by_id"][item_id])]) for item_id in index["by_branch_ref"].get(branch, [])]

    def initialize(self, pack: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        branches: dict[str, Any] = {}
        written = 0
        for branch in sorted(pack["knowledge_index"]["by_branch_ref"]):
            items = self._branch_items(pack, branch)
            payload = {"branch_ref": branch, "items": items}
            digest = _checksum(payload)
            name = f"{hashlib.sha256(branch.encode()).hexdigest()[:16]}-r{int(pack['knowledge_revision']):09d}.json"
            written += _write_document(self.root / "chunks" / name, payload)
            branches[branch] = {"path": f"chunks/{name}", "checksum": digest, "item_count": len(items)}
        self.manifest = {"format": "CGKN_CHUNKED_1", "metadata": _metadata(pack), "branches": branches}
        written += _write_document(self.manifest_path, self.manifest)
        return {"elapsed_ms": (time.perf_counter() - started) * 1000, "bytes_written": written, **_storage(self.root)}

    def persist(self, pack: Mapping[str, Any], branch: str, _: list[str]) -> dict[str, Any]:
        started = time.perf_counter()
        items = self._branch_items(pack, branch)
        payload = {"branch_ref": branch, "items": items}
        revision = int(pack["knowledge_revision"])
        name = f"{hashlib.sha256(branch.encode()).hexdigest()[:16]}-r{revision:09d}.json"
        written = _write_document(self.root / "chunks" / name, payload)
        previous = self.manifest.get("branches", {}).get(branch, {}).get("path")
        self.manifest["metadata"] = _metadata(pack)
        self.manifest.setdefault("branches", {})[branch] = {
            "path": f"chunks/{name}", "checksum": _checksum(payload), "item_count": len(items),
        }
        written += _write_document(self.manifest_path, self.manifest)
        if previous and previous != f"chunks/{name}":
            old = (self.root / previous).resolve()
            if self.root.resolve() in old.parents and old.exists():
                old.unlink()
        return {"elapsed_ms": (time.perf_counter() - started) * 1000, "bytes_written": written, **_storage(self.root)}

    def load(self) -> dict[str, Any]:
        manifest = _read_document(self.manifest_path)
        items: list[dict[str, Any]] = []
        for branch, reference in sorted(manifest["branches"].items()):
            payload = _read_document(self.root / reference["path"])
            if payload.get("branch_ref") != branch or _checksum(payload) != reference["checksum"]:
                raise ValueError("chunk identity or checksum mismatch")
            items.extend(dict(row) for row in payload["items"])
        return _empty_pack(manifest["metadata"], items)


class AppendLogStore:
    name = "S2_APPEND_LOG"

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.log_path = root / "authority.log"
        self.checkpoint_path = root / "derived-checkpoint.json"

    @staticmethod
    def _record(payload: Any) -> bytes:
        return _json_bytes({"payload": payload, "checksum": _checksum(payload)})

    def initialize(self, pack: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ".authority.log.tmp"
        count = 0
        with temporary.open("wb") as handle:
            handle.write(self._record({"operation": "HEADER", "metadata": _metadata(pack)}))
            count += 1
            for item in sorted(pack["all_items"], key=lambda row: str(row["id"])):
                handle.write(self._record({"operation": "UPSERT", "items": [dict(item)]}))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.log_path)
        checkpoint = {
            "format": "CGKN_DERIVED_CHECKPOINT_1", "record_count": count,
            "authority_hash": base.stable_hash(base.authoritative_projection(pack)),
            "pack": base.authoritative_projection(pack),
        }
        checkpoint_bytes = _write_document(self.checkpoint_path, checkpoint)
        return {
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "bytes_written": self.log_path.stat().st_size + checkpoint_bytes,
            **_storage(self.root),
        }

    def persist(self, pack: Mapping[str, Any], _: str, changed_ids: list[str]) -> dict[str, Any]:
        started = time.perf_counter()
        index = pack["knowledge_index"]
        items = [dict(pack["all_items"][int(index["by_id"][item_id])]) for item_id in changed_ids]
        payload = {"operation": "UPSERT", "metadata": _metadata(pack), "items": items}
        record = self._record(payload)
        with self.log_path.open("ab") as handle:
            handle.write(record)
            handle.flush()
            os.fsync(handle.fileno())
        return {"elapsed_ms": (time.perf_counter() - started) * 1000, "bytes_written": len(record), **_storage(self.root)}

    def load(self, *, recover_incomplete_tail: bool = True) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        by_id: dict[str, dict[str, Any]] = {}
        with self.log_path.open("rb") as handle:
            lines = handle.readlines()
        for index, raw in enumerate(lines):
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                if recover_incomplete_tail and index == len(lines) - 1 and not raw.endswith(b"\n"):
                    break
                raise
            payload = document["payload"]
            if document.get("checksum") != _checksum(payload):
                raise ValueError(f"log checksum mismatch at record {index}")
            if payload["operation"] == "HEADER":
                metadata = dict(payload["metadata"])
            else:
                metadata.update(payload.get("metadata", {}))
                for item in payload["items"]:
                    by_id[str(item["id"])] = dict(item)
        return _empty_pack(metadata, list(by_id.values()))


class AuthoritySidecarStore:
    name = "S3_AUTHORITY_SIDECAR"

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.authority_path = root / "authority.json"
        self.sidecar_path = root / "derived-sidecar.json"

    def initialize(self, pack: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        projection = base.authoritative_projection(pack)
        written = _write_document(self.authority_path, projection)
        sidecar = {
            "format": "CGKN_DERIVED_SIDECAR_1",
            "authority_hash": base.stable_hash(projection),
            "knowledge_index": pack["knowledge_index"],
            "buckets": {name: pack[name] for name in (*ACTIVE_BUCKETS.values(), "archived_items", "discarded_items")},
        }
        written += _write_document(self.sidecar_path, sidecar)
        return {"elapsed_ms": (time.perf_counter() - started) * 1000, "bytes_written": written, **_storage(self.root)}

    def persist(self, pack: Mapping[str, Any], _: str, __: list[str]) -> dict[str, Any]:
        started = time.perf_counter()
        projection = base.authoritative_projection(pack)
        written = _write_document(self.authority_path, projection)
        return {"elapsed_ms": (time.perf_counter() - started) * 1000, "bytes_written": written, **_storage(self.root)}

    def load(self) -> tuple[dict[str, Any], str]:
        projection = _read_document(self.authority_path)
        authority_hash = base.stable_hash(projection)
        sidecar_status = "MISSING_REBUILT"
        try:
            sidecar = _read_document(self.sidecar_path)
            if sidecar.get("authority_hash") != authority_hash:
                raise ValueError("stale sidecar")
            pack = dict(projection)
            pack["knowledge_index"] = sidecar["knowledge_index"]
            pack.update(sidecar["buckets"])
            sidecar_status = "CURRENT_REUSED"
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            pack = _empty_pack(projection, [dict(row) for row in projection["all_items"]])
            sidecar_status = "STALE_OR_CORRUPT_REBUILT"
        return pack, sidecar_status


def store_for(strategy: str, root: pathlib.Path) -> Any:
    if strategy == "S1_CHUNKED":
        return ChunkedStore(root)
    if strategy == "S2_APPEND_LOG":
        return AppendLogStore(root)
    if strategy == "S3_AUTHORITY_SIDECAR":
        return AuthoritySidecarStore(root)
    raise ValueError(strategy)


def _load_strategy(strategy: str, root: pathlib.Path) -> tuple[dict[str, Any], str]:
    store = store_for(strategy, root)
    value = store.load()
    if isinstance(value, tuple):
        return value
    return value, "NOT_APPLICABLE"


def cold_worker(args: argparse.Namespace) -> int:
    result_path = pathlib.Path(args.result_path)
    with base.RssMonitor() as monitor:
        started = time.perf_counter()
        pack, cache_status = _load_strategy(args.strategy, pathlib.Path(args.store_root))
        load_ms = (time.perf_counter() - started) * 1000
        query = base.evaluate_queries(pack, base.query_cases(args.size, args.branches, args.shape), repeats=5)
        authority_hash = base.stable_hash(base.authoritative_projection(pack))
        steady = psutil.Process().memory_info().rss
    result = {
        "load_ms": round(load_ms, 3), "cache_status": cache_status,
        "authority_equivalent": authority_hash == args.expected_authority_hash,
        "query_equivalent": query["result_hash"] == args.expected_query_hash,
        "query": query, "steady_rss_bytes": steady, "peak_rss_bytes": monitor.peak,
    }
    result_path.write_text(base._stable_json(result, pretty=True) + "\n", encoding="utf-8")
    return 0


def scale_worker(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.result_path)
    root = pathlib.Path(args.store_root)
    root.mkdir(parents=True, exist_ok=True)
    with base.RssMonitor() as monitor:
        pack = base.generate_corpus(args.size, args.branches, args.shape)
        cases = base.query_cases(args.size, args.branches, args.shape)
        store = store_for(args.strategy, root)
        initial = store.initialize(pack)
        persist_rows: list[dict[str, Any]] = []
        internalize_rows: list[float] = []
        for offset in range(args.update_samples):
            branch = f"branch-{offset:04d}"
            evidence = base._update_evidence(offset, branch)
            logical_bytes = len(base._stable_json(evidence).encode("utf-8"))
            started = time.perf_counter()
            result = internalize_evidence(pack, evidence, policy=KnowledgeMaintenancePolicy.LOCAL_LAZY)
            internalize_rows.append((time.perf_counter() - started) * 1000)
            pack = result["pack"]
            changed_ids = [str(result["receipt"]["evidence_id"]), *map(str, result["receipt"]["nodes_invalidated"])]
            persistence = store.persist(pack, branch, sorted(set(changed_ids)))
            persistence["amplification"] = persistence["bytes_written"] / max(1, logical_bytes)
            persist_rows.append(persistence)
        query = base.evaluate_queries(pack, cases, repeats=5)
        expected_authority_hash = base.stable_hash(base.authoritative_projection(pack))
        expected_query_hash = query["result_hash"]
        parent_steady = psutil.Process().memory_info().rss
        del pack
        gc.collect()
        cold_path = root / "cold-result.json"
        command = [
            sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "cold",
            "--strategy", args.strategy, "--store-root", str(root), "--result-path", str(cold_path),
            "--size", str(args.size), "--branches", str(args.branches), "--shape", args.shape,
            "--expected-authority-hash", expected_authority_hash, "--expected-query-hash", expected_query_hash,
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout)
        if completed.returncode:
            raise RuntimeError(completed.stderr[-3000:])
        cold = json.loads(cold_path.read_text(encoding="utf-8"))
        cold_path.unlink()
    result = {
        "strategy": args.strategy, "scale": args.size, "branches": args.branches, "shape": args.shape,
        "initial_write": initial,
        "single_update": {
            "count": len(persist_rows),
            "internalization_ms": base.summary(internalize_rows),
            "persistence_ms": base.summary(row["elapsed_ms"] for row in persist_rows),
            "bytes_written": base.summary(row["bytes_written"] for row in persist_rows),
            "write_amplification": base.summary(row["amplification"] for row in persist_rows),
            "final_storage": _storage(root),
        },
        "cold_restart": cold,
        "parent_steady_rss_bytes": parent_steady, "parent_peak_rss_bytes": monitor.peak,
        "status": "PASS" if query["recall_pass"] and cold["authority_equivalent"] and cold["query_equivalent"] and cold["query"]["recall_pass"] else "FAIL",
    }
    output.write_text(base._stable_json(result, pretty=True) + "\n", encoding="utf-8")
    return 0


def crash_probes(workspace_root: pathlib.Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    pack = base.generate_corpus(200, 20, "uniform")
    for strategy in STRATEGIES:
        with tempfile.TemporaryDirectory(prefix=f"{strategy.lower()}-crash-", dir=workspace_root) as tmp:
            root = pathlib.Path(tmp)
            store = store_for(strategy, root)
            store.initialize(pack)
            expected = base.stable_hash(base.authoritative_projection(pack))
            if strategy == "S1_CHUNKED":
                manifest = _read_document(root / "manifest.json")
                victim = root / next(iter(manifest["branches"].values()))["path"]
                backup = victim.read_bytes()
                victim.write_bytes(backup[: len(backup) // 2])
                try:
                    store.load()
                    corruption_detected = False
                except (ValueError, json.JSONDecodeError):
                    corruption_detected = True
                victim.write_bytes(backup)
                (root / "chunks" / ".unreferenced.tmp").write_bytes(b"partial")
                recovered = base.stable_hash(base.authoritative_projection(store.load())) == expected
                results[strategy] = {"corrupt_chunk_detected": corruption_detected, "unreferenced_temp_ignored": recovered}
            elif strategy == "S2_APPEND_LOG":
                with store.log_path.open("ab") as handle:
                    handle.write(b'{"partial":')
                recovered = base.stable_hash(base.authoritative_projection(store.load())) == expected
                store.checkpoint_path.write_bytes(b"corrupt derived checkpoint")
                recovered_checkpoint = base.stable_hash(base.authoritative_projection(store.load())) == expected
                results[strategy] = {"incomplete_tail_recovered": recovered, "corrupt_checkpoint_discarded": recovered_checkpoint}
            else:
                store.sidecar_path.write_bytes(b"corrupt sidecar")
                loaded, status = store.load()
                sidecar_rebuilt = status == "STALE_OR_CORRUPT_REBUILT" and base.stable_hash(base.authoritative_projection(loaded)) == expected
                temporary = root / ".authority.json.interrupted.tmp"
                temporary.write_bytes(b"partial")
                loaded, _ = store.load()
                temp_safe = base.stable_hash(base.authoritative_projection(loaded)) == expected
                results[strategy] = {"corrupt_sidecar_rebuilt": sidecar_rebuilt, "interrupted_temp_preserves_authority": temp_safe}
    return results


def orchestrate(args: argparse.Namespace) -> int:
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = pathlib.Path(args.workspace_root).resolve() if args.workspace_root else output_dir / "tmp"
    workspace_root.mkdir(parents=True, exist_ok=True)
    sizes = [int(value) for value in args.scales.split(",") if value]
    results: list[dict[str, Any]] = []
    for size in sizes:
        for strategy in STRATEGIES:
            with tempfile.TemporaryDirectory(prefix=f"{strategy.lower()}-{size}-", dir=workspace_root) as tmp:
                result_path = output_dir / f"{strategy.lower()}-{size}.json"
                command = [
                    sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "scale",
                    "--strategy", strategy, "--store-root", tmp, "--result-path", str(result_path),
                    "--size", str(size), "--branches", str(base.branch_count_for(size)), "--shape", "uniform",
                    "--update-samples", str(args.update_samples), "--worker-timeout", str(args.worker_timeout),
                ]
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout + 60)
                if completed.returncode:
                    raise RuntimeError(completed.stderr[-4000:])
                results.append(json.loads(result_path.read_text(encoding="utf-8")))
    report = {
        "kind": "KnowledgePersistenceAlternativesBenchmark", "version": "1.0",
        "base_source": base.BASE_SOURCE, "baseline_hashes": base.benchmark_hashes(),
        "strategies": list(STRATEGIES), "results": results,
        "crash_safety": crash_probes(workspace_root),
        "production_source_modified": False,
    }
    path = output_dir / "alternatives-report.json"
    path.write_text(base._stable_json(report, pretty=True) + "\n", encoding="utf-8")
    print(base._stable_json({"report": str(path), "matrix": [{"strategy": r["strategy"], "scale": r["scale"], "status": r["status"]} for r in results]}, pretty=True))
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--profile", default="alternatives", choices=("alternatives",))
    value.add_argument("--worker", choices=("scale", "cold"))
    value.add_argument("--strategy", choices=STRATEGIES)
    value.add_argument("--output-dir", default=str(ROOT / "evidence" / "knowledge_persistence_alternatives"))
    value.add_argument("--workspace-root")
    value.add_argument("--store-root")
    value.add_argument("--result-path")
    value.add_argument("--scales", default="10000,50000,100000")
    value.add_argument("--size", type=int)
    value.add_argument("--branches", type=int)
    value.add_argument("--shape", default="uniform")
    value.add_argument("--update-samples", type=int, default=5)
    value.add_argument("--worker-timeout", type=int, default=1800)
    value.add_argument("--expected-authority-hash", default="")
    value.add_argument("--expected-query-hash", default="")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.worker == "cold":
        return cold_worker(args)
    if args.worker == "scale":
        return scale_worker(args)
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())

