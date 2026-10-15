"""Build a complete, local Pass 5 engineering-output archive.

The archive intentionally includes unsuccessful/invalidated runs as well as the
final accepted runs. It is an engineering archive, not a formal evidence PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import zipfile


REPO = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO / "artifacts" / "function_stress_pass"
CURATED_ROOT = REPO / "cgkn-function-stress-pass" / "pass5-real-workload-recovery"
OUTPUT = REPO / "cgkn-function-stress-pass" / "CGKN_PASS5_COMPLETE_OUTPUT.zip"
SHA_FILE = OUTPUT.with_suffix(".sha256")

EXTRA_FILES = (
    REPO / "scripts" / "run_real_workload_recovery_stress.py",
    REPO / "scripts" / "build_pass5_evidence_bundle.py",
    REPO / "scripts" / "build_pass5_complete_output.py",
    REPO / "tests" / "test_real_workload_recovery_stress.py",
    REPO / "project_management" / "current" / "active_iteration.json",
    REPO / "project_management" / "backlog.json",
    REPO / "project_management" / "risks.json",
    REPO / "project_management" / "enterprise_experience.json",
    REPO
    / "project_management"
    / "summaries"
    / "ITER-103-real-workload-recovery-stress.md",
)


def excluded(path: Path) -> bool:
    return any(part in {"__pycache__", ".pytest_cache"} for part in path.parts) or path.suffix in {
        ".pyc",
        ".pyo",
    }


def iter_inputs():
    seen: set[Path] = set()
    raw_roots = sorted(RAW_ROOT.glob("20261011-pass5-*"))
    diagnostic = RAW_ROOT / "diagnose-fault-flake"
    if diagnostic.exists():
        raw_roots.append(diagnostic)

    for root in (*raw_roots, CURATED_ROOT):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or excluded(path):
                continue
            resolved = path.resolve()
            if resolved in {OUTPUT.resolve(), SHA_FILE.resolve()} or resolved in seen:
                continue
            seen.add(resolved)
            yield path

    for path in EXTRA_FILES:
        if path.is_file() and path.resolve() not in seen:
            seen.add(path.resolve())
            yield path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".zip.partial")
    entries: list[dict[str, object]] = []
    total_bytes = 0

    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for index, path in enumerate(iter_inputs(), start=1):
            relative = path.relative_to(REPO).as_posix()
            size = path.stat().st_size
            digest = sha256_file(path)
            archive.write(path, relative)
            entries.append({"path": relative, "bytes": size, "sha256": digest})
            total_bytes += size
            if index % 1000 == 0:
                print(f"archived {index} files ({total_bytes} bytes)", flush=True)

        manifest = {
            "package": "CGKN Pass 5 complete engineering output",
            "scope": {
                "raw_runs": "all 20261011-pass5-* runs plus diagnose-fault-flake",
                "curated_evidence": "complete pass5-real-workload-recovery tree",
                "implementation_and_management_records": True,
                "cache_files_excluded": ["__pycache__", ".pytest_cache", "*.pyc", "*.pyo"],
            },
            "status_boundary": {
                "engineering_result": "PASS_WITH_LIMITS",
                "formal_evidence_status": "NOT_EVALUATED",
                "24_hour_soak": "NOT_EVALUATED",
                "paid_provider_calls": 0,
            },
            "file_count": len(entries),
            "uncompressed_bytes": total_bytes,
            "files": entries,
        }
        archive.writestr(
            "COMPLETE_OUTPUT_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    os.replace(tmp, OUTPUT)
    digest = sha256_file(OUTPUT)
    SHA_FILE.write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")

    with zipfile.ZipFile(OUTPUT) as archive:
        bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad}")

    print(
        json.dumps(
            {
                "path": str(OUTPUT),
                "sha256_path": str(SHA_FILE),
                "sha256": digest,
                "file_count": len(entries) + 1,
                "uncompressed_bytes": total_bytes,
                "zip_bytes": OUTPUT.stat().st_size,
                "zip_test": "PASS",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
